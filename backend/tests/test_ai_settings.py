"""Bring-your-own AI key: encryption, write-only API, per-user use of the key."""

import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from app.ai.rag.case_questions import ClaudeQuestionWriter, FollowUps
from app.api.auth import require_practitioner
from app.api.routes import ai_settings as settings_routes
from app.api.routes import cases as cases_routes
from app.core import vault
from app.main import create_app
from app.services.compatible_llm import CompatibleProviderError
from app.services.user_ai import (
    KeyPausedError,
    KeyRejectedError,
    NoUserKeyError,
    ProviderUnavailableError,
    is_active,
    parse_active_until,
    provider_for,
)
from tests.test_cases_api import InMemoryCaseStore

KEY_A = "sk-ant-api03-AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAWXYZ"
KEY_B = "sk-ant-api03-BBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB1234"


def save_key(env, key=None, model="claude-sonnet-5-5"):
    return env.client.put("/api/settings/ai", json={"api_key": key or KEY_A, "model": model})


class InMemoryAIStore:
    def __init__(self) -> None:
        self.rows: dict[str, dict] = {}

    def get(self, owner):
        return dict(self.rows[owner]) if owner in self.rows else None

    def save(self, owner, row):
        self.rows[owner] = {**self.rows.get(owner, {}), **row, "practitioner_id": owner}

    def update(self, owner, provider, changes):
        row = self.rows.get(owner)
        if not row or row["provider"] != provider:
            return False
        row.update(changes)
        return True

    def delete(self, owner):
        self.rows.pop(owner, None)


@pytest.fixture
def secret(monkeypatch: pytest.MonkeyPatch) -> str:
    key = Fernet.generate_key().decode()
    monkeypatch.setattr(vault, "get_settings", lambda: SimpleNamespace(app_encryption_key=key))
    return key


class Env:
    def __init__(self, client, ai, audit, who, verifier):
        self.client, self.ai, self.audit, self.who, self.verifier = client, ai, audit, who, verifier

    def as_user(self, user):
        self.who["id"] = user
        return self


@pytest.fixture
def env(secret) -> Env:
    app = create_app()
    ai, audit, who = InMemoryAIStore(), InMemoryCaseStore(), {"id": "doctor-a"}
    verifier = {"result": None}  # None = accept; or an exception to raise

    def verify(_key, provider):
        verifier["provider"] = provider
        if verifier["result"] is not None:
            raise verifier["result"]

    app.dependency_overrides[require_practitioner] = lambda: who["id"]
    app.dependency_overrides[settings_routes.get_ai_store] = lambda: ai
    app.dependency_overrides[settings_routes.get_audit_store] = lambda: audit
    app.dependency_overrides[settings_routes.get_key_verifier] = lambda: verify
    app.dependency_overrides[cases_routes.get_case_store] = lambda: audit
    return Env(TestClient(app), ai, audit, who, verifier)


def test_vault_round_trip_and_ciphertext_hides_the_key(secret):
    token = vault.encrypt_secret(KEY_A)
    assert KEY_A not in token and vault.decrypt_secret(token) == KEY_A


def test_vault_refuses_without_server_secret_and_with_the_wrong_one(monkeypatch, secret):
    token = vault.encrypt_secret(KEY_A)
    other = Fernet.generate_key().decode()
    monkeypatch.setattr(vault, "get_settings", lambda: SimpleNamespace(app_encryption_key=other))
    with pytest.raises(vault.VaultError):
        vault.decrypt_secret(token)
    monkeypatch.setattr(vault, "get_settings", lambda: SimpleNamespace(app_encryption_key=""))
    assert vault.vault_ready() is False
    with pytest.raises(vault.VaultError):
        vault.encrypt_secret(KEY_A)


def test_requires_sign_in():
    assert TestClient(create_app()).get("/api/settings/ai").status_code == 401


