"""Automatic resume: one confirmation, one job at a time, every limit and stop still applies."""

# ruff: noqa: F811
import pytest

from app.ai.ingestion.auto import AutoResume, flag_of
from app.ai.ingestion.service import (
    BudgetExhaustedError,
    ConfirmationRequiredError,
    IngestionService,
    ProviderPausedError,
)
from tests.conftest import MockEmbeddingProvider
from tests.sample_data import ORGANON_SAMPLE
from tests.test_ingestion_service import (  # noqa: F401
    embedder,
    fake_db,
    prepared,
    register,
    service,
)


def second_book(service: IngestionService) -> dict:
    return prepared(service, text=ORGANON_SAMPLE + "\fSecond book page.")


def drain(auto: AutoResume, limit: int = 30) -> list[str]:
    actions = []
    for _ in range(limit):
        action = auto.tick()
        actions.append(action)
        if action == "idle":
            break
    return actions


def test_nothing_is_queued_without_confirmation(service: IngestionService, fake_db) -> None:
    book = prepared(service)
    auto = AutoResume(service)
    with pytest.raises(ConfirmationRequiredError):
        auto.enable([book["id"]], confirmed=False)
    assert not flag_of(fake_db.books[book["id"]]).get("enabled") and fake_db.jobs == {}


def test_enabling_reports_the_total_and_skips_books_that_cannot_run(
    service: IngestionService, fake_db
) -> None:
    ready = prepared(service)
    unprepared = register(service, text=ORGANON_SAMPLE + "\fx", category="organon")
    cli = second_book(service)
    fake_db.books[cli["id"]]["metadata"]["plan_hash"] = "abc"
    auto = AutoResume(service)
    result = auto.enable([ready["id"], unprepared["id"], cli["id"], "ghost"], confirmed=True)
    assert [q["book_id"] for q in result["queued"]] == [ready["id"]]
    assert result["total_pending_tokens"] > 0
    reasons = {s["book_id"]: s["reason"] for s in result["skipped"]}
    assert "Prepare the book first" in reasons[unprepared["id"]]
    assert "command-line" in reasons[cli["id"]] and reasons["ghost"] == "Book not found"


def test_the_queue_runs_the_books_one_at_a_time_until_everything_is_embedded(
    service: IngestionService, fake_db, embedder
) -> None:
    first, second = prepared(service), second_book(service)
    auto = AutoResume(service)
    auto.enable([first["id"], second["id"]], confirmed=True)
    actions = drain(auto)
    assert actions.count("ran") == 2 and actions[-1] == "idle"
    assert all(c["embedding"] is not None for c in fake_db.chunks.values())
    for book in (first, second):
        flag = flag_of(fake_db.books[book["id"]])
        assert flag["enabled"] is False and "Finished" in flag["note"]
    sent = [t for call in embedder.document_calls for t in call]
    assert len(sent) == len(fake_db.chunks)  # every chunk sent exactly once


def test_a_job_that_stops_at_its_token_limit_is_resumed_automatically(fake_db, embedder) -> None:
    capped = IngestionService(db=object(), embedder=embedder, max_tokens=300, batch_tokens=100)
    book = prepared(capped)
    auto = AutoResume(capped)
    auto.enable([book["id"]], confirmed=True)
    actions = drain(auto, 60)
    jobs = [j for j in fake_db.jobs.values() if j["book_id"] == book["id"]]
    assert len(jobs) >= 2 and actions.count("ran") == len(jobs)
    assert any(j["status"] == "paused" for j in jobs)  # stopped at the limit, then resumed
    assert all(c["embedding"] is not None for c in fake_db.chunks.values())


def test_only_one_job_runs_at_a_time(service: IngestionService, fake_db) -> None:
    book = prepared(service)
    other = second_book(service)
    auto = AutoResume(service)
    auto.enable([book["id"]], confirmed=True)
    running = service.start_ingestion(other["id"], confirmed=True)  # started by hand, still active
    assert auto.tick() == "busy"
    fake_db.jobs[running["id"]]["status"] = "completed"
    assert auto.tick() == "ran"


def test_a_set_provider_stop_makes_the_queue_wait_and_keeps_it(fake_db, embedder) -> None:
    stop = {"reason": None}
    held = IngestionService(db=object(), embedder=embedder, provider_pause=lambda: stop["reason"])
    book = prepared(held)
    auto = AutoResume(held)
    auto.enable([book["id"]], confirmed=True)
    stop["reason"] = "Provider stop is set"
    assert auto.tick() == "waiting_provider_stop"
    assert embedder.document_calls == [] and flag_of(fake_db.books[book["id"]])["enabled"]
    stop["reason"] = None  # the owner cleared it
    assert drain(auto)[0] == "ran"
    with pytest.raises(ProviderPausedError):
        stop["reason"] = "again"
        auto.enable([book["id"]], confirmed=True)


