"""Document ingestion for books uploaded through the website: register, prepare, embed, control.

Money safety is enforced HERE, on the server, not in the browser:
  - nothing is sent to the paid embedding provider unless the caller confirmed it;
  - a job stops by itself before it would pass its token limit or the total token budget;
  - requests are token-limited per batch and paced to a requests-per-minute rate;
  - the owner's provider stop (set after a provider error) blocks starting and stops running jobs;
  - an update that the database did not store stops the job instead of re-sending
    (re-billing) the batch.

Resume model: chunking is deterministic for identical source bytes and chunks are stored with
ignore-duplicates on (book_id, chunk_index). A vector is stored on the chunk row itself, so "embed
what still has no vector" is the one and only resume point: finished work is never repeated, never
duplicated and never billed twice. Pause, a reached limit, a provider error, a crash and
a restart all
leave the job resumable by simply starting the next job.
"""

import hashlib
import logging
import math
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from app.ai.ingestion.chunking import MAX_CHUNK_CHARS, chunk_document
from app.ai.ingestion.cleaning import clean_pages
from app.ai.ingestion.extraction import PAGE_SEPARATOR, ExtractionError, PageText, extract_document
from app.ai.rag import guard
from app.services import knowledge_db
from app.services.embeddings import EmbeddingProvider

logger = logging.getLogger(__name__)

CATEGORIES = ("materia_medica", "repertory", "organon", "general")
ACTIVE = ("pending", "running")
STALE_JOB_SECONDS = 300  # a running job with no heartbeat for this long is treated as interrupted
SAFETY_MARGIN = 1.25  # the ~4 characters per token estimate can run low; stop a little early
PROGRESS_EVENT_EVERY = 10  # batches between "progress" history entries
PAGE_PREVIEW_CHARS = 2000
_KEY_LIKE = re.compile(r"\b(?:al|pa|sk)-[A-Za-z0-9_\-]{10,}")
FROZEN_PLAN_MESSAGE = (
    "This book belongs to the command-line pipeline (frozen plan and token ledger). "
    "Resume it there: python -m app.ai.ingestion --live from the backend directory."
)


class BookNotFoundError(LookupError):
    """No book with that id exists."""


class DuplicateBookError(ValueError):
    """A book with identical source bytes is already registered."""

    def __init__(self, message: str, book_id: str) -> None:
        super().__init__(message)
        self.book_id = book_id


class IngestionError(RuntimeError):
    """Ingestion could not be started or run."""


class ConfirmationRequiredError(IngestionError):
    """Spending provider tokens needs an explicit confirmation."""


class BudgetExhaustedError(IngestionError):
    """The total embedding token budget is used up."""


class ProviderPausedError(IngestionError):
    """The owner's provider stop is set."""