def test_save_encrypts_verifies_and_never_returns_the_key(env: Env):
    assert env.client.get("/api/settings/ai").json()["configured"] is False
    response = save_key(env, KEY_A, "claude-sonnet-5-5")
    assert response.status_code == 200
    body = response.json()
    assert body["configured"] and body["key_last4"] == "WXYZ" and body["validated_at"]
    for text in (response.text, env.client.get("/api/settings/ai").text):
        assert KEY_A not in text and "encrypted" not in text
    stored = env.ai.rows["doctor-a"]
    assert KEY_A not in json.dumps(stored)
    assert vault.decrypt_secret(stored["encrypted_api_key"]) == KEY_A
    assert all(KEY_A not in json.dumps(row, default=str) for row in env.audit.audit_rows)
    assert any(row[1] == "ai_settings.key_saved" for row in env.audit.audit_rows)


def test_rejected_key_is_not_saved(env: Env):
    env.verifier["result"] = KeyRejectedError("no")
    response = save_key(env, KEY_A, "claude-sonnet-5-5")
    assert response.status_code == 422 and KEY_A not in response.text
    assert env.ai.rows == {}


def test_provider_outage_gives_502_and_saves_nothing(env: Env):
    env.verifier["result"] = ProviderUnavailableError("down")
    response = save_key(env, KEY_A, "claude-sonnet-5-5")
    assert response.status_code == 502 and env.ai.rows == {}


def test_bad_input_is_refused(env: Env):
    put = lambda body: env.client.put("/api/settings/ai", json=body)  # noqa: E731
    assert put({"api_key": KEY_A, "model": "not-a-model"}).status_code == 422
    assert put({"api_key": "short", "model": "claude-sonnet-5-5"}).status_code == 422
    spaced = KEY_A[:25] + " " + KEY_A[26:]
    assert put({"api_key": spaced, "model": "claude-sonnet-5-5"}).status_code == 422
    assert put({"model": "claude-sonnet-5-5"}).status_code == 422  # no key saved yet
    assert env.ai.rows == {}


def test_missing_server_secret_gives_clear_503(env: Env, monkeypatch):
    monkeypatch.setattr(vault, "get_settings", lambda: SimpleNamespace(app_encryption_key=""))
    response = save_key(env, KEY_A, "claude-sonnet-5-5")
    assert response.status_code == 503 and "APP_ENCRYPTION_KEY" in response.json()["detail"]


def test_model_can_change_without_re_entering_the_key(env: Env):
    save_key(env, KEY_A, "claude-sonnet-5-5")
    response = env.client.put("/api/settings/ai", json={"model": "claude-haiku-5-5"})
    assert response.json()["model"] == "claude-haiku-5-5" and response.json()["key_last4"] == "WXYZ"
    assert vault.decrypt_secret(env.ai.rows["doctor-a"]["encrypted_api_key"]) == KEY_A


def test_switching_providers_requires_its_own_key_and_preserves_failed_settings(env: Env):
    save_key(env, KEY_A)
    path = "/api/settings/ai"
    options = {entry["id"] for entry in env.client.get(path).json()["providers"]}
    assert options == {"anthropic", "openai", "gemini", "openrouter"}
    selection = {"provider": "gemini", "model": "gemini-test-model"}
    assert env.client.put(path, json=selection).status_code == 422
    assert env.client.get(path).json()["provider"] == "anthropic"
    invalid = env.client.put(path, json={**selection, "provider": "https://example.test"})
    assert invalid.status_code == 422

    new_key = "synthetic-gemini-key-123456"
    response = env.client.put(path, json={**selection, "api_key": new_key})
    assert response.status_code == 200 and response.json()["provider"] == "gemini"
    assert new_key not in response.text and env.verifier["provider"] == "gemini"
    llm = provider_for(env.ai.get("doctor-a"))
    assert llm.model == "gemini-test-model" and llm._api_key == new_key


