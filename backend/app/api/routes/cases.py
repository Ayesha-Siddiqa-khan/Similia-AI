"""Patient and case endpoints for practitioners.

Every handler is owner-scoped: the verified user id from `require_practitioner`
is passed to the store, so another practitioner's record behaves like a 404.
"""

import json
import logging
import re
from datetime import datetime, timezone
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from langsmith import tracing_context
from pydantic import BaseModel

from app.ai.rag.case_analysis import (
    AnalysisResult,
    AnalysisStageError,
    CaseAnalyzer,
    ClaudeReasoner,
)
from app.ai.rag.case_questions import ClaudeQuestionWriter, QuestionWriter, suggest_questions
from app.ai.rag.coverage import book_completeness
from app.ai.rag.guard import embedding_paused
from app.ai.rag.report_translation import (
    ClaudeReportTranslator,
    ReportTranslator,
    UrduReport,
    build_source,
    matches_shape,
)
from app.ai.rag.retrieval import analysis_search_info, build_retriever
from app.api.auth import require_practitioner
from app.api.routes.ai_settings import get_ai_store
from app.core.config import get_settings
from app.core.vault import VaultError
from app.schemas.cases import (
    AnalysisOut,
    CaseCreate,
    CaseHistoryOut,
    CaseOut,
    CaseUpdate,
    ConsentOut,
    PatientCreate,
    PatientOut,
    PatientUpdate,
    QuestionsOut,
    ReviewIn,
    ReviewOut,
    SymptomsPut,
    UrduReportOut,
)
from app.services import ai_limits, patient_rules, report_files
from app.services.case_db import CaseStore, CaseStoreError, SupabaseCaseStore
from app.services.compatible_llm import CompatibleProviderError
from app.services.embeddings import get_embedding_provider
from app.services.knowledge_db import KnowledgeDBError
from app.services.llm import LLMProvider
from app.services.supabase import get_supabase_admin_client
from app.services.user_ai import KeyPausedError, NoUserKeyError, UserAIStore, provider_for

logger = logging.getLogger(__name__)
SearchMode = Literal["semantic", "keyword", "hybrid"]
router = APIRouter(prefix="/api", tags=["cases"])

Owner = Annotated[str, Depends(require_practitioner)]


def get_case_store() -> CaseStore:
    settings = get_settings()
    if not settings.supabase_url or not settings.supabase_secret_key:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Patient records are not configured (SUPABASE_URL / SUPABASE_SECRET_KEY missing)",
        )
    return SupabaseCaseStore(get_supabase_admin_client())


# Fixed reason codes for provider failures. Matching happens locally against the
# provider's own error message; only the code is ever logged, never the message.
_PROVIDER_REASON_HINTS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("billing", ("credit balance", "billing", "insufficient funds", "payment")),
    (
        "context_length",
        ("prompt is too long", "context length", "too many tokens", "request_too_large"),
    ),
    ("tool_choice", ("tool_choice",)),
    ("structured_output", ("output_config", "json_schema", "response_format", "schema")),
    ("max_tokens", ("max_tokens",)),
    ("sampling", ("temperature", "top_p", "top_k")),
    ("model", ("model", "not found", "does not exist")),
)


def _provider_error_type(exc: Exception) -> str:
    """The provider's error class (e.g. `invalid_request_error`), if exposed."""
    body = getattr(exc, "body", None)
    if isinstance(body, dict):
        error = body.get("error", body)
        if isinstance(error, dict) and isinstance(error.get("type"), str):
            return error["type"]
    return "unknown"


def _provider_error_reason(exc: Exception) -> str:
    """Classify a provider error without ever logging its raw message."""
    if isinstance(exc, CompatibleProviderError):
        return exc.message or {400: "invalid_request", 429: "rate_limit"}.get(
            exc.status_code, "unclassified"
        )
    message = getattr(exc, "message", "")
    text = message.lower() if isinstance(message, str) else ""
    for code, hints in _PROVIDER_REASON_HINTS:
        if any(hint in text for hint in hints):
            return code
    return "unclassified"


def _own_llm(row: dict[str, Any] | None) -> LLMProvider:
    """The signed-in practitioner's own AI provider (their key, their model)."""
    try:
        return provider_for(row)
    except NoUserKeyError:
        raise HTTPException(
            status.HTTP_428_PRECONDITION_REQUIRED,
            "Add your own AI key in AI Settings to use this feature",
        ) from None
    except KeyPausedError:
        raise HTTPException(
            status.HTTP_428_PRECONDITION_REQUIRED,
            "Your AI key is paused. Turn it on again in AI Settings to continue",
        ) from None
    except VaultError:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "Key storage is not set up correctly"
        ) from None


