"""Sign-off and prescription safety: current analysis only, live consent, nothing invented."""

# ruff: noqa: F811
import unicodedata

import pymupdf
import pytest

from app.services import report_files
from tests.test_cases_api import Env, env, make_case  # noqa: F401


def analyse(env: Env, case_id: str) -> str:
    response = env.client.post(f"/api/cases/{case_id}/analyze")
    assert response.status_code == 201, response.text
    return response.json()["id"]


def sign(env: Env, case_id: str, analysis_id: str, **extra):
    body = {
        "analysis_id": analysis_id, "decision": "accepted", "chosen_remedy": "Sulphur",
        "practitioner_name": "Dr Test", **extra,
    }
    return env.client.post(f"/api/cases/{case_id}/review", json=body)


def patient_of(env: Env, case_id: str) -> str:
    return env.client.get(f"/api/cases/{case_id}").json()["patient_id"]


def pdf_text(data: bytes) -> str:
    text = "\n".join(page.get_text() for page in pymupdf.open(stream=data, filetype="pdf"))
    return unicodedata.normalize("NFKC", text)


def test_an_older_analysis_cannot_be_signed_off(env: Env) -> None:
    case_id = make_case(env)
    older = analyse(env, case_id)
    latest = analyse(env, case_id)
    refused = sign(env, case_id, older)
    assert refused.status_code == 409 and "newer analysis" in refused.json()["detail"]
    assert env.store.reviews == []
    assert sign(env, case_id, latest).status_code == 201


def test_sign_off_is_refused_after_consent_is_withdrawn(env: Env) -> None:
    case_id = make_case(env)
    analysis = analyse(env, case_id)
    assert env.client.post(f"/api/patients/{patient_of(env, case_id)}/consent/withdraw").is_success
    refused = sign(env, case_id, analysis)
    assert refused.status_code == 409
    assert env.store.reviews == []


def test_sign_off_is_refused_for_an_archived_patient(env: Env) -> None:
    case_id = make_case(env)
    analysis = analyse(env, case_id)
    archived = env.client.patch(
        f"/api/patients/{patient_of(env, case_id)}", json={"archived": True}
    )
    assert archived.status_code == 200
    assert sign(env, case_id, analysis).status_code == 409
    assert env.store.reviews == []


def test_the_prescriber_name_is_stored_as_entered(env: Env) -> None:
    case_id = make_case(env)
    done = sign(env, case_id, analyse(env, case_id), practitioner_name="Dr A. Example")
    assert done.status_code == 201 and done.json()["practitioner_name"] == "Dr A. Example"
    saved = env.client.get(f"/api/cases/{case_id}/review").json()
    assert saved["practitioner_name"] == "Dr A. Example"
    assert saved["potency"] is None and saved["dose"] is None


def test_the_downloaded_prescription_shows_the_entered_name_never_the_user_id(env: Env) -> None:
    case_id = make_case(env)
    sign(env, case_id, analyse(env, case_id), practitioner_name="Dr A. Example")
    response = env.client.get(f"/api/cases/{case_id}/prescription/file")
    assert response.status_code == 200
    text = pdf_text(response.content)
    assert "Dr A. Example" in text and "doctor-a" not in text


def _render(review: dict) -> str:
    case = {"id": "abcdef12-0000", "chief_complaint": "itch"}
    patient = {"full_name": "Sample Person", "identifier": "S-1", "age_years": 8, "sex": "female"}
    return pdf_text(report_files.render_prescription_pdf(case, patient, review))


def test_empty_prescription_fields_are_never_filled_with_defaults() -> None:
    text = _render({"decision": "accepted", "chosen_remedy": "Sulphur", "signed_at": None})
    for invented in ("30C", "4 pills", "Twice daily", "7 days", "clean tongue", "camphor",
                     "Provisional Homeopathic Assessment", "Treating Doctor"):
        assert invented not in text, invented
    assert text.count("Not recorded") >= 6


def test_recorded_prescription_fields_are_printed_as_written() -> None:
    text = _render(
        {
            "decision": "accepted", "chosen_remedy": "Sulphur", "potency": "200C",
            "dose": "2 pills", "frequency": "Once", "duration": "1 day",
            "instructions": "Review in one week.", "diagnosis": "Eczema",
            "practitioner_name": "Dr B. Example",
        }
    )
    for written in ("200C", "2 pills", "Once", "1 day", "Review in one week.", "Eczema",
                    "Dr B. Example"):
        assert written in text, written
    assert "Not recorded" not in text


@pytest.mark.parametrize("name", [None, "", "   "])
def test_an_accepted_prescription_needs_the_prescribers_name(env: Env, name) -> None:
    case_id = make_case(env)
    refused = sign(env, case_id, analyse(env, case_id), practitioner_name=name)
    assert refused.status_code == 422 and "prescriber" in refused.json()["detail"]
    assert env.store.reviews == []


def test_rejecting_an_analysis_needs_no_prescriber_name(env: Env) -> None:
    case_id = make_case(env)
    done = env.client.post(
        f"/api/cases/{case_id}/review",
        json={"analysis_id": analyse(env, case_id), "decision": "rejected"},
    )
    assert done.status_code == 201
