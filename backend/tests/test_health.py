"""Smoke tests for GET /health."""

from fastapi.testclient import TestClient

from app.api.routes.health import INSTANCE_ID
from app.core.config import get_settings
from app.main import create_app

client = TestClient(create_app())


def test_health_returns_ok() -> None:
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["app"] == "Similia AI API"
    assert body["version"] == "0.1.0"


def test_development_process_id_is_stable() -> None:
    expected = INSTANCE_ID if get_settings().environment.strip().lower() == "development" else None
    assert client.get("/health").json()["instance_id"] == expected
    assert client.get("/health").json()["instance_id"] == expected


def test_health_reports_provider_status_without_secrets() -> None:
    response = client.get("/health")
    services = response.json()["services"]
    assert set(services) == {"supabase", "anthropic", "voyage"}
    assert all(isinstance(v, bool) for v in services.values())
    # No secret material may leak through /health.
    assert "key" not in response.text.lower()