AIStore = Annotated[UserAIStore, Depends(get_ai_store)]


def get_question_writer(owner: Owner, ai: AIStore) -> QuestionWriter:
    return ClaudeQuestionWriter(_own_llm(ai.get(owner)))


def get_report_translator(owner: Owner, ai: AIStore) -> ReportTranslator:
    return ClaudeReportTranslator(_own_llm(ai.get(owner)))


def get_analyzer(
    owner: Owner,
    ai: AIStore,
    search_mode: Annotated[SearchMode, Query()] = "semantic",
) -> CaseAnalyzer:
    row = ai.get(owner)
    llm = _own_llm(row)
    db = get_supabase_admin_client()
    # The requested search method, with a safe fall back to keyword matching when the provider
    # stop is set or the provider cannot be used. The result says which method actually ran.
    retriever = build_retriever(search_mode, db, get_embedding_provider, paused=embedding_paused())
    return CaseAnalyzer(
        retriever,
        ClaudeReasoner(llm),
        min_similarity=get_settings().rag_min_similarity,
        completeness=lambda: book_completeness(db),
        model=llm.model,
        hourly_analysis_limit=row.get("hourly_analysis_limit") if row else None,
        daily_analysis_limit=row.get("daily_analysis_limit") if row else None,
        cache_scope=owner,
    )


Store = Annotated[CaseStore, Depends(get_case_store)]
Analyzer = Annotated[CaseAnalyzer, Depends(get_analyzer)]
Writer = Annotated[QuestionWriter, Depends(get_question_writer)]
Translator = Annotated[ReportTranslator, Depends(get_report_translator)]


def _enforce_limit(
    store: CaseStore,
    owner: str,
    kind: ai_limits.Kind,
    *,
    hourly_analysis_limit: int | None = None,
    daily_analysis_limit: int | None = None,
) -> None:
    try:
        ai_limits.enforce(
            store, owner, kind,
            hourly_analysis_limit=hourly_analysis_limit,
            daily_analysis_limit=daily_analysis_limit,
        )
    except ai_limits.RateLimitedError as limited:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            limited.message,
            headers={"Retry-After": str(limited.retry_after_seconds)},
        ) from None


def _audit_read(store: CaseStore, owner: str, action: str, entity: str, entity_id: str) -> None:
    """Record that a record was opened. Best effort: a failed log never blocks reading."""
    try:
        store.audit(owner, action, entity, entity_id)
    except CaseStoreError:
        logger.warning("Could not record %s", action)


def _found[T](row: T | None, what: str) -> T:
    if row is None:
        raise HTTPException(404, f"{what} not found")
    return row


def _analysis_out(row: dict, cautions: list[str] | None = None) -> AnalysisOut:
    """Partly indexed source books are named so the doctor knows the evidence may be incomplete."""
    passages = row.get("passages") or []
    incomplete = sorted(
        {
            p["book_title"]
            for p in passages
            if isinstance(p, dict) and p.get("book_complete") is False and p.get("book_title")
        }
    )
    return AnalysisOut(
        **{
            **row,
            "incomplete_books": incomplete,
            "cautions": cautions or [],
            **analysis_search_info(row),
        }
    )


ARCHIVED = "This patient is archived (read-only). Re-grant consent to reopen the record."
SIGNED_OFF = "This case is signed off and locked. Reopen it to make changes."
SYMPTOM_FIELDS = (
    "kind",
    "label",
    "location",
    "sensation",
    "better",
    "worse",
    "concomitants",
    "duration",
    "notes",
    "weight",
)


def _editable_case(store: CaseStore, owner: str, case_id: UUID) -> dict:
    """The owner's case, refusing edits to a signed-off (locked) record."""
    case = _found(store.get_case(owner, str(case_id)), "Case")
    if case["status"] == "signed_off":
        raise HTTPException(status.HTTP_409_CONFLICT, SIGNED_OFF)
    _live_patient(store, owner, case["patient_id"])
    return case


def _normalised(symptoms: list[dict]) -> list[tuple]:
    return [tuple(s.get(field) or "" for field in SYMPTOM_FIELDS) for s in symptoms]


# -- patients ---------------------------------------------------------------


def _patient_out(row: dict, active_consents: set[str]) -> PatientOut:
    return PatientOut(
        **row,
        is_minor=patient_rules.is_minor(row),
        is_infant=patient_rules.is_infant(row),
        consent_active=row["id"] in active_consents,
    )


