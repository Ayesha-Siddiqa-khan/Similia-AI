"""The desktop launcher token protects the loopback API from other local processes."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.core.config import Settings
from app.core.desktop_guard import HEADER, DesktopTokenMiddleware


def _client(token: str = "test-launch-token") -> TestClient:
    app = FastAPI()
    app.add_middleware(DesktopTokenMiddleware, token=token)

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/speech/settings")
    def settings() -> dict[str, str]:
        return {"status": "ok"}

    return TestClient(app)


def test_api_requires_desktop_token() -> None:
    client = _client()
    assert client.get("/api/speech/settings").status_code == 401
    assert client.get("/api/speech/settings", headers={HEADER: "wrong"}).status_code == 401
    assert (
        client.get("/api/speech/settings", headers={HEADER: "test-launch-token"}).status_code
        == 200
    )


def test_health_probe_requires_token() -> None:
    client = _client()
    assert client.get("/health").status_code == 401
    assert client.get("/health", headers={HEADER: "test-launch-token"}).status_code == 200


def test_settings_read_launcher_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SIMILIA_DESKTOP_TOKEN", "test-launch-token")
    assert Settings(_env_file=None).desktop_token == "test-launch-token"


def test_graphql_websocket_rejects_missing_token() -> None:
    with pytest.raises(WebSocketDisconnect) as exc, _client().websocket_connect("/graphql"):
        pytest.fail("Unauthenticated WebSocket was accepted")
    assert exc.value.code == 1008


def test_graphql_is_protected() -> None:
    client = _client()
    assert client.post("/graphql", json={"query": "{ health }"}).status_code == 401
    assert (
        client.post(
            "/graphql",
            json={"query": "{ health }"},
            headers={HEADER: "test-launch-token"},
        ).status_code
        != 401
    )