def test_catalog_uses_only_a_key_for_the_requested_provider_and_never_saves_it(env, monkeypatch):
    path = "/api/settings/ai/models"
    save_key(env, KEY_A)
    seen = []

    def list_models(key, provider):
        seen.append((key, provider))
        return {"provider-chat-id": "Provider chat name"}

    monkeypatch.setattr(settings_routes, "list_provider_models", list_models)
    assert env.client.post(path, json={"provider": "gemini"}).status_code == 422
    assert not seen
    assert env.client.post(path, json={"provider": "anthropic"}).status_code == 200
    new_key = "synthetic-gemini-key-123456"
    response = env.client.post(path, json={"provider": "gemini", "api_key": new_key})
    assert response.json() == [{"id": "provider-chat-id", "label": "Provider chat name"}]
    assert seen == [(KEY_A, "anthropic"), (new_key, "gemini")]
    assert env.ai.rows["doctor-a"]["provider"] == "anthropic"


def test_diagnostics_separate_a_model_failure_from_working_semantic_search(env, monkeypatch):
    save_key(env)
    def fail(_self, text, language):
        assert "blue notebook" in text and language == "en"
        raise CompatibleProviderError(429)

    def embed(text):
        assert text == "blue notebook"
        return [0.5]

    monkeypatch.setattr(settings_routes.ClaudeReasoner, "normalise", fail)
    monkeypatch.setattr(settings_routes, "embedding_paused", lambda: False)
    monkeypatch.setattr(settings_routes, "get_settings", lambda: SimpleNamespace(
        voyage_model="voyage-test", voyage_api_key="synthetic-voyage-key"
    ))
    monkeypatch.setattr(settings_routes, "get_embedding_provider", lambda **_: SimpleNamespace(
        embed_query=embed
    ))
    monkeypatch.setattr(settings_routes, "get_supabase_admin_client", object)
    monkeypatch.setattr(settings_routes.knowledge_db, "search_chunks", lambda *_a, **_kw: [])
    result = env.client.post("/api/settings/ai/diagnostics").json()
    assert [(row["service"], row["status"]) for row in result] == [
        ("Anthropic", "failed"), ("Voyage", "passed"), ("Semantic source library", "passed"),
    ]
    assert result[0]["upstream_status"] == 429
    assert not env.audit.analyses

    monkeypatch.setattr(settings_routes, "embedding_paused", lambda: True)
    monkeypatch.setattr(settings_routes, "get_embedding_provider", None)
    paused = env.client.post("/api/settings/ai/diagnostics").json()
    assert paused[1]["status"] == "skipped" and "paused" in paused[1]["detail"]


def test_each_doctor_has_their_own_key_and_can_delete_it(env: Env):
    save_key(env, KEY_A, "claude-sonnet-5-5")
    env.as_user("doctor-b")
    assert env.client.get("/api/settings/ai").json()["configured"] is False
    save_key(env, KEY_B, "claude-opus-5-5")
    assert env.client.get("/api/settings/ai").json()["key_last4"] == "1234"
    assert env.client.delete("/api/settings/ai").json()["configured"] is False
    env.as_user("doctor-a")
    assert env.client.get("/api/settings/ai").json()["key_last4"] == "WXYZ"


def test_provider_for_uses_that_users_key_and_model(env: Env):
    save_key(env, KEY_A, "claude-haiku-5-5")
    llm = provider_for(env.ai.get("doctor-a"))
    assert llm._api_key == KEY_A and llm._model == "claude-haiku-5-5"
    with pytest.raises(NoUserKeyError):
        provider_for(env.ai.get("doctor-b"))


def test_ai_features_need_the_users_own_key_and_use_it(env: Env, monkeypatch):
    seen: list[str] = []

    def fake_write(self, case_text, language):
        seen.append(self._llm._api_key)
        return FollowUps()

    monkeypatch.setattr(ClaudeQuestionWriter, "write", fake_write)
    patient = env.client.post("/api/patients", json={
        "identifier": "P-1", "full_name": "T", "consent_given": True}).json()
    case_id = env.client.post("/api/cases", json={
        "patient_id": patient["id"], "chief_complaint": "itchy skin"}).json()["id"]

    blocked = env.client.post(f"/api/cases/{case_id}/questions")
    assert blocked.status_code == 428 and "AI Settings" in blocked.json()["detail"]
    assert seen == []

    save_key(env, KEY_A, "claude-sonnet-5-5")
    assert env.client.post(f"/api/cases/{case_id}/questions").status_code == 200
    assert seen == [KEY_A]  # never a shared server key