class TokenLimitReachedError(IngestionError):
    """Kept for callers that raise it directly; a running job now stops with status 'paused'."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _estimate(row: dict[str, Any]) -> int:
    return int(row.get("token_count") or max(1, len(row.get("content", "")) // 4))


def _safe_text(value: Any, limit: int = 300) -> str:
    """Error text with anything key-shaped removed, shortened for the history."""
    return _KEY_LIKE.sub("[redacted]", str(value))[:limit]


def provider_error_details(exc: Exception) -> dict[str, Any]:
    """What is safe and useful to keep about a provider failure (never keys or request bodies)."""
    status = getattr(exc, "http_status", None) or getattr(exc, "status_code", None)
    headers = getattr(exc, "headers", None) or {}
    retry_after = None
    try:
        retry_after = headers.get("Retry-After") or headers.get("retry-after")
    except AttributeError:
        pass
    return {
        "error_class": type(exc).__name__,
        "http_status": status,
        "retry_after_seconds": retry_after,
        "message": _safe_text(exc),
    }


@dataclass
class IngestionService:
    """Operations over a Supabase client and an embedding provider."""

    db: Any
    embedder: EmbeddingProvider
    # Most tokens ONE job may send to the provider (None = unlimited).
    max_tokens: int | None = None
    # Most tokens ALL website jobs together may send (None = unlimited).
    budget_tokens: int | None = None
    batch_tokens: int = 3_000
    requests_per_minute: int = 0  # 0 = not paced
    # Returns a reason while the owner's provider stop is set, otherwise None.
    provider_pause: Callable[[], str | None] = lambda: None
    provider_info: dict[str, Any] = field(
        default_factory=lambda: {
            "endpoint_host": "not configured",
            "model": "unknown",
            "dimension": 1024,
        }
    )
    sleep: Callable[[float], None] = time.sleep
    clock: Callable[[], float] = time.monotonic

    # -- registration -------------------------------------------------------

    def register_book(
        self,
        *,
        filename: str,
        data: bytes,
        category: str,
        title: str,
        author: str | None = None,
        publisher: str | None = None,
        publication_year: int | None = None,
        language: str = "en",
        source_uri: str | None = None,
    ) -> dict[str, Any]:
        """Validate, extract and store a book; refuses duplicates. Calls no provider."""
        if category not in CATEGORIES:
            raise ValueError(f"category must be one of {CATEGORIES}")
        if not data:
            raise ExtractionError("Uploaded file is empty")
        content_hash = hashlib.sha256(data).hexdigest()
        existing = knowledge_db.find_book_by_content_hash(self.db, content_hash)
        if existing:
            raise DuplicateBookError(
                f"Book already registered as '{existing['title']}' ({existing['id']})",
                book_id=existing["id"],
            )
        extracted = extract_document(data, filename)
        return knowledge_db.create_book(
            self.db,
            {
                "category": category,
                "title": title.strip(),
                "author": author,
                "publisher": publisher,
                "publication_year": publication_year,
                "language": language,
                "source_filename": filename,
                "source_uri": source_uri,
                "content_hash": content_hash,
                # \f-separated pages preserve page metadata for chunkers.
                "raw_text": extracted.text,
                "metadata": {
                    "pdf_bytes": len(data),
                    "text_bytes": len(extracted.text.encode("utf-8")),
                    "total_pages": len(extracted.pages),
                    "category_reviewed_at_registration": True,
                },
            },
        )

    # -- reading -------------------------------------------------------------

    def _book(self, book_id: str, include_text: bool = False) -> dict[str, Any]:
        book = knowledge_db.get_book(self.db, book_id, include_text=include_text)
        if book is None:
            raise BookNotFoundError(f"Book {book_id} not found")
        return book

    def _set_provider_stop(self) -> None:
        """After a provider 429 hold every paid call, on every server, until the owner clears it."""
        try:
            knowledge_db.set_system_flag(
                self.db,
                "provider_pause",
                paused=True,
                reason="The embedding provider answered HTTP 429. Check the provider account, "
                "then clear the flag (docs/production-runbook.md).",
                by="web-ingestion",
            )
        except knowledge_db.KnowledgeDBError:
            logger.error("Could not save the provider stop flag after an HTTP 429")
        guard.reset_cache()

    def _event(
        self, job_id: str | None, book_id: str, level: str, kind: str, message: str, **details: Any
    ) -> None:
        try:
            knowledge_db.add_ingestion_event(
                self.db,
                job_id=job_id,
                book_id=book_id,
                level=level,
                kind=kind,
                message=message,
                details=details,
            )
        except knowledge_db.KnowledgeDBError:
            logger.warning(
                "Could not record ingestion event %s", kind
            )  # history must never stop a job

    def limits(self) -> dict[str, Any]:
        used = knowledge_db.budget_tokens_used(self.db)
        budget = self.budget_tokens
        reason = self.provider_pause()
        return {
            **self.provider_info,
            "per_job_token_limit": self.max_tokens if self.max_tokens is not None else 0,
            "budget_token_limit": budget if budget is not None else 0,
            "budget_tokens_used": used,
            "budget_tokens_remaining": max(0, budget - used) if budget is not None else 0,
            "batch_tokens": self.batch_tokens,
            "requests_per_minute": self.requests_per_minute,
            "provider_paused": reason is not None,
            "provider_pause_reason": reason,
        }

    def book_stats(
        self, book: dict[str, Any], stats: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        row = stats or {}
        total = int(row.get("total_chunks") or 0)
        embedded = int(row.get("embedded_chunks") or 0)
        metadata = book.get("metadata") or {}
        return {
            "book_id": book["id"],
            "title": book["title"],
            "category": book["category"],
            "source_filename": book.get("source_filename", ""),
            "total_pages": metadata.get("total_pages"),
            "total_chunks": total,
            "embedded_chunks": embedded,
            "pending_chunks": total - embedded,
            "embedded_tokens": int(row.get("embedded_tokens") or 0),
            "pending_tokens": int(row.get("pending_tokens") or 0),
            "prepared": total > 0,
            "complete": total > 0 and embedded == total,
            "frozen_plan": bool(metadata.get("plan_hash")),
        }

    def _stats_for(self, book: dict[str, Any]) -> dict[str, Any]:
        rows = {r["book_id"]: r for r in knowledge_db.book_stats(self.db)}
        return self.book_stats(book, rows.get(book["id"]))

    def overview(self) -> dict[str, Any]:
        self.recover_stale_jobs()
        rows = {r["book_id"]: r for r in knowledge_db.book_stats(self.db)}
        books = [self.book_stats(b, rows.get(b["id"])) for b in knowledge_db.list_books(self.db)]
        active = knowledge_db.list_ingestion_jobs(self.db, statuses=ACTIVE, limit=50)
        return {"limits": self.limits(), "books": books, "active_jobs": active}

    def plan(self, book_id: str) -> dict[str, Any]:
        """What starting (or resuming) embedding for this book would do, and what blocks it."""
        self.recover_stale_jobs(book_id)
        book = self._book(book_id)
        stats = self._stats_for(book)
        limits = self.limits()
        jobs = knowledge_db.list_ingestion_jobs(self.db, book_id=book_id, limit=10)
        active = next((j for j in jobs if j["status"] in ACTIVE), None)
        remaining = limits["budget_tokens_remaining"] if self.budget_tokens is not None else None
        caps = [c for c in (self.max_tokens, remaining) if c is not None]
        # With no configured cap the job may use the estimate plus the same safety margin the
        # runner applies before each batch, so the estimate itself never blocks the last batch.
        effective = min(caps) if caps else math.ceil(stats["pending_tokens"] * SAFETY_MARGIN)

        blockers: list[str] = []
        if stats["frozen_plan"]:
            blockers.append(FROZEN_PLAN_MESSAGE)
        elif not stats["prepared"]:
            blockers.append(
                "Prepare the book first: it must be split into chunks (free, no provider call)."
            )
        elif stats["pending_chunks"] == 0:
            blockers.append("All chunks are already embedded.")
        if limits["provider_paused"]:
            blockers.append(
                limits["provider_pause_reason"] or "The embedding provider stop is set."
            )
        if self.budget_tokens is not None and remaining == 0:
            blockers.append("The total embedding token budget is used up.")
        if active:
            blockers.append("A job is already running for this book.")
        return {
            "stats": stats,
            "limits": limits,
            "effective_token_limit": effective,
            "can_start": not blockers,
            "blockers": blockers,
            "active_job": active,
            "latest_job": jobs[0] if jobs else None,
        }

    def book_ingestion(self, book_id: str) -> dict[str, Any]:
        return {
            "plan": self.plan(book_id),
            "jobs": knowledge_db.list_ingestion_jobs(self.db, book_id=book_id, limit=10),
            "events": knowledge_db.list_ingestion_events(self.db, book_id=book_id, limit=50),
        }

    # -- inspecting text and chunks ---------------------------------------------

    def chunk_page(
        self, book_id: str, *, offset: int, limit: int, query: str | None, embedded: bool | None
    ) -> dict[str, Any]:
        self._book(book_id)
        rows = knowledge_db.list_chunks(
            self.db, book_id, offset=offset, limit=limit, query=query, embedded=embedded
        )
        items = [
            {
                "id": r["id"],
                "chunk_index": r["chunk_index"],
                "content": r["content"],
                "token_count": r.get("token_count"),
                "embedded": bool(r.get("embedded")),
                "page_start": (r.get("metadata") or {}).get("page_start"),
                "page_end": (r.get("metadata") or {}).get("page_end"),
                "section_heading": r.get("section_heading"),
                "section_path": r.get("section_path") or [],
            }
            for r in rows
        ]
        total = int(rows[0]["total"]) if rows else 0
        return {"total": total, "offset": offset, "limit": limit, "items": items}

    def text_preview(self, book_id: str, *, offset: int, limit: int) -> dict[str, Any]:
        book = self._book(book_id, include_text=True)
        pages = (book.get("raw_text") or "").split(PAGE_SEPARATOR)
        window = pages[offset : offset + limit]
        return {
            "total_pages": len(pages),
            "offset": offset,
            "limit": limit,
            "pages": [
                {
                    "page": offset + i + 1,
                    "chars": len(text),
                    "text": text[:PAGE_PREVIEW_CHARS],
                    "truncated": len(text) > PAGE_PREVIEW_CHARS,
                }
                for i, text in enumerate(window)
            ],
        }

    # -- preparing (free) -------------------------------------------------------

    def prepare_book(self, book_id: str) -> dict[str, Any]:
        """Clean the extracted text and split it into chunks. Free, repeatable, no provider call."""
        book = self._book(book_id, include_text=True)
        if (book.get("metadata") or {}).get("plan_hash"):
            raise IngestionError(FROZEN_PLAN_MESSAGE)
        if knowledge_db.list_ingestion_jobs(self.db, book_id=book_id, statuses=ACTIVE, limit=1):
            raise IngestionError("A job is running for this book. Pause it before preparing again.")

        pages = book["raw_text"].split(PAGE_SEPARATOR)
        cleaned = clean_pages([PageText(page=i + 1, text=t) for i, t in enumerate(pages)])
        result = chunk_document(cleaned, book["category"])

        section_rows = [
            {
                "book_id": book["id"],
                "ordinal": s.ordinal,
                "heading": s.heading,
                "section_type": s.section_type,
                "path": s.path,
                "page_start": s.page_start,
                "page_end": s.page_end,
                "metadata": s.metadata,
            }
            for s in result.sections
        ]
        stored = knowledge_db.upsert_sections(self.db, section_rows) if section_rows else []
        ordinal_to_id = {row["ordinal"]: row["id"] for row in stored}
        chunk_rows = [
            {
                "book_id": book["id"],
                "section_id": ordinal_to_id.get(c.section_ordinal),
                "chunk_index": c.chunk_index,
                "content": c.content,
                "content_hash": c.content_hash,
                "token_count": c.token_estimate,
                # PDF page numbers travel with the chunk so citations can name the page.
                "metadata": {**c.metadata, "page_start": c.page_start, "page_end": c.page_end},
            }
            for c in result.chunks
        ]
        knowledge_db.upsert_chunks(self.db, chunk_rows)
        knowledge_db.update_book_counts(
            self.db, book["id"], section_count=len(result.sections), chunk_count=len(chunk_rows)
        )
        self._event(
            None,
            book_id,
            "info",
            "prepared",
            f"Split into {len(chunk_rows)} chunks",
            chunks=len(chunk_rows),
            sections=len(result.sections),
        )
        return self._stats_for(self._book(book_id))

    # -- jobs ----------------------------------------------------------------------

    def start_ingestion(
        self, book_id: str, *, confirmed: bool = False, max_tokens: int | None = None
    ) -> dict[str, Any]:
        """Create a job that embeds the chunks still missing a vector. Spends provider tokens."""
        if not confirmed:
            raise ConfirmationRequiredError(
                "Confirm the token spend before starting (confirmed must be true)."
            )
        plan = self.plan(book_id)
        stats = plan["stats"]
        if stats["frozen_plan"]:
            raise IngestionError(FROZEN_PLAN_MESSAGE)
        if plan["limits"]["provider_paused"]:
            raise ProviderPausedError(
                plan["limits"]["provider_pause_reason"] or "Provider stop is set"
            )
        if self.budget_tokens is not None and plan["limits"]["budget_tokens_remaining"] == 0:
            raise BudgetExhaustedError("The total embedding token budget is used up.")
        if plan["active_job"]:
            raise IngestionError(f"Book {book_id} already has an active ingestion job")
        if not stats["prepared"]:
            raise IngestionError("Prepare the book first: it must be split into chunks.")
        if stats["pending_chunks"] == 0:
            raise IngestionError("All chunks are already embedded; nothing left to send.")

        limit = plan["effective_token_limit"]
        if max_tokens is not None:
            limit = min(limit, max_tokens)
        latest = plan["latest_job"]
        try:
            job = knowledge_db.create_ingestion_job(
                self.db,
                book_id,
                {
                    "token_limit": limit,
                    "estimated_tokens": stats["pending_tokens"],
                    "total_chunks": stats["pending_chunks"],
                    "heartbeat_at": _now(),
                    "resumed_from": latest["id"] if latest else None,
                },
            )
        except knowledge_db.KnowledgeDBError as exc:
            if "ingestion_jobs_one_active_per_book" in str(exc):
                raise IngestionError(f"Book {book_id} already has an active ingestion job") from exc
            raise
        self._event(
            job["id"],
            book_id,
            "info",
            "started",
            f"Started: {stats['pending_chunks']} chunks, about {stats['pending_tokens']} tokens, "
            f"limit {limit}",
            token_limit=limit,
            estimated_tokens=stats["pending_tokens"],
            pending_chunks=stats["pending_chunks"],
            resumed_from=latest["id"] if latest else None,
        )
        return job

    def pause_job(self, job_id: str) -> dict[str, Any]:
        """Ask a job to stop safely: it finishes its current batch, then stops."""
        job = knowledge_db.get_ingestion_job(self.db, job_id)
        if job is None:
            raise IngestionError(f"Job {job_id} not found")
        if job["status"] not in ACTIVE:
            raise IngestionError(f"The job is {job['status']}; there is nothing to pause.")
        knowledge_db.update_ingestion_job(self.db, job_id, {"pause_requested": True})
        self._event(
            job_id, job["book_id"], "info", "pause_requested", "Pause requested by the operator"
        )
        return knowledge_db.get_ingestion_job(self.db, job_id) or job

    def recover_stale_jobs(self, book_id: str | None = None) -> int:
        """Mark jobs that stopped reporting (crash, restart) as failed so they can be resumed."""
        cutoff = datetime.now(timezone.utc) - timedelta(seconds=STALE_JOB_SECONDS)
        recovered = 0
        for job in knowledge_db.list_ingestion_jobs(
            self.db, book_id=book_id, statuses=ACTIVE, limit=50
        ):
            seen = (
                _parse(job.get("heartbeat_at"))
                or _parse(job.get("started_at"))
                or _parse(job.get("created_at"))
            )
            if seen is not None and seen > cutoff:
                continue
            knowledge_db.update_ingestion_job(
                self.db,
                job["id"],
                {
                    "status": "failed",
                    "stop_reason": "interrupted",
                    "error": "Interrupted: the job stopped reporting (server restarted or "
                    "crashed). Start it again to continue from the last stored chunk.",
                    "finished_at": _now(),
                },
            )
            self._event(
                job["id"],
                job["book_id"],
                "warning",
                "interrupted",
                "The job stopped reporting and was marked interrupted",
            )
            recovered += 1
        return recovered

    def run_ingestion(self, job_id: str) -> None:
        """Run one job to completion, pause, limit or failure. Every outcome is recorded."""
        job = knowledge_db.get_ingestion_job(self.db, job_id)
        if job is None:
            logger.error("Ingestion job %s vanished before start", job_id)
            return
        try:
            self._run(job)
        except Exception as exc:  # the job row and history are the error record
            logger.exception("Ingestion job %s failed", job_id)
            message = _safe_text(exc, 2000)
            knowledge_db.update_ingestion_job(
                self.db,
                job_id,
                {
                    "status": "failed",
                    "stop_reason": "error",
                    "error": message,
                    "finished_at": _now(),
                },
            )
            self._event(job_id, job["book_id"], "error", "failed", message)

    def _stop(
        self,
        job: dict[str, Any],
        status: str,
        reason: str,
        kind: str,
        level: str = "info",
        **details: Any,
    ) -> None:
        knowledge_db.update_ingestion_job(
            self.db,
            job["id"],
            {
                "status": status,
                "stop_reason": reason,
                "finished_at": _now(),
                "heartbeat_at": _now(),
                "stage": "stopped",
            },
        )
        self._event(job["id"], job["book_id"], level, kind, reason, **details)

    def _run(self, job: dict[str, Any]) -> None:
        book = self._book(job["book_id"])
        if (book.get("metadata") or {}).get("plan_hash"):
            raise IngestionError(FROZEN_PLAN_MESSAGE)
        knowledge_db.update_ingestion_job(
            self.db,
            job["id"],
            {
                "status": "running",
                "stage": "embedding",
                "started_at": _now(),
                "heartbeat_at": _now(),
            },
        )
        self._embed_pending(job)

    def _take_batch(self, pending: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """The first chunks whose estimated tokens fit one request (always at least one)."""
        batch: list[dict[str, Any]] = []
        total = 0
        for row in pending:
            tokens = _estimate(row)
            if batch and total + tokens > self.batch_tokens:
                break
            batch.append(row)
            total += tokens
        return batch

    def _pace(self, last_request: float | None) -> float:
        """Wait so requests stay under the configured rate; returns the time of this request."""
        if self.requests_per_minute > 0 and last_request is not None:
            wait = 60.0 / self.requests_per_minute - (self.clock() - last_request)
            if wait > 0:
                self.sleep(wait)
        return self.clock()

    def _embed_pending(self, job: dict[str, Any]) -> None:
        job_id, book_id = job["id"], job["book_id"]
        limit = job.get("token_limit") if job.get("token_limit") is not None else self.max_tokens
        processed = int(job.get("processed_chunks") or 0)
        tokens = int(job.get("embedded_tokens") or 0)
        last_request: float | None = None
        batches = 0
        while True:
            fresh = knowledge_db.get_ingestion_job(self.db, job_id) or job
            if fresh.get("pause_requested"):
                self._stop(
                    job,
                    "paused",
                    "Paused by the operator",
                    "paused",
                    chunks_embedded=processed,
                    tokens_used=tokens,
                )
                return
            reason = self.provider_pause()
            if reason:
                self._stop(
                    job,
                    "paused",
                    reason,
                    "provider_stop",
                    "warning",
                    chunks_embedded=processed,
                    tokens_used=tokens,
                )
                return
            pending = knowledge_db.chunks_needing_embeddings(self.db, book_id, limit=64)
            if not pending:
                knowledge_db.update_ingestion_job(
                    self.db,
                    job_id,
                    {
                        "status": "completed",
                        "stage": "completed",
                        "stop_reason": None,
                        "error": None,
                        "finished_at": _now(),
                        "heartbeat_at": _now(),
                    },
                )
                self._event(
                    job_id,
                    book_id,
                    "info",
                    "completed",
                    f"Finished: {processed} chunks embedded, {tokens} tokens used",
                    chunks_embedded=processed,
                    tokens_used=tokens,
                )
                return

            batch = self._take_batch(pending)
            # About 4 characters per token (as the chunker estimates), plus a margin.
            # Stop BEFORE sending, never after.
            estimate = int(sum(_estimate(r) for r in batch) * SAFETY_MARGIN)
            if limit is not None and tokens + estimate > limit:
                self._stop(
                    job,
                    "paused",
                    "Token limit reached",
                    "limit_reached",
                    "warning",
                    tokens_used=tokens,
                    next_batch_estimate=estimate,
                    token_limit=limit,
                    chunks_embedded=processed,
                )
                self._event(
                    job_id,
                    book_id,
                    "info",
                    "limit_hint",
                    f"{tokens:,} of {limit:,} tokens used; the next batch needs about "
                    f"{estimate:,}. "
                    "Nothing more was sent. Start again to continue after raising the limit.",
                )
                return
            if self.budget_tokens is not None:
                used = knowledge_db.budget_tokens_used(self.db)
                if used + estimate > self.budget_tokens:
                    self._stop(
                        job,
                        "paused",
                        "Total token budget used up",
                        "budget_exhausted",
                        "warning",
                        budget_used=used,
                        budget=self.budget_tokens,
                        chunks_embedded=processed,
                    )
                    return

            last_request = self._pace(last_request)
            try:
                result = self.embedder.embed_documents([r["content"] for r in batch])
            except Exception as exc:
                details = provider_error_details(exc)
                status = details["http_status"]
                if status == 429:
                    message = (
                        "The provider answered HTTP 429 (a rate limit or the free allowance). "
                        "This batch was not stored and nothing was billed for it. Check the "
                        "provider "
                        "dashboard before retrying."
                    )
                    kind = "provider_rate_limited"
                    self._set_provider_stop()
                else:
                    message = (
                        f"The provider returned an error ({details['error_class']}). "
                        "This batch was not stored."
                    )
                    kind = "provider_error"
                knowledge_db.update_ingestion_job(
                    self.db,
                    job_id,
                    {
                        "status": "failed",
                        "stop_reason": "provider_error",
                        "error": message,
                        "finished_at": _now(),
                        "heartbeat_at": _now(),
                    },
                )
                self._event(
                    job_id,
                    book_id,
                    "error",
                    kind,
                    message,
                    chunks_embedded=processed,
                    tokens_used=tokens,
                    **{
                        ("provider_message" if k == "message" else k): v for k, v in details.items()
                    },
                )
                return

            model = self.provider_info.get("model")
            items = [
                {"id": r["id"], "embedding": e, "token_count": r.get("token_count"), "model": model}
                for r, e in zip(batch, result.embeddings)
            ]
            stored = knowledge_db.apply_chunk_embeddings(self.db, items)
            if stored != len(items):
                # A missed update would leave chunks unembedded and the next pass would send (and
                # pay for) the same batch again, forever. Stop instead.
                raise IngestionError(
                    f"The database stored {stored} of {len(items)} embeddings for this batch; "
                    "stopping so the same chunks are not sent to the provider again."
                )
            processed += len(batch)
            tokens += result.total_tokens
            batches += 1
            knowledge_db.update_ingestion_job(
                self.db,
                job_id,
                {"processed_chunks": processed, "embedded_tokens": tokens, "heartbeat_at": _now()},
            )
            if batches % PROGRESS_EVENT_EVERY == 0:
                self._event(
                    job_id,
                    book_id,
                    "info",
                    "progress",
                    f"{processed} chunks embedded, {tokens} tokens used",
                    chunks_embedded=processed,
                    tokens_used=tokens,
                    batches=batches,
                )


__all__ = [
    "ACTIVE",
    "BookNotFoundError",
    "BudgetExhaustedError",
    "CATEGORIES",
    "ConfirmationRequiredError",
    "DuplicateBookError",
    "IngestionError",
    "IngestionService",
    "MAX_CHUNK_CHARS",
    "ProviderPausedError",
    "STALE_JOB_SECONDS",
    "TokenLimitReachedError",
    "provider_error_details",
]