def test_a_used_up_budget_switches_the_queue_off_with_a_note(fake_db, embedder) -> None:
    capped = IngestionService(db=object(), embedder=embedder, budget_tokens=10_000_000)
    book = prepared(capped)
    auto = AutoResume(capped)
    auto.enable([book["id"]], confirmed=True)
    capped.budget_tokens = 1
    fake_db.jobs["spent"] = {
        "id": "spent",
        "book_id": "x",
        "status": "completed",
        "embedded_tokens": 5,
        "_order": 0,
    }
    assert auto.tick() == "budget_exhausted"
    flag = flag_of(fake_db.books[book["id"]])
    assert flag["enabled"] is False and "budget" in flag["note"]
    with pytest.raises(BudgetExhaustedError):
        auto.enable([book["id"]], confirmed=True)


def test_repeated_failures_stop_the_book_and_show_the_last_error(
    service: IngestionService, fake_db, monkeypatch
) -> None:
    class Failing:
        dimension = 1024

        def embed_documents(self, texts):
            raise RuntimeError("provider outage")

    monkeypatch.setattr(service, "embedder", Failing())
    book = prepared(service)
    auto = AutoResume(service, max_failures=3, retry_wait=0)
    auto.enable([book["id"]], confirmed=True)
    actions = drain(auto, 20)
    assert actions.count("ran") == 3
    flag = flag_of(fake_db.books[book["id"]])
    assert flag["enabled"] is False and "Stopped after 3 failed attempts" in flag["note"]


def test_a_failure_is_retried_after_a_wait_not_at_once(
    service: IngestionService, fake_db, monkeypatch
) -> None:
    class Failing:
        dimension = 1024

        def embed_documents(self, texts):
            raise RuntimeError("outage")

    monkeypatch.setattr(service, "embedder", Failing())
    book = prepared(service)
    auto = AutoResume(service, max_failures=3, retry_wait=3600)
    auto.enable([book["id"]], confirmed=True)
    assert auto.tick() == "ran"  # first try fails
    assert auto.tick() == "idle"  # backing off for an hour: no second job yet
    assert len([j for j in fake_db.jobs.values() if j["book_id"] == book["id"]]) == 1


def test_stopping_ends_the_automatic_mode_and_asks_a_running_job_to_pause(
    service: IngestionService, fake_db
) -> None:
    book, other = prepared(service), second_book(service)
    auto = AutoResume(service)
    auto.enable([book["id"], other["id"]], confirmed=True)
    running = service.start_ingestion(book["id"], confirmed=True)
    assert auto.disable([book["id"]]) == [book["id"]]
    assert fake_db.jobs[running["id"]]["pause_requested"] is True
    assert not flag_of(fake_db.books[book["id"]])["enabled"]
    assert flag_of(fake_db.books[other["id"]])["enabled"]  # untouched
    assert auto.disable() == [other["id"]]  # everything
    assert flag_of(fake_db.books[other["id"]])["note"] == "Stopped by the operator"


def test_pausing_a_job_by_hand_ends_the_automatic_mode_for_that_book(
    fake_db,
) -> None:
    class PausingEmbedder(MockEmbeddingProvider):
        service: IngestionService | None = None
        job_id: str | None = None

        def embed_documents(self, texts):
            result = super().embed_documents(texts)
            self.service.pause_job(self.job_id)  # the operator presses Pause on the job
            return result

    emb = PausingEmbedder()
    svc = IngestionService(db=object(), embedder=emb, batch_tokens=60)
    emb.service = svc
    book = prepared(svc)
    auto = AutoResume(svc)
    auto.enable([book["id"]], confirmed=True)
    original = svc.start_ingestion

    def start(book_id, **kw):
        job = original(book_id, **kw)
        emb.job_id = job["id"]
        return job

    svc.start_ingestion = start  # type: ignore[method-assign]
    assert auto.tick() == "ran"
    flag = flag_of(fake_db.books[book["id"]])
    assert flag["enabled"] is False and flag["note"] == "Stopped by the operator"
    assert auto.tick() == "idle"


def test_a_restart_in_the_middle_is_resumed_without_counting_as_a_failure(
    service: IngestionService, fake_db
) -> None:
    from tests.test_ingestion_service import _old

    book = prepared(service)
    auto = AutoResume(service)
    auto.enable([book["id"]], confirmed=True)
    stuck = service.start_ingestion(book["id"], confirmed=True)
    fake_db.jobs[stuck["id"]].update(status="running", heartbeat_at=_old(3600))
    assert auto.tick() == "ran"  # stale job recovered as interrupted, then a fresh one runs
    assert flag_of(fake_db.books[book["id"]]).get("failures", 0) == 0
    assert all(c["embedding"] is not None for c in fake_db.chunks.values())


def test_the_overview_shows_the_queue_position_and_note(service: IngestionService, fake_db) -> None:
    a, b = prepared(service), second_book(service)
    AutoResume(service).enable([a["id"], b["id"]], confirmed=True)
    by_id = {x["book_id"]: x for x in service.overview()["books"]}
    assert (
        by_id[a["id"]]["auto_resume"]["enabled"] and by_id[a["id"]]["auto_resume"]["position"] == 1
    )
    assert by_id[b["id"]]["auto_resume"]["position"] == 2
