"""Operator ingestion endpoints: auth, free preparing, confirmed starts, pause, inspection."""

# ruff: noqa: F811
import pytest
from fastapi.testclient import TestClient

from app.ai.ingestion.service import IngestionService
from app.api.auth import require_operator
from app.api.routes import knowledge
from app.main import create_app
from tests.conftest import MockEmbeddingProvider, install_fake_db
from tests.sample_data import ORGANON_SAMPLE

UNKNOWN = "11111111-2222-3333-4444-555555555555"


class Env:
    def __init__(self, client: TestClient, fake_db, embedder, service) -> None:
        self.client, self.db, self.embedder, self.service = client, fake_db, embedder, service

    def upload(self, text: str = ORGANON_SAMPLE, **overrides) -> dict:
        form = {"category": "organon", "title": "Organon (sample)", **overrides}
        response = self.client.post(
            "/api/books", data=form, files={"file": ("organon.txt", text.encode(), "text/plain")}
        )
        assert response.status_code == 201, response.text
        return response.json()


@pytest.fixture()
def env(monkeypatch: pytest.MonkeyPatch) -> Env:
    fake_db = install_fake_db(monkeypatch)
    embedder = MockEmbeddingProvider()
    service = IngestionService(db=object(), embedder=embedder, batch_tokens=60)
    monkeypatch.setattr(knowledge, "_require_db_config", lambda: None)
    monkeypatch.setattr(knowledge, "get_supabase_admin_client", lambda: object())
    app = create_app()
    app.dependency_overrides[require_operator] = lambda: "operator"
    app.dependency_overrides[knowledge.get_ingestion_service] = lambda: service
    return Env(TestClient(app), fake_db, embedder, service)


def test_every_ingestion_endpoint_requires_a_verified_operator() -> None:
    client = TestClient(create_app())
    for path in (
        "/api/ingestion/overview",
        f"/api/books/{UNKNOWN}/ingestion",
        f"/api/books/{UNKNOWN}/chunks",
        f"/api/books/{UNKNOWN}/text",
        f"/api/ingestion-jobs/{UNKNOWN}",
        f"/api/ingestion-jobs/{UNKNOWN}/events",
    ):
        assert client.get(path).status_code == 401, path
    for path in (
        f"/api/books/{UNKNOWN}/prepare",
        f"/api/books/{UNKNOWN}/ingest",
        f"/api/ingestion-jobs/{UNKNOWN}/pause",
    ):
        assert client.post(path, json={"confirmed": True}).status_code == 401, path


def test_upload_prepare_confirm_and_run_end_to_end_with_a_mock_provider(env: Env) -> None:
    book = env.upload()
    overview = env.client.get("/api/ingestion/overview").json()
    row = next(b for b in overview["books"] if b["book_id"] == book["id"])
    assert row["prepared"] is False and row["total_chunks"] == 0

    plan = env.client.post(f"/api/books/{book['id']}/prepare").json()
    assert plan["can_start"] is True and plan["stats"]["pending_tokens"] > 0
    assert env.embedder.document_calls == []  # preparing is free

    started = env.client.post(f"/api/books/{book['id']}/ingest", json={"confirmed": True})
    assert started.status_code == 202
    assert started.json()["status"] == "pending"

    # TestClient has run the background task by now: the job is finished.
    job = env.client.get(f"/api/ingestion-jobs/{started.json()['id']}").json()
    assert job["status"] == "completed" and job["processed_chunks"] == job["total_chunks"]
    stats = env.client.get(f"/api/books/{book['id']}/ingestion").json()
    assert stats["plan"]["stats"]["complete"] is True and stats["jobs"][0]["id"] == job["id"]
    events = env.client.get(f"/api/ingestion-jobs/{job['id']}/events").json()
    assert {"started", "completed"} <= {e["kind"] for e in events}


def test_starting_without_confirmation_is_refused_and_sends_nothing(env: Env) -> None:
    book = env.upload()
    env.client.post(f"/api/books/{book['id']}/prepare")
    for body in ({}, {"confirmed": False}):
        response = env.client.post(f"/api/books/{book['id']}/ingest", json=body)
        assert response.status_code == 409
    assert env.embedder.document_calls == [] and env.db.jobs == {}


def test_starting_before_preparing_is_a_clear_conflict(env: Env) -> None:
    book = env.upload()
    response = env.client.post(f"/api/books/{book['id']}/ingest", json={"confirmed": True})
    assert response.status_code == 409 and "Prepare the book first" in response.json()["detail"]


def test_an_unknown_book_is_404_everywhere(env: Env) -> None:
    for method, path in (
        ("get", f"/api/books/{UNKNOWN}/ingestion"),
        ("get", f"/api/books/{UNKNOWN}/chunks"),
        ("get", f"/api/books/{UNKNOWN}/text"),
        ("post", f"/api/books/{UNKNOWN}/prepare"),
    ):
        assert getattr(env.client, method)(path).status_code == 404, path
    assert (
        env.client.post(f"/api/books/{UNKNOWN}/ingest", json={"confirmed": True}).status_code == 404
    )
    assert env.client.get(f"/api/ingestion-jobs/{UNKNOWN}").status_code == 404


