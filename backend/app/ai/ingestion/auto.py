"""Automatic resume: keep embedding the chosen books until they are complete, or stopped.

The operator confirms ONCE for a chosen set of books (the dialog shows the estimated tokens, the
provider and the limits). After that a background worker starts and resumes jobs one at a time,
oldest request first. Every safeguard of a normal job still applies:

- each job stops at its token limit; the next one resumes from the first chunk without a vector;
- the total budget and the provider stop are checked before every job (a set provider stop makes
  the queue wait; a used-up budget switches the automatic mode off with a plain note);
- a book is switched off after repeated failures, with the last error shown;
- the operator can stop one book or all at any time (the running job finishes its current batch);
- pausing a job by hand ends the automatic mode for that book (the operator's intent wins).

The queue lives in the book's own metadata, so it survives a restart. A job that was running
when the server stopped is detected as interrupted and resumed, without counting as a failure.
"""

import logging
import threading
from datetime import datetime, timezone
from typing import Any

from app.ai.ingestion.service import (
    ACTIVE,
    BookNotFoundError,
    BudgetExhaustedError,
    ConfirmationRequiredError,
    IngestionError,
    IngestionService,
    ProviderPausedError,
    _now,
    _parse,
)
from app.services import knowledge_db

logger = logging.getLogger(__name__)

KEY = "auto_resume"
MAX_FAILURES = 3
RETRY_WAIT_SECONDS = 60  # after a failed job: 60 s, 120 s, ... before the next attempt
MAX_BOOKS = 50


def flag_of(book: dict[str, Any]) -> dict[str, Any]:
    return dict((book.get("metadata") or {}).get(KEY) or {})


