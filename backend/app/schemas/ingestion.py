"""Schemas for the ingestion controls (operator only).

All numbers come from the database, never from local report files. Nothing here ever
contains an API key.
"""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

JobStatus = Literal["pending", "running", "paused", "completed", "failed"]
Level = Literal["info", "warning", "error"]


class IngestionLimits(BaseModel):
    """The provider and the spending limits that apply to every embedding job."""

    provider: str = "Voyage AI embeddings"
    endpoint_host: str  # api.voyageai.com, ai.mongodb.com (Atlas) or "not configured"
    model: str
    dimension: int
    per_job_token_limit: int
    budget_token_limit: int
    budget_tokens_used: int
    budget_tokens_remaining: int
    batch_tokens: int
    requests_per_minute: int  # 0 = not paced
    provider_paused: bool
    provider_pause_reason: str | None = None


class JobOut(BaseModel):
    id: str
    book_id: str
    status: JobStatus
    stage: str
    total_chunks: int = 0
    processed_chunks: int = 0
    embedded_tokens: int = 0
    token_limit: int | None = None
    estimated_tokens: int | None = None
    pause_requested: bool = False
    error: str | None = None
    stop_reason: str | None = None
    resumed_from: str | None = None
    created_at: datetime | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    heartbeat_at: datetime | None = None


class AutoState(BaseModel):
    """Automatic resume for one book: on or off, its place in the queue, why it stopped."""

    enabled: bool = False
    position: int | None = None  # 1 = next (or running now)
    since: str | None = None
    failures: int = 0
    note: str | None = None  # why it ended or what went wrong, in plain words


class BookIndexStats(BaseModel):
    book_id: str
    title: str
    category: str
    source_filename: str
    total_pages: int | None = None
    total_chunks: int = 0
    embedded_chunks: int = 0
    pending_chunks: int = 0
    embedded_tokens: int = 0
    pending_tokens: int = 0
    prepared: bool = False  # text has been split into chunks
    complete: bool = False  # every chunk has a vector: fully searchable
    frozen_plan: bool = False  # belongs to the command-line pipeline
    # One plain state for the list: running, stalled, paused, error, interrupted, complete,
    # partial, ready, not_prepared. `detail` says why; `idle_seconds` is time since last report.
    state: str = "ready"
    detail: str | None = None
    idle_seconds: int | None = None
    latest_job: JobOut | None = None
    auto_resume: AutoState = Field(default_factory=AutoState)


class EventOut(BaseModel):
    id: int
    job_id: str | None = None
    book_id: str
    level: Level
    kind: str
    message: str
    details: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime | None = None


class PlanOut(BaseModel):
    """What would happen if the operator starts (or resumes) embedding this book."""

    stats: BookIndexStats
    limits: IngestionLimits
    effective_token_limit: int  # the most this job may use: min(per job, remaining budget)
    can_start: bool
    blockers: list[str] = Field(default_factory=list)
    active_job: JobOut | None = None
    latest_job: JobOut | None = None


class StartRequest(BaseModel):
    """Explicit confirmation to spend provider tokens. Without confirmed=true nothing starts."""

    confirmed: bool = False
    max_tokens: int | None = Field(default=None, ge=1)  # optional lower limit for this job


class BookIngestionOut(BaseModel):
    plan: PlanOut
    jobs: list[JobOut] = Field(default_factory=list)
    events: list[EventOut] = Field(default_factory=list)


class OverviewOut(BaseModel):
    limits: IngestionLimits
    books: list[BookIndexStats] = Field(default_factory=list)
    active_jobs: list[JobOut] = Field(default_factory=list)


class ChunkOut(BaseModel):
    id: str
    chunk_index: int
    content: str
    token_count: int | None = None
    embedded: bool
    page_start: int | None = None  # PDF page number (not the printed page number)
    page_end: int | None = None
    section_heading: str | None = None
    section_path: list[str] = Field(default_factory=list)


class ChunkPage(BaseModel):
    total: int
    offset: int
    limit: int
    items: list[ChunkOut]


class PageTextOut(BaseModel):
    page: int  # PDF page number
    chars: int
    text: str  # truncated for display
    truncated: bool = False


class TextPreview(BaseModel):
    total_pages: int
    offset: int
    limit: int
    pages: list[PageTextOut]


class AutoStartRequest(BaseModel):
    """Explicit confirmation to keep embedding these books automatically."""

    book_ids: list[str] = Field(min_length=1, max_length=50)
    confirmed: bool = False


class AutoStopRequest(BaseModel):
    book_ids: list[str] | None = None  # None = stop everything


class AutoQueuedBook(BaseModel):
    book_id: str
    title: str
    pending_chunks: int
    pending_tokens: int


class AutoSkippedBook(BaseModel):
    book_id: str
    title: str | None = None
    reason: str


class AutoStartOut(BaseModel):
    queued: list[AutoQueuedBook]
    skipped: list[AutoSkippedBook] = Field(default_factory=list)
    total_pending_tokens: int


class AutoStopOut(BaseModel):
    stopped: list[str]
