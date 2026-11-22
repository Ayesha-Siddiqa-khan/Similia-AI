"""AI follow-up questions: red-flag first, cleaning, owner isolation, consent."""

import pytest
from fastapi.testclient import TestClient

from app.ai.rag.case_questions import (
    ClaudeQuestionWriter,
    FollowUpQuestion,
    FollowUps,
    suggest_questions,
)
from app.api.auth import require_practitioner
from app.api.routes import cases as cases_routes
from app.main import create_app
from tests.test_cases_api import Env, InMemoryCaseStore, make_case


class FakeWriter:
    def __init__(self, follow_ups: FollowUps | None = None) -> None:
        self.calls = 0
        self.last_text = ""
        self.last_include_urdu: bool | None = None
        self.follow_ups = follow_ups or FollowUps(
            particular=[FollowUpQuestion(topic="Discharge", question="What colour is it?")]
        )

    def write(self, case_text, include_urdu):
        self.calls += 1
        self.last_text = case_text
        self.last_include_urdu = include_urdu
        return self.follow_ups


def case(complaint="itchy skin, thick sticky discharge"):
    return {"chief_complaint": complaint, "language": "en", "symptoms": []}


def test_red_flag_returns_notice_and_never_calls_the_model():
    writer = FakeWriter()
    result = suggest_questions(case("crushing chest pain"), writer)
    assert result.red_flags and writer.calls == 0
    assert all(items == [] for items in result.questions.values())


def test_questions_are_cleaned_and_capped():
    many = [FollowUpQuestion(topic=f"T{i}", question=f"Q{i}?") for i in range(10)]
    messy = [FollowUpQuestion(topic="  ", question="no topic"),
             FollowUpQuestion(topic="x" * 200, question="y" * 900)]
    result = suggest_questions(case(), FakeWriter(FollowUps(mental=many, history=messy)))
    assert len(result.questions["mental"]) == 6
    assert len(result.questions["history"]) == 1  # blank topic dropped
    assert len(result.questions["history"][0]["topic"]) == 80
    assert len(result.questions["history"][0]["question"]) == 300


def test_existing_answers_are_sent_so_questions_are_not_repeated():
    writer = FakeWriter()
    data = case()
    data["symptoms"] = [{"kind": "particular", "label": "Itching", "worse": "night", "weight": 2}]
    suggest_questions(data, writer)
    assert "Itching" in writer.last_text and "worse with: night" in writer.last_text


@pytest.fixture
def env(monkeypatch: pytest.MonkeyPatch) -> Env:
    app = create_app()
    store = InMemoryCaseStore()
    who = {"id": "doctor-a"}
    writer = FakeWriter()

    def no_network(*_a: object, **_k: object) -> None:
        raise AssertionError("tests must never call the real LLM")

    monkeypatch.setattr(ClaudeQuestionWriter, "write", no_network)
    app.dependency_overrides[require_practitioner] = lambda: who["id"]
    app.dependency_overrides[cases_routes.get_case_store] = lambda: store
    app.dependency_overrides[cases_routes.get_question_writer] = lambda: writer
    return Env(TestClient(app), store, who)


def test_endpoint_returns_questions_and_audits(env: Env):
    case_id = make_case(env)
    response = env.client.post(f"/api/cases/{case_id}/questions")
    assert response.status_code == 200
    body = response.json()
    assert body["particular"][0]["topic"] == "Discharge" and body["red_flags"] == []
    assert any(row[1] == "case.questions" for row in env.store.audit_rows)


def test_endpoint_requires_sign_in_owner_consent_and_a_complaint(env: Env):
    assert TestClient(create_app()).post(f"/api/cases/{'0' * 8}-0000-0000-0000-{'0' * 12}/questions"
                                         ).status_code == 401
    case_id = make_case(env)
    env.as_user("doctor-b")
    assert env.client.post(f"/api/cases/{case_id}/questions").status_code == 404
    env.as_user("doctor-a")
    env.store.consents[0]["withdrawn_at"] = "2026-11-22"
    assert env.client.post(f"/api/cases/{case_id}/questions").status_code == 409
    env.store.consents[0]["withdrawn_at"] = None
    env.client.patch(f"/api/cases/{case_id}", json={"chief_complaint": "  "})
    assert env.client.post(f"/api/cases/{case_id}/questions").status_code == 422


URDU = FollowUps(
    particular=[
        FollowUpQuestion(
            topic="Discharge",
            question="What colour is it?",
            topic_ur="رطوبت",
            question_ur="اس کا رنگ کیسا ہے؟",
        )
    ]
)


def test_english_is_the_default_and_urdu_is_dropped_unless_requested():
    writer = FakeWriter(URDU)
    plain = suggest_questions(case(), writer)
    assert writer.last_include_urdu is False
    item = plain.questions["particular"][0]
    assert item["question"] == "What colour is it?"
    assert item["question_ur"] == "" and item["topic_ur"] == ""  # not asked for, never shown


def test_urdu_is_included_beside_english_when_requested():
    writer = FakeWriter(URDU)
    result = suggest_questions(case(), writer, include_urdu=True)
    assert writer.last_include_urdu is True
    item = result.questions["particular"][0]
    assert item["question"] == "What colour is it?"  # English stays first
    assert item["question_ur"] == "اس کا رنگ کیسا ہے؟" and item["topic_ur"] == "رطوبت"


def test_endpoint_passes_the_urdu_option_and_returns_both_languages(env: Env):
    case_id = make_case(env)
    english_only = env.client.post(f"/api/cases/{case_id}/questions").json()
    assert english_only["particular"][0]["question_ur"] == ""
    writer = env.client.app.dependency_overrides[cases_routes.get_question_writer]()
    writer.follow_ups = URDU
    both = env.client.post(f"/api/cases/{case_id}/questions?include_urdu=true").json()
    assert both["particular"][0]["question"] == "What colour is it?"
    assert both["particular"][0]["question_ur"] == "اس کا رنگ کیسا ہے؟"
    assert writer.last_include_urdu is True


def test_example_answers_pass_through_and_urdu_examples_follow_the_option():
    items = FollowUps(
        particular=[
            FollowUpQuestion(
                topic="Discharge",
                question="What colour is it?",
                example_answer="  It is thick and yellow, like honey.  ",
                topic_ur="رطوبت",
                question_ur="اس کا رنگ کیسا ہے؟",
                example_answer_ur="یہ گاڑھا اور پیلا ہے۔",
            )
        ]
    )
    plain = suggest_questions(case(), FakeWriter(items)).questions["particular"][0]
    assert plain["example_answer"] == "It is thick and yellow, like honey."
    assert plain["example_answer_ur"] == ""  # Urdu not requested
    both = suggest_questions(case(), FakeWriter(items), include_urdu=True)
    assert both.questions["particular"][0]["example_answer_ur"] == "یہ گاڑھا اور پیلا ہے۔"
