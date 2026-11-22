"""Patient and case endpoints for practitioners.

Every handler is owner-scoped: the verified user id from `require_practitioner`
is passed to the store, so another practitioner's record behaves like a 404.
"""

import logging
from datetime import datetime, timezone
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.ai.rag.case_analysis import AnalysisResult, CaseAnalyzer, ClaudeReasoner
from app.ai.rag.case_questions import ClaudeQuestionWriter, QuestionWriter, suggest_questions
from app.ai.rag.coverage import book_completeness
from app.ai.rag.guard import embedding_paused
from app.ai.rag.retrieval import FallbackRetriever, KeywordRetriever, Retriever, VectorRetriever
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
)
from app.services import ai_limits, patient_rules
from app.services.case_db import CaseStore, CaseStoreError, SupabaseCaseStore
from app.services.embeddings import get_embedding_provider
from app.services.llm import AnthropicLLMProvider
from app.services.supabase import get_supabase_admin_client
from app.services.user_ai import KeyPausedError, NoUserKeyError, UserAIStore, provider_for

logger = logging.getLogger(__name__)
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


def _own_llm(owner: str, ai: UserAIStore) -> AnthropicLLMProvider:
    """The signed-in practitioner's own AI provider (their key, their model)."""
    try:
        return provider_for(owner, ai)
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
    return ClaudeQuestionWriter(_own_llm(owner, ai))


def get_analyzer(owner: Owner, ai: AIStore) -> CaseAnalyzer:
    llm = _own_llm(owner, ai)
    db = get_supabase_admin_client()
    vector = VectorRetriever(db=db, embedder=get_embedding_provider())
    # While the provider stop is set, or the provider cannot be used, word matching takes over
    # (free, labelled as keyword matching in the result).
    retriever: Retriever = (
        KeywordRetriever(db)
        if embedding_paused()
        else FallbackRetriever(vector, KeywordRetriever(db))
    )
    return CaseAnalyzer(
        retriever,
        ClaudeReasoner(llm),
        min_similarity=get_settings().rag_min_similarity,
        completeness=lambda: book_completeness(db),
    )


Store = Annotated[CaseStore, Depends(get_case_store)]
Analyzer = Annotated[CaseAnalyzer, Depends(get_analyzer)]
Writer = Annotated[QuestionWriter, Depends(get_question_writer)]


def _enforce_limit(store: CaseStore, owner: str, kind: ai_limits.Kind) -> None:
    try:
        ai_limits.enforce(store, owner, kind)
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
    mode = (
        "keyword"
        if any(isinstance(p, dict) and p.get("retrieval_mode") == "keyword" for p in passages)
        else "semantic"
    )
    return AnalysisOut(
        **{
            **row,
            "incomplete_books": incomplete,
            "cautions": cautions or [],
            "retrieval_mode": mode,
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
    return {
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "format": "similia-patient-export-v1",
        "patient": patient,
        "consents": store.list_consents(owner, str(patient_id)),
        "cases": cases,
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
    case = _found(store.get_case(owner, str(case_id)), "Case")
    if case["status"] == "signed_off":
        raise HTTPException(status.HTTP_409_CONFLICT, SIGNED_OFF)
    patient = _live_patient(store, owner, case["patient_id"])
    if not store.has_active_consent(owner, case["patient_id"]):
        raise HTTPException(409, "No active patient consent on record")
    if not case["symptoms"] and not case["chief_complaint"].strip():
        raise HTTPException(422, "Add a chief complaint or symptoms before analysis")
    _enforce_limit(store, owner, "analyses")
    action = "case.analyze.acknowledged_red_flags" if acknowledge_red_flags else "case.analyze"
    store.audit(owner, action, "case", str(case_id))  # counted even if the AI call fails
    infant = patient_rules.is_infant(patient)
    if infant and not acknowledge_red_flags:
        # An infant is never analysed until the practitioner confirms they assessed urgency.
        result = AnalysisResult(outcome="red_flag", red_flags=[patient_rules.INFANT_FLAG])
    else:
        try:
            result = analyzer.analyze(case, acknowledge_red_flags=acknowledge_red_flags)
        except Exception as exc:
            # Only the error type and status go to the log: the message or traceback could
            # contain the patient's text.
            logger.error(
                "Case analysis failed: %s (http_status=%s)",
                type(exc).__name__,
                getattr(exc, "http_status", None) or getattr(exc, "status_code", None),
            )
            raise HTTPException(502, "The analysis service failed. Try again later.") from None
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
            "queries": result.queries,
            "model": get_settings().anthropic_model,
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
    analysis = _found(store.get_analysis(owner, str(body.analysis_id)), "Analysis")
    if analysis["case_id"] != str(case_id):
        raise HTTPException(404, "Analysis not found")
    if body.decision != "rejected" and not (body.chosen_remedy or "").strip():
        raise HTTPException(422, "Name the remedy you chose, or reject the analysis")
    row = store.save_review(owner, {**body.model_dump(mode="json"), "case_id": str(case_id)})
    store.update_case(owner, str(case_id), {"status": "signed_off"})
    store.audit(owner, "case.review", "case", str(case_id))
    return ReviewOut(**row)