def _require_guardian(patient: dict) -> None:
    if patient_rules.guardian_missing(patient):
        raise HTTPException(422, patient_rules.GUARDIAN_REQUIRED)


def _live_patient(store: CaseStore, owner: str, patient_id: str) -> dict:
    """An owned patient who is not archived. Archived records are read-only."""
    patient = _found(store.get_patient(owner, patient_id), "Patient")
    if patient.get("archived_at"):
        raise HTTPException(status.HTTP_409_CONFLICT, ARCHIVED)
    return patient


@router.post("/patients", response_model=PatientOut, status_code=201)
def create_patient(body: PatientCreate, owner: Owner, store: Store) -> PatientOut:
    if not body.consent_given:
        raise HTTPException(422, "Patient consent is required before a record can be created")
    data = body.model_dump(mode="json")
    _require_guardian(data)
    row = store.create_patient(owner, data)
    store.audit(owner, "patient.create", "patient", row["id"])
    return _patient_out(row, {row["id"]})


@router.get("/patients", response_model=list[PatientOut])
def list_patients(owner: Owner, store: Store) -> list[PatientOut]:
    active = store.active_consent_patient_ids(owner)
    return [_patient_out(r, active) for r in store.list_patients(owner)]


@router.get("/patients/{patient_id}", response_model=PatientOut)
def get_patient(patient_id: UUID, owner: Owner, store: Store) -> PatientOut:
    row = _found(store.get_patient(owner, str(patient_id)), "Patient")
    _audit_read(store, owner, "patient.view", "patient", str(patient_id))
    return _patient_out(row, store.active_consent_patient_ids(owner))


@router.patch("/patients/{patient_id}", response_model=PatientOut)
def update_patient(patient_id: UUID, body: PatientUpdate, owner: Owner, store: Store) -> PatientOut:
    current = _found(store.get_patient(owner, str(patient_id)), "Patient")
    fields = body.model_dump(mode="json", exclude_unset=True)
    archived = fields.pop("archived", None)
    if current.get("archived_at") and archived is not False:
        raise HTTPException(status.HTTP_409_CONFLICT, ARCHIVED)
    _require_guardian({**current, **fields})
    if archived is not None:
        fields["archived_at"] = datetime.now(timezone.utc).isoformat() if archived else None
    row = _found(store.update_patient(owner, str(patient_id), fields), "Patient")
    store.audit(owner, "patient.update", "patient", str(patient_id))
    return _patient_out(row, store.active_consent_patient_ids(owner))


@router.get("/patients/{patient_id}/consents", response_model=list[ConsentOut])
def patient_consents(patient_id: UUID, owner: Owner, store: Store) -> list[ConsentOut]:
    _found(store.get_patient(owner, str(patient_id)), "Patient")
    return [ConsentOut(**c) for c in store.list_consents(owner, str(patient_id))]


@router.post("/patients/{patient_id}/consent/withdraw", response_model=PatientOut)
def withdraw_consent(patient_id: UUID, owner: Owner, store: Store) -> PatientOut:
    """Stop all AI use for this patient and archive the record. Nothing is deleted."""
    _found(store.get_patient(owner, str(patient_id)), "Patient")
    if not store.withdraw_consents(owner, str(patient_id)):
        raise HTTPException(status.HTTP_409_CONFLICT, "There is no active consent to withdraw")
    row = _found(
        store.update_patient(
            owner, str(patient_id), {"archived_at": datetime.now(timezone.utc).isoformat()}
        ),
        "Patient",
    )
    store.audit(owner, "consent.withdraw", "patient", str(patient_id))
    return _patient_out(row, store.active_consent_patient_ids(owner))


@router.post("/patients/{patient_id}/consent", response_model=PatientOut, status_code=201)
def regrant_consent(patient_id: UUID, owner: Owner, store: Store) -> PatientOut:
    """Record a new consent (the patient agreed again) and reopen the record."""
    _found(store.get_patient(owner, str(patient_id)), "Patient")
    if store.has_active_consent(owner, str(patient_id)):
        raise HTTPException(status.HTTP_409_CONFLICT, "Consent is already active")
    store.add_consent(owner, str(patient_id))
    row = _found(store.update_patient(owner, str(patient_id), {"archived_at": None}), "Patient")
    store.audit(owner, "consent.grant", "patient", str(patient_id))
    return _patient_out(row, store.active_consent_patient_ids(owner))


