"""Ingestion service tests: registration, preparing, confirmed spending, pause/resume without
duplication, limits and budget, provider stop, provider errors, crash recovery, history."""

import hashlib
from datetime import datetime, timedelta, timezone

import pytest

from app.ai.ingestion.extraction import ExtractionError
from app.ai.ingestion.service import (
    STALE_JOB_SECONDS,
    BookNotFoundError,
    BudgetExhaustedError,
    ConfirmationRequiredError,
    DuplicateBookError,
    IngestionError,
    IngestionService,
    ProviderPausedError,
    provider_error_details,
)
from app.services import knowledge_db
from tests.conftest import MockEmbeddingProvider, install_fake_db
from tests.sample_data import ORGANON_SAMPLE, REPERTORY_SAMPLE


@pytest.fixture()
def fake_db(monkeypatch: pytest.MonkeyPatch):
    return install_fake_db(monkeypatch)


@pytest.fixture()
def embedder() -> MockEmbeddingProvider:
    return MockEmbeddingProvider()


@pytest.fixture()
def service(fake_db, embedder) -> IngestionService:
    return IngestionService(db=object(), embedder=embedder)


def register(
    service: IngestionService, text: str = ORGANON_SAMPLE, category: str = "organon"
) -> dict:
    return service.register_book(
        filename="organon.txt",
        data=text.encode("utf-8"),
        category=category,
        title="Organon (sample)",
        author="S. Hahnemann",
    )


def prepared(service: IngestionService, **kwargs) -> dict:
    book = register(service, **kwargs)
    service.prepare_book(book["id"])
    return book


def start(service: IngestionService, book_id: str, **kwargs) -> dict:
    return service.start_ingestion(book_id, confirmed=True, **kwargs)


def run_to_end(service: IngestionService, book_id: str, **kwargs) -> dict:
    job = start(service, book_id, **kwargs)
    service.run_ingestion(job["id"])
    return job


def kinds(fake_db, job_id: str | None = None) -> list[str]:
    return [e["kind"] for e in fake_db.events if job_id is None or e["job_id"] == job_id]


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


def test_register_stores_hash_and_page_separated_text(service: IngestionService, fake_db) -> None:
    source = ORGANON_SAMPLE + "\fSecond source page."
    book = register(service, source)
    assert book["content_hash"] == hashlib.sha256(source.encode()).hexdigest()
    assert fake_db.books[book["id"]]["raw_text"] == source
    assert book["chunk_count"] == 0


def test_register_rejects_duplicate_content(service: IngestionService) -> None:
    book = register(service)
    with pytest.raises(DuplicateBookError) as excinfo:
        register(service)
    assert excinfo.value.book_id == book["id"]


def test_register_rejects_bad_category(service: IngestionService) -> None:
    with pytest.raises(ValueError, match="category"):
        service.register_book(filename="x.txt", data=b"x", category="novel", title="X")


def test_register_rejects_unreadable_file(service: IngestionService) -> None:
    with pytest.raises(ExtractionError):
        service.register_book(
            filename="broken.pdf", data=b"%PDF junk", category="organon", title="Broken"
        )


def test_a_renamed_non_pdf_is_rejected_before_the_pdf_parser(service: IngestionService) -> None:
    with pytest.raises(ExtractionError, match="not a PDF"):
        service.register_book(
            filename="book.pdf", data=b"MZ\x90\x00 executable", category="organon", title="x"
        )


def test_a_binary_file_renamed_to_txt_is_rejected(service: IngestionService) -> None:
    with pytest.raises(ExtractionError, match="binary"):
        service.register_book(
            filename="book.txt", data=b"text\x00more", category="organon", title="x"
        )


def test_registering_never_calls_the_provider(service: IngestionService, embedder) -> None:
    register(service)
    assert embedder.document_calls == [] and embedder.query_calls == []


# ---------------------------------------------------------------------------
# Preparing (free) and inspecting
# ---------------------------------------------------------------------------


def test_prepare_splits_the_text_without_calling_the_provider(
    service: IngestionService, fake_db, embedder
) -> None:
    book = register(service)
    stats = service.prepare_book(book["id"])
    assert stats["prepared"] and stats["total_chunks"] > 0
    assert stats["embedded_chunks"] == 0 and stats["pending_chunks"] == stats["total_chunks"]
    assert stats["pending_tokens"] > 0 and not stats["complete"]
    assert embedder.document_calls == [] and embedder.query_calls == []
    assert "prepared" in kinds(fake_db)