def test_a_bad_id_is_a_validation_error(env: Env) -> None:
    assert env.client.get("/api/books/not-a-uuid/ingestion").status_code == 422


def test_a_set_provider_stop_blocks_starting_with_429(env: Env) -> None:
    env.service.provider_pause = lambda: "The embedding provider stop is set."
    book = env.upload()
    env.client.post(f"/api/books/{book['id']}/prepare")
    response = env.client.post(f"/api/books/{book['id']}/ingest", json={"confirmed": True})
    assert response.status_code == 429
    assert env.embedder.document_calls == []
    plan = env.client.get(f"/api/books/{book['id']}/ingestion").json()["plan"]
    assert plan["can_start"] is False and plan["limits"]["provider_paused"] is True


def test_the_server_limit_stops_a_job_even_if_the_browser_asks_for_more(env: Env) -> None:
    env.service.max_tokens = 1
    book = env.upload()
    env.client.post(f"/api/books/{book['id']}/prepare")
    started = env.client.post(
        f"/api/books/{book['id']}/ingest", json={"confirmed": True, "max_tokens": 10_000_000}
    )
    job = env.client.get(f"/api/ingestion-jobs/{started.json()['id']}").json()
    assert job["status"] == "paused" and job["stop_reason"] == "Token limit reached"
    assert env.embedder.document_calls == []


def test_pausing_an_active_job_and_refusing_to_pause_a_finished_one(env: Env) -> None:
    book = env.upload()
    env.client.post(f"/api/books/{book['id']}/prepare")
    # Create an active job directly (no background run) so it is still pending.
    job = env.service.start_ingestion(book["id"], confirmed=True)
    paused = env.client.post(f"/api/ingestion-jobs/{job['id']}/pause")
    assert paused.status_code == 200 and paused.json()["pause_requested"] is True
    env.service.run_ingestion(job["id"])
    assert env.client.get(f"/api/ingestion-jobs/{job['id']}").json()["status"] == "paused"
    assert env.client.post(f"/api/ingestion-jobs/{UNKNOWN}/pause").status_code == 409


def test_chunk_inspection_is_paged_filtered_and_never_returns_vectors(env: Env) -> None:
    book = env.upload(ORGANON_SAMPLE + "\fSecond page of the sample text.")
    env.client.post(f"/api/books/{book['id']}/prepare")
    page = env.client.get(f"/api/books/{book['id']}/chunks?limit=1").json()
    assert page["total"] >= 1 and len(page["items"]) == 1
    assert "embedding" not in page["items"][0] and page["items"][0]["embedded"] is False
    assert env.client.get(f"/api/books/{book['id']}/chunks?embedded=true").json()["total"] == 0
    assert env.client.get(f"/api/books/{book['id']}/chunks?limit=500").status_code == 422
    text = env.client.get(f"/api/books/{book['id']}/text?limit=1").json()
    assert text["total_pages"] == 2 and text["pages"][0]["page"] == 1


def test_duplicate_uploads_are_rejected(env: Env) -> None:
    env.upload()
    response = env.client.post(
        "/api/books",
        data={"category": "organon", "title": "Again"},
        files={"file": ("again.txt", ORGANON_SAMPLE.encode(), "text/plain")},
    )
    assert response.status_code == 409


def test_unreadable_and_oversized_metadata_are_validation_errors(env: Env) -> None:
    bad = env.client.post(
        "/api/books",
        data={"category": "organon", "title": "x"},
        files={"file": ("x.txt", b"text\x00binary", "text/plain")},
    )
    assert bad.status_code == 422
    long_title = env.client.post(
        "/api/books",
        data={"category": "organon", "title": "t" * 301},
        files={"file": ("x.txt", ORGANON_SAMPLE.encode(), "text/plain")},
    )
    assert long_title.status_code == 422


def test_search_flags_partly_indexed_books_with_pdf_pages(
    env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.ai.rag.retrieval import RetrievedPassage

    book = env.upload()
    passage = RetrievedPassage(
        chunk_id="c1",
        book_id=book["id"],
        section_id=None,
        book_title="Organon (sample)",
        book_category="organon",
        book_author=None,
        section_heading="Aphorism 1",
        section_path=["Aphorism 1"],
        content="The physician's highest calling is to restore the sick to health.",
        similarity=0.8,
        metadata={"page_start": 3, "page_end": 4},
    )

    class FakeRetriever:
        def __init__(self, **_kwargs) -> None: ...

        def search(self, *_args, **_kwargs):
            return [passage], 5

    monkeypatch.setattr(knowledge, "VectorRetriever", FakeRetriever)
    monkeypatch.setattr(knowledge, "get_embedding_provider", lambda: env.embedder)
    monkeypatch.setattr(knowledge, "embedding_paused", lambda: False)
    monkeypatch.setattr(knowledge.knowledge_db, "save_retrieval_evaluation", lambda *_a: None)
    monkeypatch.setattr(knowledge, "book_completeness", lambda _db: {book["id"]: False})

    body = env.client.post("/api/search", json={"query": "restore the sick"}).json()
    hit = body["results"][0]
    assert hit["page_start"] == 3 and hit["page_end"] == 4 and hit["book_complete"] is False
    assert body["incomplete_books"] == ["Organon (sample)"]