@router.get("/patients/{patient_id}/history", response_model=list[CaseHistoryOut])
def patient_history(patient_id: UUID, owner: Owner, store: Store) -> list[CaseHistoryOut]:
    """Every case of the patient, newest first, with outcome and sign-off. No clinical detail."""
    _found(store.get_patient(owner, str(patient_id)), "Patient")
    _audit_read(store, owner, "patient.history", "patient", str(patient_id))
    items = []
    for case in store.list_cases(owner, str(patient_id)):
        analyses = store.list_analyses(owner, case["id"])
        reviews = store.list_reviews(owner, case["id"])
        review = reviews[0] if reviews else None
        items.append(
            CaseHistoryOut(
                id=case["id"],
                status=case["status"],
                chief_complaint=case["chief_complaint"],
                language=case["language"],
                created_at=case["created_at"],
                updated_at=case["updated_at"],
                analysis_count=len(analyses),
                latest_outcome=analyses[0]["outcome"] if analyses else None,
                review_decision=review["decision"] if review else None,
                chosen_remedy=review.get("chosen_remedy") if review else None,
                signed_at=review.get("signed_at") if review else None,
            )
        )
    return items


@router.get("/patients/{patient_id}/export")
def export_patient(patient_id: UUID, owner: Owner, store: Store) -> dict:
    """Everything stored about the patient as one JSON document (for the patient or a transfer)."""
    patient = _found(store.get_patient(owner, str(patient_id)), "Patient")
    cases = []
    for case in store.list_cases(owner, str(patient_id)):
        full = store.get_case(owner, case["id"]) or case
        cases.append(
            {
                **full,
                "analyses": store.list_analyses(owner, case["id"]),
                "reviews": store.list_reviews(owner, case["id"]),
            }
        )
    store.audit(owner, "patient.export", "patient", str(patient_id))
    clinical_export = (
        store.export_clinical(owner, str(patient_id), [case["id"] for case in cases])
        if isinstance(store, SupabaseCaseStore) else {}
    )
    return {
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "format": "similia-patient-export-v1",
        "patient": patient,
        "consents": store.list_consents(owner, str(patient_id)),
        "cases": cases,
        **clinical_export,
    }


@router.delete("/patients/{patient_id}", status_code=204)
def erase_patient(
    patient_id: UUID,
    owner: Owner,
    store: Store,
    confirm_identifier: Annotated[str, Query(min_length=1, max_length=64)],
) -> None:
    """Permanently erase the patient and every case, analysis and review. Cannot be undone.

    Safeguards: the record must already be archived, and the identifier must be typed.
    The audit log keeps only the action, never clinical content or the patient id.
    """
    patient = _found(store.get_patient(owner, str(patient_id)), "Patient")
    if not patient.get("archived_at"):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Archive the patient (or withdraw consent) and export the record before erasing it",
        )
    if confirm_identifier != patient["identifier"]:
        raise HTTPException(422, "The identifier you typed does not match this patient")
    if not store.delete_patient(owner, str(patient_id)):
        raise HTTPException(404, "Patient not found")
    store.audit(owner, "patient.erase", "patient", None)


# -- cases ------------------------------------------------------------------


@router.post("/cases", response_model=CaseOut, status_code=201)
def create_case(body: CaseCreate, owner: Owner, store: Store) -> CaseOut:
    _live_patient(store, owner, str(body.patient_id))
    if not store.has_active_consent(owner, str(body.patient_id)):
        raise HTTPException(409, "No active patient consent on record")
    row = store.create_case(owner, body.model_dump(mode="json"))
    store.audit(owner, "case.create", "case", row["id"])
    return CaseOut(**row)


@router.get("/cases", response_model=list[CaseOut])
def list_cases(
    owner: Owner, store: Store, patient_id: Annotated[UUID | None, Query()] = None
) -> list[CaseOut]:
    rows = store.list_cases(owner, str(patient_id) if patient_id else None)
    return [CaseOut(**r) for r in rows]


@router.get("/cases/{case_id}", response_model=CaseOut)
def get_case(case_id: UUID, owner: Owner, store: Store) -> CaseOut:
    row = _found(store.get_case(owner, str(case_id)), "Case")
    _audit_read(store, owner, "case.view", "case", str(case_id))
    return CaseOut(**row)


@router.patch("/cases/{case_id}", response_model=CaseOut)
def update_case(case_id: UUID, body: CaseUpdate, owner: Owner, store: Store) -> CaseOut:
    case = _editable_case(store, owner, case_id)
    fields = body.model_dump(exclude_unset=True)
    changed = {key: value for key, value in fields.items() if case.get(key) != value}
    if changed and case["status"] == "analyzed":
        changed["status"] = "draft"  # the earlier analysis no longer matches the case
    row = store.update_case(owner, str(case_id), changed) if changed else case
    return CaseOut(**_found(row, "Case"))