def test_prepare_is_repeatable_and_never_duplicates_chunks(
    service: IngestionService, fake_db
) -> None:
    book = register(service)
    first = service.prepare_book(book["id"])
    second = service.prepare_book(book["id"])
    assert first["total_chunks"] == second["total_chunks"] == len(fake_db.chunks)


def test_prepared_chunks_carry_their_pdf_page_numbers(service: IngestionService, fake_db) -> None:
    book = register(service, ORGANON_SAMPLE + "\fAphorism text on the second page.")
    service.prepare_book(book["id"])
    pages = [c["metadata"].get("page_start") for c in fake_db.chunks.values()]
    assert pages and all(isinstance(p, int) and p >= 1 for p in pages)
    assert max(pages) >= 1


def test_general_books_can_be_prepared(service: IngestionService, fake_db) -> None:
    text = "First paragraph about homeopathy.\n\nSecond paragraph.\n\f" + "Third page text."
    book = register(service, text, category="general")
    stats = service.prepare_book(book["id"])
    assert stats["total_chunks"] >= 1 and stats["category"] == "general"


def test_prepare_refuses_command_line_books_and_running_jobs(
    service: IngestionService, fake_db
) -> None:
    frozen = register(service)
    fake_db.books[frozen["id"]]["metadata"]["plan_hash"] = "abc"
    with pytest.raises(IngestionError, match="command-line pipeline"):
        service.prepare_book(frozen["id"])

    other = register(service, ORGANON_SAMPLE + "\f2", "organon")
    service.prepare_book(other["id"])
    start(service, other["id"])
    with pytest.raises(IngestionError, match="job is running"):
        service.prepare_book(other["id"])


def test_chunk_and_text_inspection(service: IngestionService, fake_db) -> None:
    book = prepared(service, text=ORGANON_SAMPLE + "\fSecond page of text.")
    page = service.chunk_page(book["id"], offset=0, limit=2, query=None, embedded=None)
    assert page["total"] >= 2 and len(page["items"]) == 2
    first = page["items"][0]
    assert first["embedded"] is False and first["page_start"] >= 1 and first["content"]
    assert (
        service.chunk_page(book["id"], offset=0, limit=5, query=None, embedded=True)["total"] == 0
    )
    hits = service.chunk_page(
        book["id"], offset=0, limit=5, query="restore the sick", embedded=None
    )
    assert hits["total"] >= 1

    text = service.text_preview(book["id"], offset=0, limit=1)
    assert text["total_pages"] == 2 and text["pages"][0]["page"] == 1
    assert text["pages"][0]["chars"] > 0


# ---------------------------------------------------------------------------
# Confirmed spending: nothing is sent without it
# ---------------------------------------------------------------------------


def test_nothing_starts_without_confirmation(service: IngestionService, fake_db, embedder) -> None:
    book = prepared(service)
    with pytest.raises(ConfirmationRequiredError):
        service.start_ingestion(book["id"])
    with pytest.raises(ConfirmationRequiredError):
        service.start_ingestion(book["id"], confirmed=False)
    assert fake_db.jobs == {} and embedder.document_calls == []


def test_an_unprepared_book_cannot_be_started(service: IngestionService) -> None:
    book = register(service)
    with pytest.raises(IngestionError, match="Prepare the book first"):
        start(service, book["id"])


def test_start_ingestion_unknown_book(service: IngestionService) -> None:
    with pytest.raises(BookNotFoundError):
        start(service, "no-such-book")


def test_command_line_books_cannot_be_started_here(service: IngestionService, fake_db) -> None:
    book = prepared(service)
    fake_db.books[book["id"]]["metadata"]["plan_hash"] = "abc"
    with pytest.raises(IngestionError, match="command-line pipeline"):
        start(service, book["id"])


def test_the_plan_shows_what_will_be_spent_and_what_blocks_it(
    service: IngestionService, fake_db
) -> None:
    book = register(service)
    blocked = service.plan(book["id"])
    assert not blocked["can_start"] and "Prepare the book first" in blocked["blockers"][0]

    service.prepare_book(book["id"])
    plan = service.plan(book["id"])
    assert plan["can_start"] and plan["blockers"] == []
    assert plan["stats"]["pending_tokens"] > 0
    assert plan["limits"]["batch_tokens"] == service.batch_tokens
    # No caps configured: the estimate plus the runner's safety margin.
    assert plan["effective_token_limit"] >= plan["stats"]["pending_tokens"]