class AutoResume:
    def __init__(
        self,
        service: IngestionService,
        max_failures: int = MAX_FAILURES,
        retry_wait: int = RETRY_WAIT_SECONDS,
    ) -> None:
        self.service, self.max_failures, self.retry_wait = service, max_failures, retry_wait

    # -- the operator's two actions -----------------------------------------------------

    def enable(self, book_ids: list[str], confirmed: bool) -> dict[str, Any]:
        """Queue the books for automatic resume. Needs the operator's explicit confirmation."""
        if not confirmed:
            raise ConfirmationRequiredError(
                "Automatic resume spends provider tokens. Confirm it in the dialog first."
            )
        if len(set(book_ids)) > MAX_BOOKS:
            raise IngestionError(f"Choose at most {MAX_BOOKS} books at a time.")
        service = self.service
        reason = service.provider_pause()
        if reason:
            raise ProviderPausedError(reason)
        if service.budget_tokens is not None and service.limits()["budget_tokens_remaining"] <= 0:
            raise BudgetExhaustedError("The total embedding token budget is used up.")
        queued, skipped = [], []
        for book_id in dict.fromkeys(book_ids):
            try:
                book = service._book(book_id)
            except BookNotFoundError:
                skipped.append({"book_id": book_id, "reason": "Book not found"})
                continue
            stats = service._stats_for(book)
            problem = (
                "Belongs to the command-line pipeline"
                if stats["frozen_plan"]
                else "Prepare the book first"
                if not stats["prepared"]
                else "Already fully embedded"
                if stats["pending_chunks"] == 0
                else None
            )
            if problem:
                skipped.append({"book_id": book_id, "title": book["title"], "reason": problem})
                continue
            self._write(book, enabled=True, since=_now(), failures=0, note=None)
            queued.append(
                {
                    "book_id": book_id,
                    "title": book["title"],
                    "pending_chunks": stats["pending_chunks"],
                    "pending_tokens": stats["pending_tokens"],
                }
            )
        return {
            "queued": queued,
            "skipped": skipped,
            "total_pending_tokens": sum(q["pending_tokens"] for q in queued),
        }

    def disable(self, book_ids: list[str] | None = None) -> list[str]:
        """Stop automatic resume (for the given books, or all). Running jobs stop safely after
        their current batch and can be resumed later by hand."""
        stopped = []
        for book, _flag in self._queued():
            if book_ids is not None and book["id"] not in book_ids:
                continue
            self._write(book, enabled=False, note="Stopped by the operator")
            for job in knowledge_db.list_ingestion_jobs(
                self.service.db, book_id=book["id"], statuses=ACTIVE, limit=5
            ):
                try:
                    self.service.pause_job(job["id"])
                except IngestionError:
                    pass
            stopped.append(book["id"])
        return stopped

    # -- queue helpers --------------------------------------------------------------------

    def _queued(self) -> list[tuple[dict[str, Any], dict[str, Any]]]:
        rows = [
            (b, flag_of(b))
            for b in knowledge_db.list_books(self.service.db)
            if flag_of(b).get("enabled")
        ]
        return sorted(rows, key=lambda row: row[1].get("since") or "")

    def _write(self, book: dict[str, Any], **changes: Any) -> None:
        flag = {**flag_of(book), **changes}
        knowledge_db.update_book_metadata(self.service.db, book["id"], {KEY: flag})
        book["metadata"] = {**(book.get("metadata") or {}), KEY: flag}

    def _note(self, book: dict[str, Any], note: str) -> None:
        self._write(book, enabled=False, note=note)
        self.service._event(None, book["id"], "info", "auto_resume_off", note)

    # -- one step of the worker ---------------------------------------------------------

    def tick(self) -> str:
        """Do at most one job. Returns what happened (for the worker and the tests)."""
        service = self.service
        service.recover_stale_jobs()
        queued = self._queued()
        if not queued:
            return "idle"
        if service.provider_pause():
            return "waiting_provider_stop"  # the queue stays; the owner clears the stop
        if knowledge_db.list_ingestion_jobs(service.db, statuses=ACTIVE, limit=1):
            return "busy"
        if service.budget_tokens is not None and (service.limits()["budget_tokens_remaining"] <= 0):
            for book, _ in queued:
                self._note(book, "Stopped: the total embedding token budget is used up")
            return "budget_exhausted"
        for book, flag in queued:
            stats = service._stats_for(book)
            if stats["frozen_plan"]:
                self._note(book, "Stopped: this book belongs to the command-line pipeline")
                continue
            if stats["pending_chunks"] == 0:
                self._note(book, "Finished: every chunk has a vector")
                continue
            failures = int(flag.get("failures") or 0)
            last = next(
                iter(knowledge_db.list_ingestion_jobs(service.db, book_id=book["id"], limit=1)),
                None,
            )
            if failures >= self.max_failures:
                detail = (last or {}).get("error") or "unknown error"
                self._note(
                    book,
                    f"Stopped after {failures} failed attempts. Last error: {str(detail)[:160]}",
                )
                continue
            if failures and last and last.get("status") == "failed":
                finished = _parse(last.get("finished_at"))
                wait = self.retry_wait * failures
                if finished and (datetime.now(timezone.utc) - finished).total_seconds() < wait:
                    continue  # back off before trying again
            try:
                job = service.start_ingestion(book["id"], confirmed=True)
            except (BudgetExhaustedError, ProviderPausedError):
                return "waiting"
            except IngestionError as exc:
                self._write(book, failures=failures + 1, note=str(exc)[:200])
                continue
            service.run_ingestion(job["id"])
            self._after(book, flag, job["id"])
            return "ran"
        return "idle"

    def _after(self, book: dict[str, Any], flag: dict[str, Any], job_id: str) -> None:
        job = knowledge_db.get_ingestion_job(self.service.db, job_id) or {}
        status, reason = job.get("status"), job.get("stop_reason")
        if status == "failed":
            self._write(
                book,
                failures=int(flag.get("failures") or 0) + 1,
                note=str(job.get("error") or "The job failed")[:200],
            )
        elif status == "paused" and reason == "Paused by the operator":
            self._note(book, "Stopped by the operator")
        else:  # completed, or paused at a limit/provider stop: carry on next time
            self._write(book, failures=0, note=None)


class AutoResumeWorker(threading.Thread):
    """Runs `AutoResume.tick` in a loop inside the API process."""

    def __init__(self, auto: AutoResume, interval: float = 10.0) -> None:
        super().__init__(name="auto-resume", daemon=True)
        self.auto, self.interval = auto, interval
        self.stop_event = threading.Event()

    def run(self) -> None:
        while not self.stop_event.is_set():
            action = "idle"
            try:
                action = self.auto.tick()
            except Exception:  # never let the loop die; the error is in the log
                logger.exception("Automatic resume step failed")
            self.stop_event.wait(1.0 if action == "ran" else self.interval)

    def stop(self) -> None:
        self.stop_event.set()