@router.put("/cases/{case_id}/symptoms", response_model=CaseOut)
def put_symptoms(case_id: UUID, body: SymptomsPut, owner: Owner, store: Store) -> CaseOut:
    case = _editable_case(store, owner, case_id)
    incoming = [s.model_dump() for s in body.symptoms]
    if _normalised(incoming) != _normalised(case["symptoms"]):
        store.replace_symptoms(owner, str(case_id), incoming)
        if case["status"] == "analyzed":
            store.update_case(owner, str(case_id), {"status": "draft"})  # analysis is now stale
    return CaseOut(**_found(store.get_case(owner, str(case_id)), "Case"))


@router.post("/cases/{case_id}/reopen", response_model=CaseOut)
def reopen_case(case_id: UUID, owner: Owner, store: Store) -> CaseOut:
    """Unlock a signed-off case. It becomes a draft: a new analysis and sign-off are required."""
    case = _found(store.get_case(owner, str(case_id)), "Case")
    if case["status"] != "signed_off":
        raise HTTPException(status.HTTP_409_CONFLICT, "Only a signed-off case can be reopened")
    row = _found(store.update_case(owner, str(case_id), {"status": "draft"}), "Case")
    store.audit(owner, "case.reopen", "case", str(case_id))
    return CaseOut(**row)


# -- AI follow-up questions ---------------------------------------------------


@router.post("/cases/{case_id}/questions", response_model=QuestionsOut)
def suggest_case_questions(
    case_id: UUID,
    owner: Owner,
    store: Store,
    writer: Writer,
    include_urdu: Annotated[bool, Query()] = False,
) -> QuestionsOut:
    """Suggest what to ask next, per step, from the chief complaint and answers so far."""
    case = _found(store.get_case(owner, str(case_id)), "Case")
    if not store.has_active_consent(owner, case["patient_id"]):
        raise HTTPException(409, "No active patient consent on record")
    if not case["chief_complaint"].strip():
        raise HTTPException(422, "Enter the chief complaint first")
    _enforce_limit(store, owner, "questions")
    store.audit(owner, "case.questions", "case", str(case_id))  # counted even if the AI call fails
    try:
        result = suggest_questions(case, writer, include_urdu)
    except Exception:
        raise HTTPException(502, "The question service failed. Try again later.") from None
    return QuestionsOut(red_flags=result.red_flags, **result.questions)


# -- analysis and review ----------------------------------------------------