def test_the_effective_limit_is_the_smaller_of_job_limit_and_remaining_budget(
    fake_db, embedder
) -> None:
    capped = IngestionService(
        db=object(),
        embedder=embedder,
        max_tokens=5_000,
        budget_tokens=8_000,
        provider_info={"endpoint_host": "api.voyageai.com", "model": "m", "dimension": 1024},
    )
    book = prepared(capped)
    plan = capped.plan(book["id"])
    assert plan["effective_token_limit"] == 5_000
    assert plan["limits"]["endpoint_host"] == "api.voyageai.com"
    # 4,000 tokens already used by earlier jobs leaves 4,000 of the budget.
    fake_db.jobs["earlier"] = {
        "id": "earlier",
        "book_id": "x",
        "status": "completed",
        "embedded_tokens": 4_000,
        "_order": 0,
    }
    assert capped.plan(book["id"])["effective_token_limit"] == 4_000
    job = start(capped, book["id"])
    assert job["token_limit"] == 4_000
    assert start_limit_is_lowered(capped, book["id"], fake_db) == 100


def start_limit_is_lowered(capped: IngestionService, book_id: str, fake_db) -> int:
    for job in list(fake_db.jobs.values()):
        if job.get("book_id") == book_id:
            job["status"] = "completed"
    return start(capped, book_id, max_tokens=100)["token_limit"]


def test_the_plan_reports_a_set_provider_stop(fake_db, embedder) -> None:
    stopped = IngestionService(
        db=object(), embedder=embedder, provider_pause=lambda: "Provider stop is set"
    )
    book = prepared(stopped)
    plan = stopped.plan(book["id"])
    assert not plan["can_start"] and "Provider stop is set" in plan["blockers"]
    assert plan["limits"]["provider_paused"] is True
    with pytest.raises(ProviderPausedError):
        start(stopped, book["id"])
    assert embedder.document_calls == []


# ---------------------------------------------------------------------------
# Running, resuming, never duplicating
# ---------------------------------------------------------------------------


def test_full_ingestion_populates_the_database_and_completes(
    service: IngestionService, fake_db, embedder
) -> None:
    book = prepared(service)
    job = run_to_end(service, book["id"])

    done = fake_db.get_ingestion_job(job["id"])
    assert done["status"] == "completed" and done["stage"] == "completed"
    assert done["total_chunks"] > 0 and done["processed_chunks"] == done["total_chunks"]
    assert done["embedded_tokens"] > 0 and done["finished_at"]
    assert all(c["embedding"] is not None for c in fake_db.chunks.values())
    assert fake_db.sections
    assert {"started", "completed"} <= set(kinds(fake_db, job["id"]))
    assert service.plan(book["id"])["stats"]["complete"] is True


def test_embedding_keeps_the_chunkers_token_count(service: IngestionService, fake_db) -> None:
    """The database function overwrites token_count, so the value must be passed back."""
    book = prepared(service)
    run_to_end(service, book["id"])
    counts = [c["token_count"] for c in fake_db.chunks.values()]
    assert counts and all(isinstance(n, int) and n > 0 for n in counts), counts


def test_a_finished_book_has_nothing_left_to_start(service: IngestionService) -> None:
    book = prepared(service)
    run_to_end(service, book["id"])
    with pytest.raises(IngestionError, match="already embedded"):
        start(service, book["id"])


def test_a_second_active_job_is_rejected(service: IngestionService) -> None:
    book = prepared(service)
    start(service, book["id"])
    with pytest.raises(IngestionError, match="active ingestion job"):
        start(service, book["id"])


