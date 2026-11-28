"""Hourly per-doctor AI limits: counted from the audit log, enforced before the AI call."""

# ruff: noqa: F811  (pytest fixtures are imported from test_ai_settings and used by name)

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app.ai.rag.case_analysis import ClaudeReasoner, NormalisedCase
from app.ai.rag.case_questions import ClaudeQuestionWriter, FollowUps
from app.api.routes import cases as cases_routes
from app.services import ai_limits
from tests.test_ai_settings import Env, env, save_key, secret  # noqa: F401
from tests.test_cases_api import InMemoryCaseStore

NOW = datetime(2026, 11, 22, 12, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def small_limits(monkeypatch):
    monkeypatch.setattr(
        ai_limits,
        "get_settings",
        lambda: SimpleNamespace(ai_questions_per_hour=3, ai_analyses_per_hour=2),
    )


def log(store: InMemoryCaseStore, owner: str, action: str, minutes_ago: int) -> None:
    stamp = (NOW - timedelta(minutes=minutes_ago)).isoformat()
    store.audit_log.append({"owner": owner, "action": action, "created_at": stamp})


def test_under_the_limit_is_allowed_and_counted():
    store = InMemoryCaseStore()
    log(store, "a", "case.questions", 10)
    log(store, "a", "case.questions", 5)
    ai_limits.enforce(store, "a", "questions", now=NOW)
    assert ai_limits.usage(store, "a", now=NOW)["questions"] == {"used": 2, "limit": 3}


def test_at_the_limit_is_refused_with_the_wait_time():
    store = InMemoryCaseStore()
    for minutes in (50, 30, 10):
        log(store, "a", "case.questions", minutes)
    with pytest.raises(ai_limits.RateLimitedError) as caught:
        ai_limits.enforce(store, "a", "questions", now=NOW)
    # The oldest request (50 min ago) leaves the one-hour window in 10 minutes.
    assert caught.value.retry_after_seconds == 600
    assert "3 question requests per hour" in caught.value.message
    assert "10 minutes" in caught.value.message


def test_requests_older_than_an_hour_and_other_doctors_do_not_count():
    store = InMemoryCaseStore()
    for minutes in (90, 75, 61):
        log(store, "a", "case.questions", minutes)
    for _ in range(5):
        log(store, "b", "case.questions", 1)
    ai_limits.enforce(store, "a", "questions", now=NOW)
    assert ai_limits.usage(store, "a", now=NOW)["questions"]["used"] == 0


def test_analyses_count_both_kinds_of_run_separately_from_questions():
    store = InMemoryCaseStore()
    log(store, "a", "case.analyze", 5)
    log(store, "a", "case.analyze.acknowledged_red_flags", 4)
    for _ in range(3):
        log(store, "a", "case.questions", 1)
    with pytest.raises(ai_limits.RateLimitedError):
        ai_limits.enforce(store, "a", "analyses", now=NOW)
    assert ai_limits.usage(store, "a", now=NOW)["analyses"]["used"] == 2


def make_case_for(env: Env) -> str:
    patient = env.client.post(
        "/api/patients", json={"identifier": "P-1", "full_name": "T", "consent_given": True}
    ).json()
    return env.client.post(
        "/api/cases", json={"patient_id": patient["id"], "chief_complaint": "itchy skin"}
    ).json()["id"]


def test_endpoint_returns_429_with_retry_after_and_stops_calling_the_ai(env: Env, monkeypatch):
    calls: list[int] = []
    monkeypatch.setattr(ClaudeQuestionWriter, "write", lambda *a: calls.append(1) or FollowUps())
    save_key(env)
    case_id = make_case_for(env)
    for _ in range(3):
        assert env.client.post(f"/api/cases/{case_id}/questions").status_code == 200
    blocked = env.client.post(f"/api/cases/{case_id}/questions")
    assert blocked.status_code == 429 and "Limit reached" in blocked.json()["detail"]
    assert int(blocked.headers["Retry-After"]) > 0
    assert len(calls) == 3


def test_failed_ai_calls_still_count(env: Env, monkeypatch):
    def boom(*_a):
        raise RuntimeError("provider down")

    monkeypatch.setattr(ClaudeQuestionWriter, "write", boom)
    save_key(env)
    case_id = make_case_for(env)
    for _ in range(3):
        assert env.client.post(f"/api/cases/{case_id}/questions").status_code == 502
    assert env.client.post(f"/api/cases/{case_id}/questions").status_code == 429


def test_each_doctor_has_their_own_allowance(env: Env, monkeypatch):
    monkeypatch.setattr(ClaudeQuestionWriter, "write", lambda *a: FollowUps())
    save_key(env)
    case_id = make_case_for(env)
    for _ in range(3):
        env.client.post(f"/api/cases/{case_id}/questions")
    assert env.client.post(f"/api/cases/{case_id}/questions").status_code == 429
    env.as_user("doctor-b")
    usage = env.client.get("/api/settings/ai").json()["usage"]
    assert usage["questions"] == {"used": 0, "limit": 3}


def test_settings_endpoint_reports_usage(env: Env, monkeypatch):
    monkeypatch.setattr(ClaudeQuestionWriter, "write", lambda *a: FollowUps())
    save_key(env)
    case_id = make_case_for(env)
    env.client.post(f"/api/cases/{case_id}/questions")
    usage = env.client.get("/api/settings/ai").json()["usage"]
    assert usage["questions"] == {"used": 1, "limit": 3}
    assert usage["analyses"] == {"used": 0, "limit": 2} and usage["window_minutes"] == 60


def test_saved_hourly_limit_applies_to_reruns_and_can_be_reset(env: Env, monkeypatch):
    monkeypatch.setattr(cases_routes, "get_supabase_admin_client", object)
    monkeypatch.setattr(cases_routes, "embedding_paused", lambda: True)
    monkeypatch.setattr(ClaudeReasoner, "normalise", lambda *_: NormalisedCase())
    save_key(env)
    case_id = make_case_for(env)
    analyze = f"/api/cases/{case_id}/analyze?search_mode=keyword"
    settings = "/api/settings/ai/analysis-limit"

    for _ in range(2):
        assert env.client.post(analyze).status_code == 201
    assert env.client.post(analyze).status_code == 429

    def set_limit(value):
        return env.client.put(settings, json={"hourly_analysis_limit": value})

    assert set_limit(-1).status_code == 422
    assert set_limit(3).json()["usage"]["analyses"] == {"used": 2, "limit": 3}
    assert env.client.post(analyze + "&acknowledge_red_flags=true").status_code == 201
    assert env.client.post(analyze).status_code == 429
    assert set_limit(0).json()["usage"]["analyses"]["limit"] == 0
    assert env.client.post(analyze).status_code == 201
    save_key(env)  # Key replacement preserves the separate limit column.
    assert env.client.get("/api/settings/ai").json()["hourly_analysis_limit"] == 0
    assert set_limit(None).json()["usage"]["analyses"]["limit"] == 2
    assert env.client.post(analyze).status_code == 429

    env.as_user("doctor-b")
    assert env.client.get("/api/settings/ai").json()["usage"]["analyses"]["limit"] == 2


def test_daily_override_can_be_raised_lowered_and_reset_without_resetting_usage(env, monkeypatch):
    monkeypatch.setattr(cases_routes, "get_supabase_admin_client", object)
    monkeypatch.setattr(cases_routes, "embedding_paused", lambda: True)
    monkeypatch.setattr(ClaudeReasoner, "normalise", lambda *_: NormalisedCase())
    save_key(env)
    case_id = make_case_for(env)
    analyze = f"/api/cases/{case_id}/analyze?search_mode=keyword"
    settings = "/api/settings/ai/analysis-limit"

    def set_daily(value):
        return env.client.put(settings, json={"daily_analysis_limit": value})

    assert env.client.put(settings, json={"hourly_analysis_limit": 0}).status_code == 200
    assert set_daily(-1).status_code == 422
    assert set_daily(1).json()["usage"]["daily_analyses"] == {"used": 0, "limit": 1}
    assert env.client.post(analyze).status_code == 201
    limited = env.client.post(analyze)
    assert limited.status_code == 429 and "1 case analysis per day" in limited.json()["detail"]
    assert set_daily(3).json()["usage"]["daily_analyses"] == {"used": 1, "limit": 3}
    assert env.client.post(analyze + "&acknowledge_red_flags=true").status_code == 201
    lowered = set_daily(1).json()
    assert lowered["hourly_analysis_limit"] == 0
    assert lowered["usage"]["daily_analyses"] == {"used": 2, "limit": 1}
    assert env.client.post(analyze).status_code == 429
    save_key(env)
    assert env.client.get("/api/settings/ai").json()["daily_analysis_limit"] == 1
    assert set_daily(0).json()["usage"]["daily_analyses"] == {"used": 2, "limit": 0}
    assert env.client.post(analyze).status_code == 201
    assert set_daily(None).json()["daily_analysis_limit"] is None
    env.as_user("doctor-b")
    assert env.client.get("/api/settings/ai").json()["daily_analysis_limit"] is None


def test_daily_and_monthly_ceilings_stop_a_doctor_who_stays_under_the_hourly_limit(monkeypatch):
    monkeypatch.setattr(
        ai_limits,
        "get_settings",
        lambda: SimpleNamespace(
            ai_questions_per_hour=50,
            ai_analyses_per_hour=50,
            ai_questions_per_day=3,
            ai_analyses_per_day=0,  # off
            ai_analyses_per_month=4,
        ),
    )
    store = InMemoryCaseStore()
    for hours in (20, 10, 5):  # spread out: never more than one an hour
        log(store, "a", "case.questions", hours * 60)
    with pytest.raises(ai_limits.RateLimitedError) as day:
        ai_limits.enforce(store, "a", "questions", now=NOW)
    assert day.value.window == "day" and "3 question requests per day" in day.value.message
    assert day.value.retry_after_seconds == 4 * 3600  # the oldest leaves the 24-hour window

    for days in (25, 15, 8, 2):
        log(store, "a", "case.analyze", days * 24 * 60)
    with pytest.raises(ai_limits.RateLimitedError) as month:
        ai_limits.enforce(store, "a", "analyses", now=NOW, hourly_analysis_limit=0)
    assert month.value.window == "month" and "per month" in month.value.message
    assert "hours" in month.value.message
    ai_limits.enforce(store, "b", "analyses", now=NOW)  # other doctors are unaffected
