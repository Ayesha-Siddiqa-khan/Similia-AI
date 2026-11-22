"""Start-up checks, readiness probe and safe request logging."""

import logging

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from app.api.routes import health
from app.core.config import Settings
from app.core.request_log import log_path
from app.core.startup import ConfigurationError, check_configuration, configuration_problems
from app.main import create_app


def good(**overrides) -> Settings:
    base = dict(
        _env_file=None,
        environment="production",
        supabase_url="https://example.supabase.co",
        supabase_secret_key="secret-value-1",
        supabase_publishable_key="publishable-value-1",
        app_encryption_key=Fernet.generate_key().decode(),
        cors_origins="https://similia.example",
        voyage_api_key="voyage-value-1",
    )
    return Settings(**{**base, **overrides})


def test_a_complete_production_configuration_has_no_problems() -> None:
    assert configuration_problems(good()) == []
    assert check_configuration(good()) == []


def test_production_refuses_to_start_when_unsafe_and_never_prints_a_secret() -> None:
    bad = good(supabase_secret_key="", app_encryption_key="not-a-key", cors_origins="*")
    with pytest.raises(ConfigurationError) as caught:
        check_configuration(bad)
    text = str(caught.value)
    assert "SUPABASE_SECRET_KEY" in text and "valid Fernet key" in text and "'*'" in text
    assert "not-a-key" not in text and "secret-value-1" not in text


def test_production_needs_https_origins_and_a_search_key() -> None:
    problems = " ".join(
        configuration_problems(good(cors_origins="http://site.example", voyage_api_key=""))
    )
    assert "https://" in problems and "VOYAGE_API_KEY" in problems


def test_development_only_warns(caplog: pytest.LogCaptureFixture) -> None:
    dev = good(environment="development", supabase_url="", cors_origins="http://localhost:3000")
    with caplog.at_level(logging.WARNING):
        found = check_configuration(dev)
    assert any("SUPABASE_URL" in p for p in found)
    assert "SUPABASE_URL" in caplog.text


def test_the_lifespan_blocks_a_production_start_with_bad_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.main as main

    monkeypatch.setattr(main, "get_settings", lambda: good(supabase_url=""))
    with pytest.raises(ConfigurationError):
        with TestClient(create_app()):
            pass


def test_ready_reports_ok_or_a_short_reason_without_details(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(health, "get_settings", lambda: good())
    client = TestClient(create_app())
    monkeypatch.setattr(health, "_database_check", lambda: None)
    up = client.get("/ready")
    assert up.status_code == 200 and up.json()["checks"] == {
        "configuration": "ok",
        "database": "ok",
    }

    def down() -> None:
        raise RuntimeError("could not connect to db.internal.example password=hunter2")

    monkeypatch.setattr(health, "_database_check", down)
    out = client.get("/ready")
    assert out.status_code == 503 and out.json()["checks"]["database"] == "unavailable"
    assert "hunter2" not in out.text and "internal" not in out.text


def test_each_request_gets_an_id_and_the_log_holds_no_query_body_or_record_id(
    caplog: pytest.LogCaptureFixture,
) -> None:
    client = TestClient(create_app())
    pid = "123e4567-e89b-12d3-a456-426614174000"
    with caplog.at_level(logging.INFO, logger="similia.request"):
        response = client.get(
            f"/api/patients/{pid}?name=Jane+Doe", headers={"x-request-id": "bad id!"}
        )
        again = client.get("/health", headers={"x-request-id": "abcdef12-good-id"})
    assert (
        response.headers["x-request-id"] != "bad id!" and len(response.headers["x-request-id"]) >= 8
    )
    assert again.headers["x-request-id"] == "abcdef12-good-id"
    ours = " | ".join(r.getMessage() for r in caplog.records if r.name == "similia.request")
    assert "Jane" not in ours and pid not in ours
    assert "/api/patients/{id}" in ours and "401" in ours


def test_log_path_replaces_record_ids() -> None:
    assert log_path("/api/cases/123e4567-e89b-12d3-a456-426614174000/analyze") == (
        "/api/cases/{id}/analyze"
    )


def test_the_encryption_key_can_be_replaced_without_locking_anyone_out(monkeypatch) -> None:
    from types import SimpleNamespace

    from app.core import vault

    old_key, new_key = Fernet.generate_key().decode(), Fernet.generate_key().decode()

    def use(primary: str, previous: str = "") -> None:
        monkeypatch.setattr(
            vault,
            "get_settings",
            lambda: SimpleNamespace(
                app_encryption_key=primary, app_encryption_key_previous=previous
            ),
        )

    use(old_key)
    stored = vault.encrypt_secret("sk-ant-example-value")
    use(new_key)  # new key only: the old value can no longer be read
    with pytest.raises(vault.VaultError):
        vault.decrypt_secret(stored)
    use(new_key, old_key)  # rotation window: both work
    assert vault.decrypt_secret(stored) == "sk-ant-example-value"
    moved = vault.rotate_secret(stored)
    use(new_key)  # the old key can now be removed
    assert vault.decrypt_secret(moved) == "sk-ant-example-value"
    assert "sk-ant" not in moved


def test_an_invalid_previous_key_is_reported_without_printing_it() -> None:
    problems = " ".join(configuration_problems(good(app_encryption_key_previous="garbage-key")))
    assert "APP_ENCRYPTION_KEY_PREVIOUS" in problems and "garbage-key" not in problems