def test_requests_are_split_into_token_limited_batches(fake_db, embedder) -> None:
    small = IngestionService(db=object(), embedder=embedder, batch_tokens=60)
    book = prepared(small)
    run_to_end(small, book["id"])
    assert len(embedder.document_calls) > 1
    for call in embedder.document_calls:
        tokens = sum(max(1, len(text) // 4) for text in call)
        assert len(call) == 1 or tokens <= 60


def test_requests_are_paced_to_the_configured_rate(fake_db, embedder) -> None:
    now = [0.0]
    waits: list[float] = []

    def sleep(seconds: float) -> None:
        waits.append(seconds)
        now[0] += seconds

    paced = IngestionService(
        db=object(),
        embedder=embedder,
        batch_tokens=60,
        requests_per_minute=30,
        sleep=sleep,
        clock=lambda: now[0],
    )
    book = prepared(paced)
    run_to_end(paced, book["id"])
    requests = len(embedder.document_calls)
    assert requests > 2
    assert waits == pytest.approx([2.0] * (requests - 1))  # 30 per minute = one every 2 seconds


def test_pausing_stops_after_the_current_batch_and_resuming_finishes_without_repeats(
    fake_db,
) -> None:
    class PausingEmbedder(MockEmbeddingProvider):
        job_id: str | None = None
        service: IngestionService | None = None

        def embed_documents(self, texts):
            result = super().embed_documents(texts)
            if len(self.document_calls) == 1:  # the operator presses Pause during the first batch
                self.service.pause_job(self.job_id)
            return result

    embedder = PausingEmbedder()
    svc = IngestionService(db=object(), embedder=embedder, batch_tokens=60)
    embedder.service = svc
    book = prepared(svc)
    total_chunks = len(fake_db.chunks)

    first = start(svc, book["id"])
    embedder.job_id = first["id"]
    svc.run_ingestion(first["id"])
    paused = fake_db.get_ingestion_job(first["id"])
    assert paused["status"] == "paused" and paused["stop_reason"] == "Paused by the operator"
    embedded = sum(1 for c in fake_db.chunks.values() if c["embedding"] is not None)
    assert 0 < embedded < total_chunks
    assert {"pause_requested", "paused"} <= set(kinds(fake_db, first["id"]))

    second = start(svc, book["id"])
    assert second["resumed_from"] == first["id"]
    svc.run_ingestion(second["id"])
    assert fake_db.get_ingestion_job(second["id"])["status"] == "completed"
    sent = [text for call in embedder.document_calls for text in call]
    assert len(sent) == total_chunks and len(set(sent)) == len(sent)  # each chunk sent exactly once
    assert len(fake_db.chunks) == total_chunks


def test_pause_only_applies_to_active_jobs(service: IngestionService, fake_db) -> None:
    book = prepared(service)
    job = run_to_end(service, book["id"])
    with pytest.raises(IngestionError, match="nothing to pause"):
        service.pause_job(job["id"])
    with pytest.raises(IngestionError, match="not found"):
        service.pause_job("ghost")


def test_a_job_paused_before_it_runs_sends_nothing(
    service: IngestionService, fake_db, embedder
) -> None:
    book = prepared(service)
    job = start(service, book["id"])
    service.pause_job(job["id"])
    service.run_ingestion(job["id"])
    assert fake_db.get_ingestion_job(job["id"])["status"] == "paused"
    assert embedder.document_calls == []


def test_interrupted_ingestion_resumes_without_duplicates(
    service: IngestionService, fake_db, monkeypatch
) -> None:
    book = prepared(service)
    job = start(service, book["id"])

    class FailingEmbedder:
        dimension = 1024

        def embed_documents(self, texts):
            raise RuntimeError("provider outage")

        def embed_query(self, text):
            raise RuntimeError("provider outage")

    monkeypatch.setattr(service, "embedder", FailingEmbedder())
    service.run_ingestion(job["id"])
    failed = fake_db.get_ingestion_job(job["id"])
    assert failed["status"] == "failed" and "RuntimeError" in failed["error"]
    assert any(
        "provider outage" in e["details"].get("provider_message", "") for e in fake_db.events
    )
    chunk_count_after_failure = len(fake_db.chunks)

    monkeypatch.setattr(service, "embedder", MockEmbeddingProvider())
    job2 = start(service, book["id"])
    service.run_ingestion(job2["id"])
    assert fake_db.get_ingestion_job(job2["id"])["status"] == "completed"
    assert len(fake_db.chunks) == chunk_count_after_failure
    assert all(c["embedding"] is not None for c in fake_db.chunks.values())


def test_resume_only_reembeds_unembedded_chunks(
    service: IngestionService, fake_db, monkeypatch
) -> None:
    book = prepared(service)
    run_to_end(service, book["id"])
    total = len(fake_db.chunks)
    first_id = next(iter(fake_db.chunks))
    fake_db.chunks[first_id]["embedding"] = None  # one vector lost

    healthy = MockEmbeddingProvider()
    monkeypatch.setattr(service, "embedder", healthy)
    run_to_end(service, book["id"])
    sent = [text for call in healthy.document_calls for text in call]
    assert len(sent) == 1 and len(fake_db.chunks) == total


# ---------------------------------------------------------------------------
# Limits: the server stops the job, not the browser
# ---------------------------------------------------------------------------


def test_a_job_stops_before_exceeding_its_token_limit(fake_db, embedder) -> None:
    limited = IngestionService(db=object(), embedder=embedder, max_tokens=1)
    book = prepared(limited)
    job = run_to_end(limited, book["id"])
    done = fake_db.get_ingestion_job(job["id"])
    assert done["status"] == "paused" and done["stop_reason"] == "Token limit reached"
    assert "limit_reached" in kinds(fake_db, job["id"])
    assert embedder.document_calls == []  # no paid request was made at all


def test_a_job_can_be_given_a_lower_limit_than_the_server_maximum(fake_db, embedder) -> None:
    roomy = IngestionService(db=object(), embedder=embedder, max_tokens=10_000_000)
    book = prepared(roomy)
    job = run_to_end(roomy, book["id"], max_tokens=1)
    assert fake_db.get_ingestion_job(job["id"])["stop_reason"] == "Token limit reached"
    assert embedder.document_calls == []


def test_a_generous_limit_does_not_block_a_normal_job(fake_db, embedder) -> None:
    roomy = IngestionService(db=object(), embedder=embedder, max_tokens=10_000_000)
    book = prepared(roomy)
    job = run_to_end(roomy, book["id"])
    assert fake_db.get_ingestion_job(job["id"])["status"] == "completed"


def test_the_total_budget_blocks_new_jobs_and_stops_running_ones(fake_db, embedder) -> None:
    capped = IngestionService(db=object(), embedder=embedder, budget_tokens=1)
    book = prepared(capped)
    fake_db.jobs["spent"] = {
        "id": "spent",
        "book_id": "other",
        "status": "completed",
        "embedded_tokens": 1,
        "_order": 0,
    }
    with pytest.raises(BudgetExhaustedError):
        start(capped, book["id"])

    roomy_start = IngestionService(db=object(), embedder=embedder, budget_tokens=10_000_000)
    other = prepared(roomy_start, text=ORGANON_SAMPLE + "\f2")
    job = start(roomy_start, other["id"])
    roomy_start.budget_tokens = 1  # the budget shrinks (or other jobs spend it) while the job waits
    roomy_start.run_ingestion(job["id"])
    done = fake_db.get_ingestion_job(job["id"])
    assert done["status"] == "paused" and "budget" in done["stop_reason"].lower()
    assert embedder.document_calls == []


def test_a_set_provider_stop_pauses_a_running_job(fake_db) -> None:
    class StopAfterFirst(MockEmbeddingProvider):
        stop = False

        def embed_documents(self, texts):
            result = super().embed_documents(texts)
            self.stop = True
            return result

    embedder = StopAfterFirst()
    svc = IngestionService(
        db=object(),
        embedder=embedder,
        batch_tokens=60,
        provider_pause=lambda: "Provider stop is set" if embedder.stop else None,
    )
    book = prepared(svc)
    job = run_to_end(svc, book["id"])
    done = fake_db.get_ingestion_job(job["id"])
    assert done["status"] == "paused" and done["stop_reason"] == "Provider stop is set"
    assert len(embedder.document_calls) == 1  # nothing was sent after the stop appeared
    assert "provider_stop" in kinds(fake_db, job["id"])


# ---------------------------------------------------------------------------
# Provider errors, honest and safe
# ---------------------------------------------------------------------------


class RateLimited(Exception):
    http_status = 429
    headers = {"Retry-After": "30"}


def test_a_provider_429_is_recorded_without_claiming_a_cause_and_without_secrets(
    service: IngestionService, fake_db, monkeypatch
) -> None:
    class Limited:
        dimension = 1024

        def embed_documents(self, texts):
            raise RateLimited("Rate limit for key al-abcdef1234567890XYZ exceeded")

    monkeypatch.setattr(service, "embedder", Limited())
    book = prepared(service)
    job = run_to_end(service, book["id"])
    done = fake_db.get_ingestion_job(job["id"])
    assert done["status"] == "failed" and done["stop_reason"] == "provider_error"
    assert "429" in done["error"] and "nothing was billed" in done["error"]
    event = next(e for e in fake_db.events if e["kind"] == "provider_rate_limited")
    assert event["details"]["http_status"] == 429
    assert event["details"]["retry_after_seconds"] == "30"
    assert event["details"]["error_class"] == "RateLimited"
    everything = str(fake_db.events) + str(fake_db.jobs)
    assert "al-abcdef1234567890XYZ" not in everything and "[redacted]" in everything
    assert all(c["embedding"] is None for c in fake_db.chunks.values())  # nothing half stored


def test_provider_error_details_survive_odd_exceptions() -> None:
    details = provider_error_details(ValueError("plain"))
    assert details["http_status"] is None and details["error_class"] == "ValueError"


def test_a_missed_database_update_stops_the_job_instead_of_looping_and_re_billing(
    service: IngestionService, fake_db, embedder, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(knowledge_db, "apply_chunk_embeddings", lambda _client, items: 0)
    book = prepared(service)
    job = run_to_end(service, book["id"])  # would loop forever without the guard
    done = fake_db.get_ingestion_job(job["id"])
    assert done["status"] == "failed" and "stored 0 of" in done["error"]
    assert len(embedder.document_calls) == 1  # one batch sent, then it stopped
    assert "failed" in kinds(fake_db, job["id"])


# ---------------------------------------------------------------------------
# Crash and restart recovery
# ---------------------------------------------------------------------------


def _old(seconds: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(seconds=seconds)).isoformat()


def test_a_job_that_stopped_reporting_is_marked_interrupted_and_can_be_resumed(
    service: IngestionService, fake_db
) -> None:
    book = prepared(service)
    stuck = start(service, book["id"])
    fake_db.jobs[stuck["id"]].update(status="running", heartbeat_at=_old(STALE_JOB_SECONDS + 60))

    plan = service.plan(book["id"])  # looking at the book recovers stale jobs
    recovered = fake_db.get_ingestion_job(stuck["id"])
    assert recovered["status"] == "failed" and recovered["stop_reason"] == "interrupted"
    assert "Interrupted" in recovered["error"] and "interrupted" in kinds(fake_db, stuck["id"])
    assert plan["can_start"]
    job2 = run_to_end(service, book["id"])
    assert fake_db.get_ingestion_job(job2["id"])["status"] == "completed"


def test_a_job_with_a_recent_heartbeat_is_left_alone(service: IngestionService, fake_db) -> None:
    book = prepared(service)
    live = start(service, book["id"])
    fake_db.jobs[live["id"]].update(status="running", heartbeat_at=_old(10))
    assert service.recover_stale_jobs() == 0
    assert fake_db.get_ingestion_job(live["id"])["status"] == "running"


# ---------------------------------------------------------------------------
# Overview and history
# ---------------------------------------------------------------------------


def test_overview_reports_real_index_counts_and_limits(service: IngestionService, fake_db) -> None:
    done = prepared(service)
    run_to_end(service, done["id"])
    partial = prepared(service, text=ORGANON_SAMPLE + "\fSecond.")
    untouched = register(service, text=REPERTORY_SAMPLE, category="repertory")

    overview = service.overview()
    by_id = {b["book_id"]: b for b in overview["books"]}
    assert by_id[done["id"]]["complete"] is True
    assert by_id[partial["id"]]["prepared"] and not by_id[partial["id"]]["complete"]
    assert (
        by_id[untouched["id"]]["prepared"] is False and by_id[untouched["id"]]["total_chunks"] == 0
    )
    assert overview["limits"]["budget_tokens_used"] > 0
    assert overview["active_jobs"] == []


def test_the_book_history_lists_jobs_and_events_newest_first(
    service: IngestionService, fake_db
) -> None:
    book = prepared(service)
    first = run_to_end(service, book["id"])
    view = service.book_ingestion(book["id"])
    assert view["jobs"][0]["id"] == first["id"]
    assert view["events"][0]["id"] > view["events"][-1]["id"]
    assert view["plan"]["stats"]["complete"] is True


def test_run_ingestion_records_vanished_job(service: IngestionService) -> None:
    service.run_ingestion("ghost-job")  # must not raise


# ---------------------------------------------------------------------------
# Clear book states: running, stalled, paused, error, interrupted, complete
# ---------------------------------------------------------------------------


def _stats(**kw) -> dict:
    base = {"prepared": True, "complete": False, "embedded_chunks": 5}
    return {**base, **kw}


def test_every_book_gets_one_clear_state_and_a_reason() -> None:
    state = IngestionService.index_state
    live = {"status": "running", "heartbeat_at": _old(10)}
    assert state(_stats(), live)["state"] == "running"
    assert state(_stats(), {"status": "pending", "heartbeat_at": None})["state"] == "running"
    stalled = state(_stats(), {"status": "running", "heartbeat_at": _old(400)})
    assert stalled["state"] == "stalled" and "No progress reported" in stalled["detail"]
    paused = state(_stats(), {"status": "paused", "stop_reason": "Token limit reached"})
    assert paused == {"state": "paused", "detail": "Token limit reached", "idle_seconds": None}
    error = state(_stats(), {"status": "failed", "stop_reason": "error", "error": "Boom"})
    assert error["state"] == "error" and error["detail"] == "Boom"
    interrupted = state(_stats(), {"status": "failed", "stop_reason": "interrupted"})
    assert interrupted["state"] == "interrupted"
    assert state(_stats(complete=True), {"status": "failed"})["state"] == "complete"
    assert state(_stats(prepared=False), None)["state"] == "not_prepared"
    assert state(_stats(embedded_chunks=0), None)["state"] == "ready"
    assert state(_stats(), None)["state"] == "partial"


def test_the_error_detail_never_carries_a_key() -> None:
    job = {"status": "failed", "stop_reason": "error", "error": "bad key al-abcdef1234567890XYZ"}
    detail = IngestionService.index_state(_stats(), job)["detail"]
    assert "al-abcdef1234567890XYZ" not in detail and "[redacted]" in detail


def test_a_command_line_job_is_never_marked_interrupted_by_the_stale_check(
    service: IngestionService, fake_db
) -> None:
    book = prepared(service)
    cli_job = fake_db.create_ingestion_job(book["id"])  # no heartbeat, no token limit
    fake_db.jobs[cli_job["id"]].update(
        status="running", created_at=_old(3600), started_at=_old(3600)
    )
    assert service.recover_stale_jobs() == 0
    assert fake_db.get_ingestion_job(cli_job["id"])["status"] == "running"


def test_the_overview_gives_each_book_its_state_and_latest_job(
    service: IngestionService, fake_db
) -> None:
    finished = prepared(service)
    run_to_end(service, finished["id"])
    working = prepared(service, text=ORGANON_SAMPLE + "\fAnother page.")
    job = start(service, working["id"])
    fake_db.jobs[job["id"]].update(status="running", heartbeat_at=_old(5))
    untouched = register(service, text=REPERTORY_SAMPLE, category="repertory")
    by_id = {b["book_id"]: b for b in service.overview()["books"]}
    assert by_id[finished["id"]]["state"] == "complete"
    assert by_id[working["id"]]["state"] == "running"
    assert by_id[working["id"]]["latest_job"]["id"] == job["id"]
    assert by_id[untouched["id"]]["state"] == "not_prepared"


def test_a_queued_book_waits_and_an_old_failure_is_only_context() -> None:
    state = IngestionService.index_state
    failed = {"status": "failed", "stop_reason": "error", "error": "provider outage"}
    queued = state(_stats(), failed, auto_enabled=True)
    assert (
        queued["state"] == "queued" and "Last attempt failed: provider outage" in queued["detail"]
    )
    assert state(_stats(), None, auto_enabled=True) == {
        "state": "queued",
        "detail": None,
        "idle_seconds": None,
    }
    live = state(_stats(), {"status": "running", "heartbeat_at": _old(5)}, auto_enabled=True)
    assert live["state"] == "running"
    assert state(_stats(complete=True), failed, auto_enabled=True)["state"] == "complete"
    assert state(_stats(), failed, auto_enabled=False)["state"] == "error"


def test_a_wrapped_provider_error_names_the_real_cause_without_secrets() -> None:
    class Limited(Exception):
        http_status = 429

    try:
        try:
            raise Limited("slow down key al-abcdef1234567890XYZ")
        except Limited as inner:
            raise RuntimeError("Voyage embedding failed after 5 attempts: Limited") from inner
    except RuntimeError as outer:
        details = provider_error_details(outer)
    assert details["error_class"] == "RuntimeError" and details["http_status"] is None
    assert details["cause_class"] == "Limited" and details["cause_http_status"] == 429
    assert "al-abcdef1234567890XYZ" not in str(details)