# -- active period: 1 day by default, or 1 week / 1 month --------------------------------------


def hours_until(env: Env, user: str = "doctor-a") -> float:
    until = parse_active_until(env.ai.rows[user])
    return (until - datetime.now(timezone.utc)).total_seconds() / 3600


def expire(env: Env, delta: timedelta = timedelta(minutes=1)) -> None:
    env.ai.rows["doctor-a"]["active_until"] = (datetime.now(timezone.utc) - delta).isoformat()


def test_a_new_key_is_active_for_one_day_by_default_and_the_choice_is_respected(env: Env):
    body = save_key(env).json()
    assert body["active"] is True and 23.9 < hours_until(env) <= 24
    assert [o["id"] for o in body["active_options"]] == ["1d", "7d", "30d"]
    for choice, days in (("7d", 7), ("30d", 30)):
        env.client.put(
            "/api/settings/ai",
            json={"api_key": KEY_A, "model": "claude-sonnet-5-5", "active_for": choice},
        )
        assert days * 24 - 0.1 < hours_until(env) <= days * 24
    bad = env.client.put(
        "/api/settings/ai",
        json={"api_key": KEY_A, "model": "claude-sonnet-5-5", "active_for": "forever"},
    )
    assert bad.status_code == 422


def test_an_expired_key_stays_saved_but_is_paused_and_ai_is_blocked(env: Env, monkeypatch):
    seen: list[str] = []
    monkeypatch.setattr(
        ClaudeQuestionWriter, "write", lambda self, *a: seen.append("x") or FollowUps()
    )
    save_key(env)
    expire(env)
    shown = env.client.get("/api/settings/ai").json()
    assert shown["configured"] is True and shown["active"] is False
    assert shown["key_last4"] == "WXYZ"
    patient = env.client.post(
        "/api/patients", json={"identifier": "P-1", "full_name": "T", "consent_given": True}
    ).json()
    case_id = env.client.post(
        "/api/cases", json={"patient_id": patient["id"], "chief_complaint": "itch"}
    ).json()["id"]
    blocked = env.client.post(f"/api/cases/{case_id}/questions")
    assert blocked.status_code == 428 and "paused" in blocked.json()["detail"]
    assert seen == []


def test_turning_a_paused_key_back_on_needs_no_re_entry(env: Env):
    save_key(env)
    expire(env, timedelta(days=1))
    body = env.client.post("/api/settings/ai/activate", json={"active_for": "7d"}).json()
    assert body["active"] is True and 167.9 < hours_until(env) <= 168
    assert vault.decrypt_secret(env.ai.rows["doctor-a"]["encrypted_api_key"]) == KEY_A


def test_pause_now_stops_ai_immediately_and_keeps_the_key(env: Env):
    save_key(env)
    body = env.client.post("/api/settings/ai/deactivate").json()
    assert body["configured"] is True and body["active"] is False
    with pytest.raises(KeyPausedError):
        provider_for(env.ai.get("doctor-a"))


def test_activate_and_pause_need_a_saved_key_and_are_per_doctor(env: Env):
    assert env.client.post("/api/settings/ai/activate", json={}).status_code == 404
    assert env.client.post("/api/settings/ai/deactivate").status_code == 404
    save_key(env)
    env.as_user("doctor-b")
    assert env.client.post("/api/settings/ai/activate", json={}).status_code == 404
    env.as_user("doctor-a")
    assert env.client.get("/api/settings/ai").json()["active"] is True


def test_a_row_without_an_expiry_is_treated_as_paused():
    assert is_active({"model": "x"}) is False