@router.post("/cases/{case_id}/analyze", response_model=AnalysisOut, status_code=201)
def analyze_case(
    case_id: UUID,
    owner: Owner,
    store: Store,
    analyzer: Analyzer,
    acknowledge_red_flags: Annotated[bool, Query()] = False,
) -> AnalysisOut:
    if get_settings().clinical_workflow_enabled:
        raise HTTPException(409, "Start a new analysis in Clinical reports")
    case = _found(store.get_case(owner, str(case_id)), "Case")
    if case["status"] == "signed_off":
        raise HTTPException(status.HTTP_409_CONFLICT, SIGNED_OFF)
    patient = _live_patient(store, owner, case["patient_id"])
    if not store.has_active_consent(owner, case["patient_id"]):
        raise HTTPException(409, "No active patient consent on record")
    if not case["symptoms"] and not case["chief_complaint"].strip():
        raise HTTPException(422, "Add a chief complaint or symptoms before analysis")
    _enforce_limit(
        store, owner, "analyses",
        hourly_analysis_limit=analyzer.hourly_analysis_limit,
        daily_analysis_limit=analyzer.daily_analysis_limit,
    )
    action = "case.analyze.acknowledged_red_flags" if acknowledge_red_flags else "case.analyze"
    store.audit(owner, action, "case", str(case_id))  # counted even if the AI call fails
    infant = patient_rules.is_infant(patient)
    if infant and not acknowledge_red_flags:
        # An infant is never analysed until the practitioner confirms they assessed urgency.
        result = AnalysisResult(
            outcome="red_flag",
            red_flags=[patient_rules.INFANT_FLAG],
            retrieval={
                "requested_mode": getattr(analyzer, "requested_mode", "semantic"),
                "retrieval_mode": "not_run",
                "fallback_reason": None,
            },
        )
    else:
        try:
            with tracing_context(enabled=False):
                result = analyzer.analyze(
                    {**case, "_search_identifiers": (
                        patient.get("full_name") or "", patient.get("identifier") or "",
                    )},
                    acknowledge_red_flags=acknowledge_red_flags,
                )
        except Exception as failure:
            stage = failure.stage if isinstance(failure, AnalysisStageError) else None
            exc = failure.cause if isinstance(failure, AnalysisStageError) else failure
            reason = _provider_error_reason(exc)
            provider_status = getattr(exc, "http_status", None) or getattr(exc, "status_code", None)
            # Only the error type, status and a fixed reason code go to the log: the message
            # or traceback could contain the patient's text.
            logger.error(
                "Case analysis failed: %s (stage=%s, http_status=%s, provider_error=%s, reason=%s)",
                type(exc).__name__,
                stage or "unknown",
                provider_status,
                _provider_error_type(exc),
                reason,
            )
            if stage == "retrieve_sources" or isinstance(exc, KnowledgeDBError):
                raise HTTPException(
                    502, "The source library could not be searched. Try again later."
                ) from None
            if reason == "billing":
                if isinstance(exc, CompatibleProviderError):
                    raise HTTPException(
                        502,
                        "The selected AI provider rejected the analysis because of a billing "
                        "issue. "
                        "Check billing and available credits with that provider, then try again.",
                    ) from None
                raise HTTPException(
                    502,
                    "Claude rejected the analysis because of a billing issue. "
                    "Check billing and available credits in the Anthropic Console, then try again.",
                ) from None
            if isinstance(exc, CompatibleProviderError):
                detail = {
                    "rate_limit": "The AI provider reached its rate or quota limit. "
                    "Check the limits for your selected model, then try again.",
                    "model not found": "The selected model is unavailable to this API key. "
                    "Choose another model in AI Settings.",
                    "invalid_request": "The AI provider rejected the request for this model. "
                    "Choose another chat model in AI Settings.",
                    "account_restriction": "The AI provider blocked generation for this account. "
                    "Check API access and free-tier availability with your provider.",
                    "invalid_output": "The AI provider returned an incomplete response. "
                    "Try again or choose another chat model in AI Settings.",
                    "unavailable": "The connection to the AI provider failed or timed out. "
                    "Try again later.",
                }.get(reason)
                if detail:
                    raise HTTPException(502, detail) from None
                if exc.status_code == 503:
                    raise HTTPException(
                        502, "The AI provider returned HTTP 503 and is temporarily unavailable."
                    ) from None
                if exc.status_code >= 500:
                    raise HTTPException(
                        502, "The AI provider did not respond. Try again later."
                    ) from None
            if provider_status in (401, 403) or (
                provider_status in (400, 404) and reason == "model"
            ):
                raise HTTPException(
                    502,
                    "The AI provider rejected the analysis. "
                    "Check your key, model and billing in AI Settings.",
                ) from None
            detail = {
                "prepare_queries": "Analysis failed while preparing the search queries. "
                "Try again later.",
                "rank_sources": "Analysis failed while interpreting the retrieved sources. "
                "Try again later.",
            }.get(stage, "The analysis service failed. Try again later.")
            raise HTTPException(502, detail) from None
        if infant:
            result.red_flags = [patient_rules.INFANT_FLAG, *result.red_flags]
    row = store.save_analysis(
        owner,
        {
            "case_id": str(case_id),
            "outcome": result.outcome,
            "red_flags": result.red_flags,
            "remedies": result.remedies,
            "passages": result.passages,
            "missing_information": result.missing_information,
            "queries": (
                {"phrases": result.queries, "retrieval": result.retrieval}
                if result.retrieval else result.queries
            ),
            "model": analyzer.model or get_settings().anthropic_model,
        },
    )
    if result.outcome != "red_flag":
        store.update_case(owner, str(case_id), {"status": "analyzed"})
    return _analysis_out(row, patient_rules.cautions(patient))


def _case_cautions(store: CaseStore, owner: str, case: dict) -> list[str]:
    patient = store.get_patient(owner, case["patient_id"])
    return patient_rules.cautions(patient) if patient else []


@router.get("/cases/{case_id}/analysis", response_model=AnalysisOut)
def latest_analysis(case_id: UUID, owner: Owner, store: Store) -> AnalysisOut:
    case = _found(store.get_case(owner, str(case_id)), "Case")
    row = _found(store.latest_analysis(owner, str(case_id)), "Analysis")
    return _analysis_out(row, _case_cautions(store, owner, case))


