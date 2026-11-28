"""Patient/case API: auth, owner isolation, consent, analysis and sign-off."""

import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.ai.rag.case_analysis import (
    CaseAnalyzer,
    ClaudeReasoner,
    NormalisedCase,
    RankedOutput,
    RankedRemedy,
    SearchQuery,
)
from app.api.auth import require_practitioner
from app.api.routes import cases as cases_routes
from app.main import create_app
from app.services import knowledge_db
from app.services.compatible_llm import CompatibleProviderError
from tests.conftest import MockEmbeddingProvider
from tests.test_case_analysis import FakeReasoner, FakeRetriever, passage


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class InMemoryCaseStore:
    """Owner-scoped fake mirroring SupabaseCaseStore behaviour."""

    def __init__(self) -> None:
        self.patients: dict[str, dict] = {}
        self.consents: list[dict] = []
        self.cases: dict[str, dict] = {}
        self.symptoms: dict[str, list[dict]] = {}
        self.analyses: dict[str, dict] = {}
        self.reviews: list[dict] = []
        self.audit_rows: list[tuple] = []
        self.audit_log: list[dict] = []

    def _row(self, owner: str, data: dict[str, Any], **extra: Any) -> dict:
        return {
            **data,
            **extra,
            "id": str(uuid.uuid4()),
            "practitioner_id": owner,
            "created_at": _now(),
            "updated_at": _now(),
        }

    def create_patient(self, owner, data):
        data = dict(data)
        consent = data.pop("consent_given")
        row = self._row(owner, data, archived_at=None)
        self.patients[row["id"]] = row
        if consent:
            self.consents.append(
                {
                    "id": str(uuid.uuid4()),
                    "patient_id": row["id"],
                    "practitioner_id": owner,
                    "withdrawn_at": None,
                    "purpose": "case_taking_and_ai_analysis",
                    "text_version": "2026-11-v1",
                    "granted_at": _now(),
                }
            )
        return row

    def list_patients(self, owner):
        return [p for p in self.patients.values() if p["practitioner_id"] == owner]

    def get_patient(self, owner, patient_id):
        p = self.patients.get(patient_id)
        return p if p and p["practitioner_id"] == owner else None

    def update_patient(self, owner, patient_id, data):
        p = self.get_patient(owner, patient_id)
        if p:
            p.update(data)
        return p

    def has_active_consent(self, owner, patient_id):
        return any(
            c["patient_id"] == patient_id
            and c["practitioner_id"] == owner
            and c["withdrawn_at"] is None
            for c in self.consents
        )

    def active_consent_patient_ids(self, owner):
        return {
            c["patient_id"]
            for c in self.consents
            if c["practitioner_id"] == owner and c["withdrawn_at"] is None
        }

    def list_consents(self, owner, patient_id):
        return [
            c
            for c in reversed(self.consents)
            if c["patient_id"] == patient_id and c["practitioner_id"] == owner
        ]

    def add_consent(self, owner, patient_id):
        row = {
            **self._row(owner, {}),
            "patient_id": patient_id,
            "purpose": "case_taking_and_ai_analysis",
            "text_version": "2026-11-v1",
            "granted_at": _now(),
            "withdrawn_at": None,
        }
        self.consents.append(row)
        return row

    def withdraw_consents(self, owner, patient_id):
        active = [
            c
            for c in self.consents
            if c["patient_id"] == patient_id
            and c["practitioner_id"] == owner
            and c["withdrawn_at"] is None
        ]
        for c in active:
            c["withdrawn_at"] = _now()
        return len(active)

    def delete_patient(self, owner, patient_id):
        if not self.get_patient(owner, patient_id):
            return False
        del self.patients[patient_id]
        for cid in [k for k, c in self.cases.items() if c["patient_id"] == patient_id]:
            del self.cases[cid]
            self.symptoms.pop(cid, None)
            self.analyses = {k: a for k, a in self.analyses.items() if a["case_id"] != cid}
            self.reviews = [r for r in self.reviews if r["case_id"] != cid]
        self.consents = [c for c in self.consents if c["patient_id"] != patient_id]
        return True

    def list_analyses(self, owner, case_id):
        rows = [
            a
            for a in self.analyses.values()
            if a["practitioner_id"] == owner and a["case_id"] == case_id
        ]
        return list(reversed(rows))

    def list_reviews(self, owner, case_id):
        rows = [
            r for r in self.reviews if r["practitioner_id"] == owner and r["case_id"] == case_id
        ]
        return list(reversed(rows))

    def create_case(self, owner, data):
        row = self._row(owner, data, status="draft")
        self.cases[row["id"]] = row
        return row

    def list_cases(self, owner, patient_id):
        return [
            c
            for c in self.cases.values()
            if c["practitioner_id"] == owner
            and (patient_id is None or c["patient_id"] == patient_id)
        ]

    def get_case(self, owner, case_id):
        c = self.cases.get(case_id)
        if not c or c["practitioner_id"] != owner:
            return None
        return {**c, "symptoms": self.symptoms.get(case_id, [])}

    def update_case(self, owner, case_id, data):
        c = self.cases.get(case_id)
        if not c or c["practitioner_id"] != owner:
            return None
        c.update(data)
        return {**c, "symptoms": self.symptoms.get(case_id, [])}

    def replace_symptoms(self, owner, case_id, symptoms):
        self.symptoms[case_id] = [
            {**s, "id": str(uuid.uuid4()), "ordinal": i} for i, s in enumerate(symptoms)
        ]
        return self.symptoms[case_id]

    def save_analysis(self, owner, data):
        row = self._row(owner, data)
        self.analyses[row["id"]] = row
        return row

    def latest_analysis(self, owner, case_id):
        rows = [
            a
            for a in self.analyses.values()
            if a["practitioner_id"] == owner and a["case_id"] == case_id
        ]
        return rows[-1] if rows else None

    def get_analysis(self, owner, analysis_id):
        a = self.analyses.get(analysis_id)
        return a if a and a["practitioner_id"] == owner else None

    def save_review(self, owner, data):
        row = {**self._row(owner, data), "signed_at": _now()}
        self.reviews.append(row)
        return row

    def audit(self, owner, action, entity, entity_id):
        self.audit_rows.append((owner, action, entity, entity_id))
        self.audit_log.append({"owner": owner, "action": action, "created_at": _now()})

    def recent_actions(self, owner, actions, since):
        cut = datetime.fromisoformat(since)
        return sorted(
            r["created_at"]
            for r in self.audit_log
            if r["owner"] == owner
            and r["action"] in actions
            and datetime.fromisoformat(r["created_at"]) >= cut
        )


