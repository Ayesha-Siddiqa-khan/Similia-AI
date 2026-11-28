"""Urdu report translation: only AI-written text goes out, shapes must match, owner-only."""

# ruff: noqa: F811
from app.ai.rag.report_translation import UrduRemedy, UrduReport, build_source, matches_shape
from app.api.routes import cases as cases_routes
from tests.test_cases_api import Env, env, make_case, make_patient  # noqa: F401


class FakeTranslator:
    def __init__(self, shape_ok: bool = True) -> None:
        self.sources: list[dict] = []
        self.shape_ok = shape_ok

    def to_urdu(self, source: dict) -> UrduReport:
        self.sources.append(source)
        remedies = [
            UrduRemedy(
                remedy=f"اردو ({r['remedy']})",
                rationale="وجہ",
                matching_symptoms=["علامت"] * len(r["matching_symptoms"]),
                contradicting_symptoms=["مخالف"] * len(r["contradicting_symptoms"]),
            )
            for r in source["remedies"]
        ]
        if not self.shape_ok:
            remedies = remedies[:-1] if remedies else [UrduRemedy(remedy="x", rationale="y")]
        return UrduReport(
            chief_complaint="شکایت",
            red_flags=["انتباہ"] * len(source["red_flags"]),
            cautions=["احتیاط"] * len(source["cautions"]),
            remedies=remedies,
            missing_information=["سوال"] * len(source["missing_information"]),
        )


def use(env: Env, translator: FakeTranslator) -> None:
    env.client.app.dependency_overrides[cases_routes.get_report_translator] = lambda: translator


def analysed_case(env: Env) -> str:
    case_id = make_case(env)
    assert env.client.post(f"/api/cases/{case_id}/analyze").status_code == 201
    return case_id


def test_the_source_has_no_patient_identity_and_no_book_text() -> None:
    case = {"chief_complaint": "itching worse at night", "patient_id": "p1"}
    analysis = {
        "red_flags": ["fever"],
        "remedies": [
            {
                "remedy": "Sulphur",
                "rationale": "fits",
                "matching_symptoms": ["itch"],
                "contradicting_symptoms": [],
                "citations": ["c1"],
            }
        ],
        "passages": [{"content": "BOOK TEXT"}],
        "missing_information": ["Is there fever?"],
    }
    source = build_source(case, analysis)
    text = str(source)
    assert "BOOK TEXT" not in text and "p1" not in text and "citations" not in text
    assert source["remedies"][0]["remedy"] == "Sulphur"


def test_an_item_for_item_translation_is_accepted_and_a_mismatch_is_not() -> None:
    source = {
        "chief_complaint": "x",
        "red_flags": ["a"],
        "cautions": [],
        "remedies": [
            {
                "remedy": "R",
                "rationale": "r",
                "matching_symptoms": ["m"],
                "contradicting_symptoms": [],
            }
        ],
        "missing_information": ["q1", "q2"],
    }
    good = UrduReport(
        red_flags=["ا"],
        remedies=[UrduRemedy(remedy="R", rationale="ر", matching_symptoms=["م"])],
        missing_information=["1", "2"],
    )
    assert matches_shape(source, good)
    assert not matches_shape(source, good.model_copy(update={"missing_information": ["1"]}))
    assert not matches_shape(source, good.model_copy(update={"remedies": []}))


def test_the_urdu_report_is_returned_and_audited(env: Env) -> None:
    case_id = analysed_case(env)
    translator = FakeTranslator()
    use(env, translator)
    response = env.client.post(f"/api/cases/{case_id}/report/urdu")
    assert response.status_code == 200
    body = response.json()
    assert (
        body["remedies"][0]["remedy"].startswith("اردو") and "Machine translation" in body["notice"]
    )
    sent = str(translator.sources[0])
    assert "Test Patient" not in sent and "P-001" not in sent  # the patient's identity stays here
    assert ("doctor-a", "case.report.urdu", "case", case_id) in env.store.audit_rows


def test_a_translation_that_does_not_line_up_is_refused(env: Env) -> None:
    case_id = analysed_case(env)
    use(env, FakeTranslator(shape_ok=False))
    assert env.client.post(f"/api/cases/{case_id}/report/urdu").status_code == 502


def test_a_case_without_an_analysis_has_no_report(env: Env) -> None:
    case_id = make_case(env)
    use(env, FakeTranslator())
    assert env.client.post(f"/api/cases/{case_id}/report/urdu").status_code == 404


def test_another_doctor_cannot_translate_someone_elses_analysis(env: Env) -> None:
    case_id = analysed_case(env)
    use(env, FakeTranslator())
    env.as_user("doctor-b")
    assert env.client.post(f"/api/cases/{case_id}/report/urdu").status_code == 404


def test_consent_withdrawal_blocks_the_translation(env: Env) -> None:
    case_id = analysed_case(env)
    use(env, FakeTranslator())
    patient_id = env.client.get(f"/api/cases/{case_id}").json()["patient_id"]
    env.client.post(f"/api/patients/{patient_id}/consent/withdraw")
    assert env.client.post(f"/api/cases/{case_id}/report/urdu").status_code == 409


def test_the_endpoint_needs_sign_in() -> None:
    import uuid

    from fastapi.testclient import TestClient

    from app.main import create_app

    url = f"/api/cases/{uuid.uuid4()}/report/urdu"
    assert TestClient(create_app()).post(url).status_code == 401
