"""Read-only operator endpoints never invoke embedding or modify the journal."""

import json
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials
from fastapi.testclient import TestClient

from app.api.auth import require_operator
from app.api.routes import monitor
from app.main import create_app


def test_knowledge_and_monitor_require_auth() -> None:
    client = TestClient(create_app())
    for path in ("/api/books", "/api/monitor/snapshot", "/api/monitor/chunks/" + "a" * 64):
        assert client.get(path).status_code == 401
    assert client.post("/api/search", json={"query": "fixture"}).status_code == 401


def test_provider_stop_uses_keyword_matching_and_never_creates_an_embedding_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.api.routes import knowledge

    monkeypatch.setattr(knowledge, "_require_db_config", lambda: None)
    monkeypatch.setattr(knowledge, "get_supabase_admin_client", lambda: object())
    monkeypatch.setattr(knowledge, "embedding_paused", lambda: True)
    monkeypatch.setattr(knowledge.knowledge_db, "save_retrieval_evaluation", lambda *_a: None)
    monkeypatch.setattr(knowledge, "book_completeness", lambda _db: {})
    monkeypatch.setattr(
        knowledge.knowledge_db,
        "keyword_search_chunks",
        lambda _db, tsquery, match_count, category=None: [],
    )

    def forbidden() -> None:
        pytest.fail("A provider-stopped search must not create an embedding provider")

    monkeypatch.setattr(knowledge, "get_embedding_provider", forbidden)
    app = create_app()
    app.dependency_overrides[require_operator] = lambda: "fixture-operator"
    response = TestClient(app).post("/api/search", json={"query": "burning pain"})
    assert response.status_code == 200 and response.json()["retrieval_mode"] == "keyword"


def test_operator_role_must_be_trusted(monkeypatch: pytest.MonkeyPatch) -> None:
    client = SimpleNamespace(
        auth=SimpleNamespace(
            get_user=lambda _: SimpleNamespace(
                user=SimpleNamespace(
                    id="user", app_metadata={}, user_metadata={"similia_role": "operator"}
                )
            )
        )
    )
    monkeypatch.setattr("app.api.auth.get_supabase_admin_client", lambda: client)
    with pytest.raises(HTTPException) as exc:
        require_operator(HTTPAuthorizationCredentials(scheme="Bearer", credentials="fixture-token"))
    assert exc.value.status_code == 403
    client.auth.get_user = lambda _: SimpleNamespace(
        user=SimpleNamespace(id="user", app_metadata={"similia_role": "operator"})
    )
    assert (
        require_operator(HTTPAuthorizationCredentials(scheme="Bearer", credentials="fixture-token"))
        == "user"
    )


def test_reports_and_chunk_filters_are_read_only(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(monitor, "REPORTS", tmp_path)
    digest = "a" * 64
    artifacts = {
        "pdf_inventory.json": {
            "selected_hashes": [digest],
            "books": [
                {"file_hash": digest, "filename": "fixture.pdf", "source_directory": "private"}
            ],
        },
        "run_manifest.json": {"cumulative_pipeline_cap": 900000, "status": "paused"},
        "ingestion_progress.json": {
            "books": [
                {
                    "file_hash": digest,
                    "pending_chunk_indices": [1],
                    "current_checkpoint": {"last_batch_id": "private", "last_page": 3},
                }
            ],
            "usage": {"provider_reported_tokens": 42, "books": []},
        },
    }
    for name, body in artifacts.items():
        (tmp_path / name).write_text(json.dumps(body))
    source = tmp_path / "sources" / digest
    source.mkdir(parents=True)
    (source / "plan.json").write_text(
        json.dumps(
            {
                "chunks": [
                    {
                        "chunk_index": 0,
                        "content": "First passage",
                        "token_count": 3,
                        "metadata": {"section": "Mind"},
                    },
                    {
                        "chunk_index": 1,
                        "content": "Second café passage",
                        "token_count": 4,
                        "metadata": {"section": "Head"},
                    },
                ]
            }
        )
    )
    before = {p: p.read_bytes() for p in tmp_path.rglob("*.json")}
    app = create_app()
    app.dependency_overrides[require_operator] = lambda: "fixture-operator"
    client = TestClient(app)
    snapshot = client.get("/api/monitor/snapshot").json()
    assert snapshot["usage"]["provider_reported_tokens"] == 42
    assert "source_directory" not in snapshot["inventory"][0]
    assert "pending_chunk_indices" not in snapshot["books"][0]
    assert snapshot["capabilities"]["start"] is False
    result = client.get(f"/api/monitor/chunks/{digest}?q=caf&section=head").json()
    assert result["total"] == 1
    assert result["items"][0]["embedding_status"] == "pending"
    assert result["items"][0]["byte_count"] == len("Second café passage".encode())
    assert client.get("/api/monitor/chunks/" + "b" * 64).status_code == 404
    assert client.get(f"/api/monitor/chunks/{digest}?limit=101").status_code == 422
    assert before == {p: p.read_bytes() for p in tmp_path.rglob("*.json")}


def test_missing_reports_return_unavailable(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(monitor, "REPORTS", tmp_path)
    app = create_app()
    app.dependency_overrides[require_operator] = lambda: "fixture-operator"
    assert TestClient(app).get("/api/monitor/snapshot").status_code == 503
