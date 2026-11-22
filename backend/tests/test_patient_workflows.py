"""Phase 4: consent withdrawal, archive, history, export, erasure, children's safeguards."""

# ruff: noqa: F811
from datetime import date, timedelta

from tests.test_cases_api import Env, env, make_case, make_patient  # noqa: F401
from tests.test_cases_api import make_patient as _make_patient  # noqa: F401


def patient(env: Env, **extra) -> dict:
    body = {
        "identifier": "P-100",
        "full_name": "Test Patient",
        "age_years": 30,
        "consent_given": True,
        **extra,
    }
    response = env.client.post("/api/patients", json=body)
    assert response.status_code == 201, response.text
    return response.json()


def case_for(env: Env, patient_id: str, complaint="headache worse in sun") -> str:
    response = env.client.post(
        "/api/cases", json={"patient_id": patient_id, "chief_complaint": complaint}
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def sign_off(env: Env, case_id: str) -> None:
    analysis = env.client.post(f"/api/cases/{case_id}/analyze").json()
    review = env.client.post(
        f"/api/cases/{case_id}/review",
        json={"analysis_id": analysis["id"], "decision": "accepted", "chosen_remedy": "Belladonna"},
    )
    assert review.status_code == 201


# -- children ---------------------------------------------------------------------


def test_a_minor_needs_a_guardian_name_and_relationship(env: Env) -> None:
    body = {"identifier": "K-1", "full_name": "Child", "age_years": 9, "consent_given": True}
    assert env.client.post("/api/patients", json=body).status_code == 422
    only_name = {**body, "guardian_name": "A Parent"}
    assert env.client.post("/api/patients", json=only_name).status_code == 422
    full = {**body, "guardian_name": "A Parent", "guardian_relationship": "mother"}
    created = env.client.post("/api/patients", json=full)
    assert created.status_code == 201
    assert created.json()["is_minor"] is True and created.json()["is_infant"] is False


def test_the_age_comes_from_the_date_of_birth_when_known(env: Env) -> None:
    born = (date.today() - timedelta(days=200)).isoformat()
    body = {
        "identifier": "B-1",
        "full_name": "Baby",
        "date_of_birth": born,
        "guardian_name": "A Parent",
        "guardian_relationship": "father",
        "consent_given": True,
    }
    made = env.client.post("/api/patients", json=body).json()
    assert made["is_minor"] is True and made["is_infant"] is True


def test_an_adult_needs_no_guardian_and_clearing_it_for_a_minor_is_refused(env: Env) -> None:
    adult = patient(env)
    assert adult["is_minor"] is False
    child = patient(
        env,
        identifier="K-2",
        age_years=12,
        guardian_name="A Parent",
        guardian_relationship="mother",
    )
    cleared = env.client.patch(f"/api/patients/{child['id']}", json={"guardian_name": ""})
    assert cleared.status_code == 422
    aged = env.client.patch(f"/api/patients/{adult['id']}", json={"age_years": 10})
    assert aged.status_code == 422  # became a minor without a guardian


def test_analysis_for_a_child_carries_a_caution_and_keeps_the_remedy_for_the_doctor(
    env: Env,
) -> None:
    child = patient(
        env, identifier="K-3", age_years=8, guardian_name="G", guardian_relationship="aunt"
    )
    case_id = case_for(env, child["id"])
    body = env.client.post(f"/api/cases/{case_id}/analyze").json()
    assert body["outcome"] == "ranked" and "Paediatric" in body["cautions"][0]
    again = env.client.get(f"/api/cases/{case_id}/analysis").json()
    assert again["cautions"] == body["cautions"]


def test_an_infant_is_stopped_until_the_doctor_confirms_they_assessed_urgency(env: Env) -> None:
    born = (date.today() - timedelta(days=90)).isoformat()
    baby = patient(
        env,
        identifier="B-2",
        age_years=None,
        date_of_birth=born,
        guardian_name="G",
        guardian_relationship="mother",
    )
    case_id = case_for(env, baby["id"])
    stopped = env.client.post(f"/api/cases/{case_id}/analyze").json()
    assert stopped["outcome"] == "red_flag" and stopped["remedies"] == []
    assert "Infant under 1 year" in stopped["red_flags"][0]
    ok = env.client.post(f"/api/cases/{case_id}/analyze?acknowledge_red_flags=true").json()
    assert ok["outcome"] == "ranked" and "Infant under 1 year" in ok["red_flags"][0]


# -- consent ----------------------------------------------------------------------


def test_withdrawing_consent_archives_the_patient_and_blocks_ai_and_edits(env: Env) -> None:
    p = patient(env)
    case_id = case_for(env, p["id"])
    withdrawn = env.client.post(f"/api/patients/{p['id']}/consent/withdraw")
    assert withdrawn.status_code == 200
    out = withdrawn.json()
    assert out["consent_active"] is False and out["archived_at"]
    assert env.client.post(f"/api/cases/{case_id}/analyze").status_code == 409
    edit = env.client.patch(f"/api/cases/{case_id}", json={"chief_complaint": "changed"})
    assert edit.status_code == 409
    new_case = env.client.post("/api/cases", json={"patient_id": p["id"]})
    assert new_case.status_code == 409
    assert env.client.post(f"/api/patients/{p['id']}/consent/withdraw").status_code == 409
    history = env.client.get(f"/api/patients/{p['id']}/consents").json()
    assert len(history) == 1 and history[0]["withdrawn_at"]


def test_consent_can_be_given_again_and_the_record_reopens(env: Env) -> None:
    p = patient(env)
    env.client.post(f"/api/patients/{p['id']}/consent/withdraw")
    assert env.client.post(f"/api/patients/{p['id']}/consent").status_code == 201
    out = env.client.get(f"/api/patients/{p['id']}").json()
    assert out["consent_active"] is True and out["archived_at"] is None
    assert env.client.post(f"/api/patients/{p['id']}/consent").status_code == 409
    assert len(env.client.get(f"/api/patients/{p['id']}/consents").json()) == 2


def test_an_archived_patient_is_read_only_until_restored(env: Env) -> None:
    p = patient(env)
    assert env.client.patch(f"/api/patients/{p['id']}", json={"archived": True}).status_code == 200
    assert env.client.patch(f"/api/patients/{p['id']}", json={"notes": "x"}).status_code == 409
    restored = env.client.patch(f"/api/patients/{p['id']}", json={"archived": False})
    assert restored.status_code == 200 and restored.json()["archived_at"] is None


# -- history, export, erasure -------------------------------------------------------


def test_history_lists_cases_with_outcome_and_signed_decision(env: Env) -> None:
    p = patient(env)
    first = case_for(env, p["id"], "headache")
    sign_off(env, first)
    case_for(env, p["id"], "cough")
    rows = env.client.get(f"/api/patients/{p['id']}/history").json()
    by_complaint = {r["chief_complaint"]: r for r in rows}
    done = by_complaint["headache"]
    assert done["status"] == "signed_off" and done["chosen_remedy"] == "Belladonna"
    assert done["review_decision"] == "accepted" and done["latest_outcome"] == "ranked"
    assert (
        by_complaint["cough"]["analysis_count"] == 0 and by_complaint["cough"]["signed_at"] is None
    )
    assert "remedies" not in done and "symptoms" not in done  # no clinical detail in the list
    env.as_user("doctor-b")
    assert env.client.get(f"/api/patients/{p['id']}/history").status_code == 404


def test_earlier_analyses_stay_available_newest_first(env: Env) -> None:
    p = patient(env)
    case_id = case_for(env, p["id"])
    first = env.client.post(f"/api/cases/{case_id}/analyze").json()
    env.client.patch(f"/api/cases/{case_id}", json={"chief_complaint": "headache and nausea"})
    second = env.client.post(f"/api/cases/{case_id}/analyze").json()
    ids = [a["id"] for a in env.client.get(f"/api/cases/{case_id}/analyses").json()]
    assert ids == [second["id"], first["id"]]


def test_export_contains_everything_and_is_audited_and_owner_only(env: Env) -> None:
    p = patient(env)
    case_id = case_for(env, p["id"])
    sign_off(env, case_id)
    data = env.client.get(f"/api/patients/{p['id']}/export").json()
    assert data["format"] == "similia-patient-export-v1" and data["patient"]["id"] == p["id"]
    assert len(data["consents"]) == 1 and len(data["cases"]) == 1
    case = data["cases"][0]
    assert len(case["analyses"]) == 1 and len(case["reviews"]) == 1
    assert ("doctor-a", "patient.export", "patient", p["id"]) in env.store.audit_rows
    env.as_user("doctor-b")
    assert env.client.get(f"/api/patients/{p['id']}/export").status_code == 404


def test_erasure_needs_archive_and_the_typed_identifier_and_removes_everything(env: Env) -> None:
    p = patient(env, identifier="P-ERASE")
    case_id = case_for(env, p["id"])
    sign_off(env, case_id)
    url = f"/api/patients/{p['id']}"
    assert env.client.delete(url, params={"confirm_identifier": "P-ERASE"}).status_code == 409
    env.client.patch(url, json={"archived": True})
    assert env.client.delete(url, params={"confirm_identifier": "wrong"}).status_code == 422
    assert env.client.delete(url).status_code == 422  # identifier is required
    env.as_user("doctor-b")
    assert env.client.delete(url, params={"confirm_identifier": "P-ERASE"}).status_code == 404
    env.as_user("doctor-a")
    assert env.client.delete(url, params={"confirm_identifier": "P-ERASE"}).status_code == 204
    assert env.client.get(url).status_code == 404
    assert env.client.get(f"/api/cases/{case_id}").status_code == 404
    assert env.store.analyses == {} and env.store.reviews == [] and env.store.consents == []
    erased = [r for r in env.store.audit_rows if r[1] == "patient.erase"]
    assert erased == [("doctor-a", "patient.erase", "patient", None)]  # no patient id kept


def test_new_endpoints_require_sign_in() -> None:
    import uuid

    from fastapi.testclient import TestClient

    from app.main import create_app

    client = TestClient(create_app())
    pid = str(uuid.uuid4())
    for method, path in (
        ("get", f"/api/patients/{pid}/export"),
        ("get", f"/api/patients/{pid}/history"),
        ("get", f"/api/patients/{pid}/consents"),
        ("post", f"/api/patients/{pid}/consent/withdraw"),
        ("post", f"/api/patients/{pid}/consent"),
        ("delete", f"/api/patients/{pid}?confirm_identifier=x"),
        ("get", f"/api/cases/{pid}/analyses"),
    ):
        assert getattr(client, method)(path).status_code == 401, path


def test_opening_records_is_audited_and_a_failing_log_never_blocks_reading(env: Env) -> None:
    p = patient(env)
    case_id = case_for(env, p["id"])
    env.client.get(f"/api/patients/{p['id']}")
    env.client.get(f"/api/patients/{p['id']}/history")
    env.client.get(f"/api/cases/{case_id}")
    actions = {row[1] for row in env.store.audit_rows}
    assert {"patient.view", "patient.history", "case.view"} <= actions

    from app.services.case_db import CaseStoreError

    def broken(*_args, **_kwargs):
        raise CaseStoreError("audit failed")

    env.store.audit = broken
    assert env.client.get(f"/api/patients/{p['id']}").status_code == 200