@router.get("/cases/{case_id}/analyses", response_model=list[AnalysisOut])
def analysis_history(case_id: UUID, owner: Owner, store: Store) -> list[AnalysisOut]:
    """All earlier analyses of the case, newest first. They are immutable snapshots."""
    case = _found(store.get_case(owner, str(case_id)), "Case")
    cautions = _case_cautions(store, owner, case)
    return [_analysis_out(r, cautions) for r in store.list_analyses(owner, str(case_id))]


@router.post("/cases/{case_id}/report/urdu", response_model=UrduReportOut)
def urdu_report(
    case_id: UUID,
    owner: Owner,
    store: Store,
    translator: Translator,
    analysis_id: Annotated[UUID | None, Query()] = None,
) -> UrduReportOut:
    """Urdu text for the printable report (one AI call on the doctor's own key).

    Only the AI-written text is translated and sent: never the patient's name, ID or contact,
    and never the book passages.
    """
    case = _found(store.get_case(owner, str(case_id)), "Case")
    patient = _found(store.get_patient(owner, case["patient_id"]), "Patient")
    if not store.has_active_consent(owner, case["patient_id"]):
        raise HTTPException(409, "No active patient consent on record")
    row = (
        store.get_analysis(owner, str(analysis_id))
        if analysis_id
        else store.latest_analysis(owner, str(case_id))
    )
    analysis = _found(row, "Analysis")
    if analysis["case_id"] != str(case_id):
        raise HTTPException(404, "Analysis not found")
    _enforce_limit(store, owner, "questions")
    store.audit(owner, "case.report.urdu", "case", str(case_id))  # counted even if the call fails
    source = build_source(case, {**analysis, "cautions": patient_rules.cautions(patient)})
    try:
        urdu = translator.to_urdu(source)
    except Exception as exc:
        logger.error("Urdu report failed: %s", type(exc).__name__)
        raise HTTPException(502, "The translation service failed. Try again later.") from None
    if not matches_shape(source, urdu):
        logger.error("Urdu report rejected: the translation did not match the English items")
        raise HTTPException(502, "The translation was incomplete. Try again.")
    return UrduReportOut(analysis_id=analysis["id"], **urdu.model_dump())


class ReportFileRequest(BaseModel):
    format: Literal["pdf", "docx"]
    lang: Literal["en", "ur"] = "en"
    analysis_id: UUID | None = None
    translation: UrduReport | None = None  # required for Urdu: the translation already shown


_MEDIA = {
    "pdf": "application/pdf",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}


@router.post("/cases/{case_id}/report/file")
def report_file(case_id: UUID, body: ReportFileRequest, owner: Owner, store: Store) -> Response:
    """The report as a PDF or Word file. No AI call; nothing is stored.

    The Urdu version uses the translation the practitioner already saw: it must line up item for
    item with the English analysis or the request is refused.
    """
    case = _found(store.get_case(owner, str(case_id)), "Case")
    patient = _found(store.get_patient(owner, case["patient_id"]), "Patient")
    row = (
        store.get_analysis(owner, str(body.analysis_id))
        if body.analysis_id
        else store.latest_analysis(owner, str(case_id))
    )
    analysis = _found(row, "Analysis")
    if analysis["case_id"] != str(case_id):
        raise HTTPException(404, "Analysis not found")
    cautions = patient_rules.cautions(patient)
    translation = None
    if body.lang == "ur":
        translation = body.translation
        if translation is None:
            raise HTTPException(422, "Translate the report to Urdu first")
        source = build_source(case, {**analysis, "cautions": cautions})
        if not matches_shape(source, translation):
            raise HTTPException(
                422, "The translation does not match this analysis. Translate again."
            )
    blocks = report_files.build_blocks(
        case,
        patient,
        analysis,
        body.lang,
        translation,
        datetime.now(timezone.utc).strftime("%d %b %Y"),
        cautions,
    )
    try:
        data = (
            report_files.render_pdf(blocks, body.lang)
            if body.format == "pdf"
            else report_files.render_docx(blocks, body.lang)
        )
    except Exception as exc:
        logger.error("Report file failed: %s", type(exc).__name__)
        raise HTTPException(500, "The report file could not be created.") from None
    store.audit(owner, "case.report.download", "case", str(case_id))
    name = f"case-{str(case_id)[:8]}-report-{body.lang}.{body.format}"
    return Response(
        data,
        media_type=_MEDIA[body.format],
        headers={
            "Content-Disposition": f'attachment; filename="{name}"',
            "Cache-Control": "private, no-store",
        },
    )


