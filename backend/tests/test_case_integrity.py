"""Record integrity: signed-off cases are locked, edits make an analysis stale, validation errors
never echo patient text, API docs are hidden in production."""

# ruff: noqa: F811  (the `env` pytest fixture is imported from test_cases_api and used by name)

from types import SimpleNamespace

from fastapi.testclient import TestClient

import app.main as app_main
from app.ai.rag.case_analysis import build_case_text
from tests.test_cases_api import Env, env, make_case  # noqa: F401  (pytest fixtures)

COMPLAINT = "headache worse in sun"  # what make_case() records
SYMPTOM = {"kind": "mental", "label": "Irritable", "notes": "Q: Temper?\nA: Quick to anger"}


def put_symptoms(env: Env, case_id: str, symptoms: list[dict]):
    return env.client.put(f"/api/cases/{case_id}/symptoms", json={"symptoms": symptoms})


def analyse(env: Env, case_id: str) -> dict:
    return env.client.post(f"/api/cases/{case_id}/analyze").json()


def sign_off(env: Env, case_id: str, analysis_id: str, remedy: str = "Belladonna"):
    return env.client.post(
        f"/api/cases/{case_id}/review",
        json={"analysis_id": analysis_id, "decision": "accepted", "chosen_remedy": remedy},
    )


def status_of(env: Env, case_id: str) -> str:
    return env.client.get(f"/api/cases/{case_id}").json()["status"]


def test_a_signed_off_case_is_locked_against_every_change(env: Env):
    case_id = make_case(env)
    assert sign_off(env, case_id, analyse(env, case_id)["id"]).status_code == 201
    assert status_of(env, case_id) == "signed_off"
    attempts = [
        put_symptoms(env, case_id, [SYMPTOM]),
        env.client.patch(f"/api/cases/{case_id}", json={"chief_complaint": "changed"}),
        env.client.post(f"/api/cases/{case_id}/analyze"),
    ]
    for response in attempts:
        assert response.status_code == 409
        assert "signed off" in response.json()["detail"]
    assert env.client.get(f"/api/cases/{case_id}").json()["chief_complaint"] == COMPLAINT


def test_signing_off_twice_is_refused(env: Env):
    case_id = make_case(env)
    analysis_id = analyse(env, case_id)["id"]
    assert sign_off(env, case_id, analysis_id).status_code == 201
    again = sign_off(env, case_id, analysis_id, remedy="Other")
    assert again.status_code == 409
    assert "already signed off" in again.json()["detail"]


def test_reopening_unlocks_the_case_as_a_draft_and_is_audited(env: Env):
    case_id = make_case(env)
    sign_off(env, case_id, analyse(env, case_id)["id"])
    reopened = env.client.post(f"/api/cases/{case_id}/reopen")
    assert reopened.status_code == 200
    assert reopened.json()["status"] == "draft"
    assert any(row[1] == "case.reopen" for row in env.store.audit_rows)
    assert put_symptoms(env, case_id, [SYMPTOM]).status_code == 200


def test_only_a_signed_off_case_can_be_reopened_and_only_by_its_owner(env: Env):
    case_id = make_case(env)
    assert env.client.post(f"/api/cases/{case_id}/reopen").status_code == 409  # still a draft
    sign_off(env, case_id, analyse(env, case_id)["id"])
    env.as_user("doctor-b")
    assert env.client.post(f"/api/cases/{case_id}/reopen").status_code == 404


def test_editing_an_analysed_case_makes_the_analysis_stale_until_it_is_run_again(env: Env):
    case_id = make_case(env)
    first = analyse(env, case_id)
    assert status_of(env, case_id) == "analyzed"

    put_symptoms(env, case_id, [SYMPTOM])
    assert status_of(env, case_id) == "draft"
    stale = sign_off(env, case_id, first["id"])
    assert stale.status_code == 409
    assert "Run the analysis again" in stale.json()["detail"]

    assert sign_off(env, case_id, analyse(env, case_id)["id"]).status_code == 201


def test_saving_identical_content_does_not_invalidate_the_analysis(env: Env):
    case_id = make_case(env)
    put_symptoms(env, case_id, [SYMPTOM])
    analyse(env, case_id)
    same = put_symptoms(env, case_id, [SYMPTOM])
    same_complaint = env.client.patch(f"/api/cases/{case_id}", json={"chief_complaint": COMPLAINT})
    assert same.status_code == 200 and same_complaint.status_code == 200
    assert status_of(env, case_id) == "analyzed"


def test_validation_errors_name_the_field_but_never_echo_the_text(env: Env):
    case_id = make_case(env)
    private = "patient-private-" + "x" * 400
    response = put_symptoms(env, case_id, [{"kind": "mental", "label": private}])
    assert response.status_code == 422
    assert "patient-private" not in response.text
    assert "symptoms.0.label" in response.json()["detail"]


def test_api_docs_are_hidden_in_production_and_shown_in_development(monkeypatch):
    def settings(environment):
        return SimpleNamespace(app_name="Similia", environment=environment, cors_origins_list=[])

    monkeypatch.setattr(app_main, "get_settings", lambda: settings("production"))
    prod = TestClient(app_main.create_app())
    assert prod.get("/openapi.json").status_code == 404
    assert prod.get("/docs").status_code == 404
    monkeypatch.setattr(app_main, "get_settings", lambda: settings("development"))
    assert TestClient(app_main.create_app()).get("/openapi.json").status_code == 200


def test_unanswered_question_cards_are_left_out_of_the_analysis_text():
    case = {"chief_complaint": "itch", "symptoms": [
        {"kind": "mental", "label": "Asked only", "notes": "Q: Temper?\nA: ", "weight": 2},
        {"kind": "mental", "label": "Answered", "notes": "Q: Fear?\nA: Of exams", "weight": 2},
        {"kind": "particular", "label": "Detailed", "notes": "Q: Where?\nA: ", "location": "knees"},
        {"kind": "mental", "label": "Plain note", "notes": "Prefers company", "weight": 2},
    ]}
    text = build_case_text(case)
    assert "Asked only" not in text and "Temper?" not in text
    assert "Answered" in text and "Of exams" in text
    assert "Detailed" in text and "Plain note" in text
