"""Pydantic request/response schemas for the knowledge-base API."""

from datetime import datetime

from pydantic import BaseModel, Field

from app.services.rag import KnowledgeSource


class BookOut(BaseModel):
    """Registered book without its extracted text."""

    id: str
    category: KnowledgeSource
    title: str
    author: str | None = None
    publisher: str | None = None
    publication_year: int | None = None
    language: str = "en"
    source_filename: str
    source_uri: str | None = None
    metadata: dict = Field(default_factory=dict)
    section_count: int = 0
    chunk_count: int = 0
    created_at: datetime | None = None


class IngestionJobOut(BaseModel):
    """Ingestion job progress and error state."""

    id: str
    book_id: str
    status: str
    stage: str
    total_chunks: int = 0
    processed_chunks: int = 0
    embedded_tokens: int = 0
    error: str | None = None
    created_at: datetime | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None


class SearchRequest(BaseModel):
    """Semantic search request."""

    query: str = Field(min_length=1, max_length=2000)
    k: int = Field(default=5, ge=1, le=50)
    category: KnowledgeSource | None = None
    threshold: float = Field(default=0.0, ge=-1.0, le=1.0)


class PassageOut(BaseModel):
    """A retrieved passage with source traceability."""

    chunk_id: str
    book_id: str
    section_id: str | None = None
    book_title: str
    book_category: str
    book_author: str | None = None
    section_heading: str | None = None
    section_path: list[str] = Field(default_factory=list)
    content: str
    similarity: float
    metadata: dict = Field(default_factory=dict)
    page_start: int | None = None  # PDF page number (not the printed page number)
    page_end: int | None = None
    book_complete: bool = True  # False: the book is only partly indexed, so evidence may be missing
    retrieval_mode: str = "semantic"  # "keyword": word match score, not a meaning similarity


class SearchResponse(BaseModel):
    """Search results with timing for the admin UI."""

    query: str
    k: int
    latency_ms: int
    results: list[PassageOut]
    # titles of partly indexed books in the results
    incomplete_books: list[str] = Field(default_factory=list)
    retrieval_mode: str = "semantic"