def _unpack_review_row(row: dict[str, Any]) -> dict[str, Any]:
    notes = row.get("notes") or ""
    data = dict(row)
    if isinstance(notes, str) and notes.startswith("{") and notes.endswith("}"):
        try:
            parsed = json.loads(notes)
            if isinstance(parsed, dict):
                for k in (
                    "diagnosis",
                    "potency",
                    "dose",
                    "frequency",
                    "duration",
                    "instructions",
                    "urgency_disposition",
                    "include_urgent_in_pdf",
                    "practitioner_name",
                ):
                    data[k] = parsed.get(k)
                data["notes"] = parsed.get("notes")
        except Exception:
            pass
    return data


@router.post("/cases/{case_id}/review", response_model=ReviewOut, status_code=201)
def review_case(case_id: UUID, body: ReviewIn, owner: Owner, store: Store) -> ReviewOut:
    case = _found(store.get_case(owner, str(case_id)), "Case")
    if case["status"] == "signed_off":
        raise HTTPException(status.HTTP_409_CONFLICT, "This case is already signed off")
    if case["status"] != "analyzed":
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "The case changed after its last analysis. Run the analysis again before signing off.",
        )
    # Consent and archive state are checked at the moment of signing, not only at analysis.
    _live_patient(store, owner, case["patient_id"])
    if not store.has_active_consent(owner, case["patient_id"]):
        raise HTTPException(status.HTTP_409_CONFLICT, "No active patient consent on record")
    analysis = _found(store.get_analysis(owner, str(body.analysis_id)), "Analysis")
    if analysis["case_id"] != str(case_id):
        raise HTTPException(404, "Analysis not found")
    # Only the current analysis may be signed: an older one could lack later urgent findings.
    latest = store.latest_analysis(owner, str(case_id))
    if latest is None or str(latest["id"]) != str(analysis["id"]):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "There is a newer analysis of this case. Review the latest one before signing off.",
        )

    flags = analysis.get("red_flags") or []
    if flags and not (body.urgency_disposition or "").strip():
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Record your clinical assessment and disposition of the urgent findings "
            "before finalising",
        )

    if body.decision != "rejected" and not (body.chosen_remedy or "").strip():
        raise HTTPException(422, "Name the remedy you chose, or reject the analysis")
    if body.decision != "rejected" and not (body.practitioner_name or "").strip():
        raise HTTPException(422, "Enter the prescriber's name before finalising")

    prescription_meta = {
        "diagnosis": body.diagnosis,
        "potency": body.potency,
        "dose": body.dose,
        "frequency": body.frequency,
        "duration": body.duration,
        "instructions": body.instructions,
        "urgency_disposition": body.urgency_disposition,
        "include_urgent_in_pdf": body.include_urgent_in_pdf,
        "practitioner_name": (body.practitioner_name or "").strip() or None,
        "notes": body.notes,
    }
    notes_payload = json.dumps(prescription_meta)

    row = store.save_review(
        owner,
        {
            "analysis_id": str(body.analysis_id),
            "case_id": str(case_id),
            "decision": body.decision,
            "chosen_remedy": body.chosen_remedy,
            "notes": notes_payload,
        },
    )
    store.update_case(owner, str(case_id), {"status": "signed_off"})
    store.audit(owner, "case.review", "case", str(case_id))
    return ReviewOut(**_unpack_review_row(row))


@router.get("/cases/{case_id}/review", response_model=ReviewOut)
def get_case_review(case_id: UUID, owner: Owner, store: Store) -> ReviewOut:
    _found(store.get_case(owner, str(case_id)), "Case")
    reviews = store.list_reviews(owner, str(case_id))
    if not reviews:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No review recorded for this case")
    return ReviewOut(**_unpack_review_row(reviews[0]))


@router.get("/cases/{case_id}/prescription/file")
def prescription_file(case_id: UUID, owner: Owner, store: Store) -> Response:
    case = _found(store.get_case(owner, str(case_id)), "Case")
    reviews = store.list_reviews(owner, str(case_id))
    if not reviews:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No finalised prescription for this case")
    patient = _found(store.get_patient(owner, case["patient_id"]), "Patient")
    review_data = _unpack_review_row(reviews[0])
    try:
        pdf_bytes = report_files.render_prescription_pdf(case, patient, review_data)
    except Exception as exc:
        logger.error("Prescription file failed: %s", type(exc).__name__)
        raise HTTPException(500, "The prescription file could not be created.") from None
    store.audit(owner, "case.prescription.download", "case", str(case_id))
    ident = patient.get("identifier") or str(case_id)[:8]
    safe_ident = re.sub(r"[^A-Za-z0-9-]+", "-", ident).strip("-")
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="prescription-{safe_ident}.pdf"',
            "Cache-Control": "private, no-store",
        },
    )