class Env:
    def __init__(self, client: TestClient, store: InMemoryCaseStore, who: dict) -> None:
        self.client, self.store, self._who = client, store, who

    def as_user(self, user: str) -> "Env":
        self._who["id"] = user
        return self


@pytest.fixture
def env(monkeypatch: pytest.MonkeyPatch) -> Env:
    app = create_app()
    store = InMemoryCaseStore()
    who = {"id": "doctor-a"}
    ranked = RankedOutput(
        remedies=[
            RankedRemedy(
                remedy="Belladonna", confidence="medium", rationale="fits", citations=["P1"]
            )
        ]
    )
    analyzer = CaseAnalyzer(
        FakeRetriever([passage("chunk-1")]),
        FakeReasoner(NormalisedCase(queries=[SearchQuery(text="headache")]), ranked),
    )
    app.dependency_overrides[require_practitioner] = lambda: who["id"]
    app.dependency_overrides[cases_routes.get_case_store] = lambda: store
    app.dependency_overrides[cases_routes.get_analyzer] = lambda: analyzer
    monkeypatch.setattr(cases_routes, "embedding_paused", lambda: False)

    def no_network(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("tests must never call the real LLM")

    monkeypatch.setattr(ClaudeReasoner, "normalise", no_network)
    monkeypatch.setattr(ClaudeReasoner, "rank", no_network)
    return Env(TestClient(app), store, who)


def make_patient(env: Env, consent: bool = True) -> dict:
    response = env.client.post(
        "/api/patients",
        json={
            "identifier": "P-001",
            "full_name": "Test Patient",
            "age_years": 30,
            "consent_given": consent,
        },
    )
    return response.json() if response.status_code == 201 else {"status": response.status_code}


def make_case(env: Env, complaint="headache worse in sun") -> str:
    patient = make_patient(env)
    return env.client.post(
        "/api/cases", json={"patient_id": patient["id"], "chief_complaint": complaint}
    ).json()["id"]


def test_endpoints_require_sign_in():
    client = TestClient(create_app())
    assert client.get("/api/patients").status_code == 401
    assert client.post("/api/cases/" + str(uuid.uuid4()) + "/analyze").status_code == 401


def test_patient_requires_consent(env: Env):
    assert make_patient(env, consent=False)["status"] == 422
    assert make_patient(env)["identifier"] == "P-001"
    assert ("doctor-a", "patient.create") == env.store.audit_rows[0][:2]


def test_other_practitioners_cannot_see_or_change_records(env: Env):
    case_id = make_case(env)
    patient_id = env.client.get(f"/api/cases/{case_id}").json()["patient_id"]
    env.as_user("doctor-b")
    assert env.client.get("/api/patients").json() == []
    assert env.client.get(f"/api/patients/{patient_id}").status_code == 404
    assert env.client.get(f"/api/cases/{case_id}").status_code == 404
    put = env.client.put(f"/api/cases/{case_id}/symptoms", json={"symptoms": []})
    assert put.status_code == 404
    assert env.client.post(f"/api/cases/{case_id}/analyze").status_code == 404
    assert env.client.post("/api/cases", json={"patient_id": patient_id}).status_code == 404


def test_symptoms_autosave_replaces_the_list(env: Env):
    case_id = make_case(env)
    symptom = {"kind": "mental", "label": "Irritable", "worse": "consolation", "weight": 3}
    body = env.client.put(
        f"/api/cases/{case_id}/symptoms",
        json={"symptoms": [symptom, {"kind": "particular", "label": "Headache"}]},
    ).json()
    assert [s["label"] for s in body["symptoms"]] == ["Irritable", "Headache"]
    body = env.client.put(
        f"/api/cases/{case_id}/symptoms",
        json={"symptoms": [{"kind": "particular", "label": "Headache"}]},
    ).json()
    assert len(body["symptoms"]) == 1
    assert (
        env.client.put(
            f"/api/cases/{case_id}/symptoms", json={"symptoms": [{"kind": "bogus", "label": "x"}]}
        ).status_code
        == 422
    )


def test_analysis_needs_consent_and_content(env: Env):
    case_id = make_case(env)
    patient_id = env.client.get(f"/api/cases/{case_id}").json()["patient_id"]
    env.store.consents[0]["withdrawn_at"] = "2026-11-22"
    assert env.client.post(f"/api/cases/{case_id}/analyze").status_code == 409
    env.store.consents[0]["withdrawn_at"] = None
    empty = env.client.post("/api/cases", json={"patient_id": patient_id}).json()["id"]
    assert env.client.post(f"/api/cases/{empty}/analyze").status_code == 422


def test_semantic_rerun_saves_a_new_report_if_coverage_is_unavailable(
    env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    embedder = MockEmbeddingProvider()
    db = object()
    env.client.app.dependency_overrides.pop(cases_routes.get_analyzer)
    env.client.app.dependency_overrides[cases_routes.get_ai_store] = lambda: SimpleNamespace(
        get=lambda _owner: None
    )
    monkeypatch.setattr(cases_routes, "_own_llm", lambda *_: SimpleNamespace(model="test-model"))
    monkeypatch.setattr(cases_routes, "get_supabase_admin_client", lambda: db)
    monkeypatch.setattr(cases_routes, "get_embedding_provider", lambda: embedder)
    monkeypatch.setattr(
        ClaudeReasoner,
        "normalise",
        lambda *_: NormalisedCase(queries=[SearchQuery(text="headache")]),
    )
    monkeypatch.setattr(
        ClaudeReasoner,
        "rank",
        lambda *_: RankedOutput(
            remedies=[
                RankedRemedy(remedy="Example", confidence="low", rationale="fits", citations=["P1"])
            ]
        ),
    )
    row = {
        "book_id": "book-1",
        "book_title": "Test source",
        "book_category": "materia_medica",
        "content": "Test passage",
        "similarity": 0.95,
    }
    monkeypatch.setattr(
        knowledge_db,
        "keyword_search_chunks",
        lambda *_a, **_kw: [
            {**row, "chunk_id": "keyword-chunk"},
        ],
    )

    def vector_search(
        client: object, *, query_embedding: list[float], **_kwargs: Any
    ) -> list[dict]:
        assert client is db and query_embedding == embedder._vector("headache")
        return [{**row, "chunk_id": "semantic-chunk"}]

    monkeypatch.setattr(knowledge_db, "search_chunks", vector_search)
    monkeypatch.setattr(knowledge_db, "book_stats", lambda _: [])
    case_url = f"/api/cases/{make_case(env)}"
    first = env.client.post(f"{case_url}/analyze?search_mode=keyword")
    assert first.status_code == 201 and first.json()["retrieval_mode"] == "keyword"
    assert embedder.query_calls == []

    def unavailable(_client: object) -> list[dict]:
        raise knowledge_db.KnowledgeDBError("private database error")

    monkeypatch.setattr(knowledge_db, "book_stats", unavailable)
    rerun = env.client.post(f"{case_url}/analyze?search_mode=semantic")
    assert rerun.status_code == 201
    semantic = rerun.json()
    assert semantic["id"] != first.json()["id"] and semantic["retrieval_mode"] == "semantic"
    assert semantic["model"] == "test-model"
    assert semantic["remedies"][0]["citations"] == ["semantic-chunk"]
    assert semantic["incomplete_books"] == ["Test source"]
    assert embedder.query_calls == ["headache"]
    assert env.client.get(f"{case_url}/analysis").json() == semantic
    assert [item["id"] for item in env.client.get(f"{case_url}/analyses").json()] == [
        semantic["id"],
        first.json()["id"],
    ]


@pytest.mark.parametrize(
    ("status_code", "provider_message", "visible_message"),
    [
        (403, "Access denied", "Check your key, model and billing"),
        (400, "Your credit balance is too low", "Check billing and available credits"),
    ],
)
def test_analysis_provider_rejection_does_not_expose_the_error_body(
    env: Env,
    monkeypatch: pytest.MonkeyPatch,
    status_code: int,
    provider_message: str,
    visible_message: str,
) -> None:
    class Rejected(Exception):
        def __init__(self) -> None:
            super().__init__("private provider body")
            self.status_code = status_code
            self.message = provider_message

    def reject(*_args: object, **_kwargs: object) -> None:
        raise Rejected()

    monkeypatch.setattr(CaseAnalyzer, "analyze", reject)
    response = env.client.post(f"/api/cases/{make_case(env)}/analyze?search_mode=semantic")
    assert response.status_code == 502
    assert visible_message in response.json()["detail"]
    assert provider_message not in response.text
    assert "private provider body" not in response.text
    assert env.store.analyses == {}


def test_analysis_reports_provider_quota_failure(env: Env, monkeypatch: pytest.MonkeyPatch):
    def reject(*_args: object, **_kwargs: object) -> None:
        raise CompatibleProviderError(429)

    monkeypatch.setattr(CaseAnalyzer, "analyze", reject)
    response = env.client.post(f"/api/cases/{make_case(env)}/analyze?search_mode=keyword")
    assert response.status_code == 502
    assert "rate or quota limit" in response.json()["detail"]
    assert env.store.analyses == {}


def test_acknowledged_retry_reports_a_source_library_failure(env: Env, monkeypatch):
    def fail(_self, _case, acknowledge_red_flags=False):
        assert acknowledge_red_flags is True
        raise knowledge_db.KnowledgeDBError("private database detail")

    monkeypatch.setattr(CaseAnalyzer, "analyze", fail)
    case_id = make_case(env)
    response = env.client.post(f"/api/cases/{case_id}/analyze?acknowledge_red_flags=true")
    assert response.status_code == 502
    assert response.json()["detail"] == "The source library could not be searched. Try again later."
    assert env.store.analyses == {}


def test_failed_acknowledged_ranking_keeps_the_safety_result(env: Env, monkeypatch):
    def prepare(*_args):
        return NormalisedCase(
            queries=[SearchQuery(text="synthetic query")], urgent_concerns=["Synthetic concern"]
        )

    def fail_ranking(*_args):
        raise RuntimeError("private provider response")

    monkeypatch.setattr(FakeReasoner, "normalise", prepare)
    monkeypatch.setattr(FakeReasoner, "rank", fail_ranking)
    case_url = f"/api/cases/{make_case(env)}"
    stopped = env.client.post(f"{case_url}/analyze")
    assert stopped.status_code == 201 and stopped.json()["outcome"] == "red_flag"

    retry = env.client.post(f"{case_url}/analyze?acknowledge_red_flags=true")
    assert retry.status_code == 502
    assert "interpreting the retrieved sources" in retry.json()["detail"]
    assert "private provider response" not in retry.text
    assert env.client.get(f"{case_url}/analysis").json() == stopped.json()


def test_analysis_returns_cited_remedies_and_review_signs_off(env: Env):
    case_id = make_case(env)
    analysis = env.client.post(f"/api/cases/{case_id}/analyze")
    assert analysis.status_code == 201
    body = analysis.json()
    assert body["outcome"] == "ranked" and body["remedies"][0]["citations"] == ["chunk-1"]
    assert body["passages"][0]["chunk_id"] == "chunk-1"
    assert "not clinical evidence" in body["disclaimer"]
    assert env.client.get(f"/api/cases/{case_id}").json()["status"] == "analyzed"
    assert env.client.get(f"/api/cases/{case_id}/analysis").json()["id"] == body["id"]

    no_remedy = env.client.post(
        f"/api/cases/{case_id}/review", json={"analysis_id": body["id"], "decision": "accepted"}
    )
    assert no_remedy.status_code == 422
    review = env.client.post(
        f"/api/cases/{case_id}/review",
        json={
            "analysis_id": body["id"], "decision": "accepted", "chosen_remedy": "Belladonna",
            "practitioner_name": "Dr Test",
        },
    )
    assert review.status_code == 201
    assert env.client.get(f"/api/cases/{case_id}").json()["status"] == "signed_off"

    env.as_user("doctor-b")
    assert env.client.get(f"/api/cases/{case_id}/analysis").status_code == 404


def test_red_flag_case_returns_urgent_outcome_without_remedies(env: Env):
    case_id = make_case(env, complaint="crushing chest pain and cannot breathe")
    body = env.client.post(f"/api/cases/{case_id}/analyze").json()
    assert body["outcome"] == "red_flag" and body["remedies"] == []
    assert env.client.get(f"/api/cases/{case_id}").json()["status"] == "draft"
    acknowledged = env.client.post(
        f"/api/cases/{case_id}/analyze?acknowledge_red_flags=true"
    ).json()
    assert acknowledged["outcome"] == "ranked" and acknowledged["red_flags"]
    assert any("acknowledged" in row[1] for row in env.store.audit_rows)


def test_analysis_still_runs_while_the_provider_stop_is_set(
    env: Env, monkeypatch: pytest.MonkeyPatch
):
    """The stop only blocks paid embedding. Analysis then uses free keyword matching."""
    case_id = make_case(env)
    monkeypatch.setattr(cases_routes, "embedding_paused", lambda: True)
    assert env.client.post(f"/api/cases/{case_id}/analyze").status_code == 201


def test_long_answers_in_every_symptom_box_are_saved(env: Env):
    """Every box the form allows must be accepted by the API (a 422 stops autosave)."""
    case_id = make_case(env)
    long_text = "ا" * 500  # the form allows 500 characters in each detail box
    symptom = {
        "kind": "particular",
        "label": "Skin eruption",
        "location": long_text,
        "sensation": long_text,
        "better": long_text,
        "worse": long_text,
        "concomitants": long_text,
        "duration": long_text,
        "notes": "n" * 4000,
        "weight": 3,
    }
    response = env.client.put(f"/api/cases/{case_id}/symptoms", json={"symptoms": [symptom]})
    assert response.status_code == 200, response.text


def test_analysis_output_names_partly_indexed_books() -> None:
    row = {
        "id": str(uuid.uuid4()),
        "case_id": str(uuid.uuid4()),
        "outcome": "ranked",
        "created_at": _now(),
        "passages": [
            {
                "chunk_id": "a",
                "book_title": "Partial Book",
                "book_category": "materia_medica",
                "book_complete": False,
                "content": "x",
                "similarity": 0.5,
            },
            {
                "chunk_id": "b",
                "book_title": "Whole Book",
                "book_category": "organon",
                "book_complete": True,
                "content": "y",
                "similarity": 0.4,
            },
            {
                "chunk_id": "c",
                "book_title": "Partial Book",
                "book_category": "materia_medica",
                "book_complete": False,
                "content": "z",
                "similarity": 0.3,
            },
        ],
    }
    assert cases_routes._analysis_out(row).incomplete_books == ["Partial Book"]


def test_prescription_workflow_saves_and_finalises_with_pdf_download(env: Env) -> None:
    case_id = make_case(env, complaint="Severe itchy eczema worse at night in warm bed")
    analysis = env.client.post(f"/api/cases/{case_id}/analyze")
    assert analysis.status_code == 201
    analysis_id = analysis.json()["id"]

    # Finalise prescription with full clinical details
    review_payload = {
        "analysis_id": analysis_id,
        "decision": "accepted",
        "chosen_remedy": "Sulphur",
        "diagnosis": "Atopic Dermatitis with nocturnal pruritus",
        "potency": "30C",
        "practitioner_name": "Dr Test",
        "dose": "4 pills",
        "frequency": "Twice daily",
        "duration": "7 days",
        "instructions": "Take on empty tongue 15 min before meals. Avoid camphor and mint.",
        "notes": "Patient advised to return in 1 week.",
    }
    res = env.client.post(f"/api/cases/{case_id}/review", json=review_payload)
    assert res.status_code == 201
    review = res.json()
    assert review["decision"] == "accepted"
    assert review["chosen_remedy"] == "Sulphur"
    assert review["diagnosis"] == "Atopic Dermatitis with nocturnal pruritus"
    assert review["potency"] == "30C"
    assert review["dose"] == "4 pills"
    assert review["frequency"] == "Twice daily"
    assert review["duration"] == "7 days"
    assert "Take on empty tongue" in review["instructions"]

    # Check GET /cases/{case_id}/review
    get_res = env.client.get(f"/api/cases/{case_id}/review")
    assert get_res.status_code == 200
    assert get_res.json()["chosen_remedy"] == "Sulphur"

    # Check GET /cases/{case_id}/prescription/file
    pdf_res = env.client.get(f"/api/cases/{case_id}/prescription/file")
    assert pdf_res.status_code == 200
    assert pdf_res.headers["content-type"] == "application/pdf"
    assert pdf_res.content.startswith(b"%PDF")
    disposition = pdf_res.headers["content-disposition"]
    assert "prescription-" in disposition and disposition.endswith('.pdf"')


def test_red_flag_requires_urgency_disposition_to_finalise(env: Env) -> None:
    case_id = make_case(env, complaint="crushing chest pain and cannot breathe")
    # Acknowledge to run analysis
    analysis_res = env.client.post(f"/api/cases/{case_id}/analyze?acknowledge_red_flags=true")
    assert analysis_res.status_code == 201
    analysis_id = analysis_res.json()["id"]

    # Attempting to finalise without urgency_disposition should be rejected with 422
    attempt = env.client.post(
        f"/api/cases/{case_id}/review",
        json={
            "analysis_id": analysis_id, "decision": "accepted", "chosen_remedy": "Aconite",
            "practitioner_name": "Dr Test",
        },
    )
    assert attempt.status_code == 422
    assert "urgent findings" in attempt.json()["detail"].lower()

    # Finalising with urgency_disposition succeeds
    success = env.client.post(
        f"/api/cases/{case_id}/review",
        json={
            "analysis_id": analysis_id,
            "decision": "accepted",
            "chosen_remedy": "Aconite",
            "practitioner_name": "Dr Test",
            "urgency_disposition": (
                "Cardiology referral arranged immediately; emergency services notified."
            ),
        },
    )
    assert success.status_code == 201
    assert success.json()["urgency_disposition"].startswith("Cardiology referral")
