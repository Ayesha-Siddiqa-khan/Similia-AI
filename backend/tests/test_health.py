"""Smoke tests for GET /health."""

from fastapi.testclient import TestClient

from app.main import create_app

client = TestClient(create_app())


def test_health_returns_ok() -> None:
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["app"] == "Similia AI API"
    assert body["version"] == "0.1.0"


def test_health_reports_provider_status_without_secrets() -> None:
    response = client.get("/health")
    services = response.json()["services"]
    assert set(services) == {"supabase", "anthropic", "voyage"}
    assert all(isinstance(v, bool) for v in services.values())
    # No secret material may leak through /health.
    assert "key" not in response.text.lower()
