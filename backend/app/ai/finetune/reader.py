"""Read-only access to the knowledge base for dataset preparation.

Every query is a ``SELECT`` against an allow-listed ``knowledge_*`` table.
Embeddings and ``raw_text`` are rejected before a query is built, so a caller
cannot accidentally pull vectors or megabytes of book text into a dataset.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from app.ai.finetune.config import (
    BOOK_COLUMNS,
    CHUNK_COLUMNS,
    FORBIDDEN_COLUMNS,
    READ_PAGE_SIZE,
    READABLE_TABLES,
    SECTION_COLUMNS,
)
from app.ai.finetune.models import BookRecord, ChunkRecord, SectionRecord


class ReadOnlyViolation(RuntimeError):
    """A caller asked for a table or column the module must never read."""


def _checked_columns(columns: str | tuple[str, ...]) -> str:
    raw = ",".join(columns) if isinstance(columns, tuple) else columns
    names = [part.strip() for part in raw.split(",") if part.strip()]
    if not names:
        raise ReadOnlyViolation("A select must name its columns")
    if "*" in names:
        raise ReadOnlyViolation("Wildcard selects are not allowed")
    forbidden = FORBIDDEN_COLUMNS.intersection(names)
    if forbidden:
        raise ReadOnlyViolation(f"Forbidden columns requested: {sorted(forbidden)}")
    return ",".join(names)


class ReadOnlyKnowledgeReader:
    """Paged, read-only reader for books, chunks and sections."""

    def __init__(self, client: Any, page_size: int = READ_PAGE_SIZE) -> None:
        if page_size < 1:
            raise ValueError("page_size must be positive")
        self._client = client
        self._page_size = page_size

    def _table(self, name: str) -> Any:
        if name not in READABLE_TABLES:
            raise ReadOnlyViolation(f"Table is not readable by this module: {name}")
        return self._client.table(name)

    def _paged(
        self,
        table: str,
        columns: str | tuple[str, ...],
        order: str,
        **filters: Any,
    ) -> Iterator[dict[str, Any]]:
        selected = _checked_columns(columns)
        start = 0
        while True:
            query = self._table(table).select(selected).order(order)
            for key, value in filters.items():
                query = query.eq(key, value)
            batch = query.range(start, start + self._page_size - 1).execute().data or []
            for row in batch:
                yield row
            if len(batch) < self._page_size:
                return
            start += self._page_size

    def books(self) -> list[BookRecord]:
        rows = self._paged("knowledge_books", BOOK_COLUMNS, "created_at")
        return [
            BookRecord(
                id=row["id"],
                title=(row.get("title") or "Untitled").strip(),
                author=(row.get("author") or None),
                publisher=(row.get("publisher") or None),
                publication_year=row.get("publication_year"),
                language=row.get("language"),
                category=(row.get("category") or "general").strip(),
                source_filename=(row.get("source_filename") or "").strip(),
                source_uri=(row.get("source_uri") or None),
                content_hash=row["content_hash"],
                section_count=int(row.get("section_count") or 0),
                chunk_count=int(row.get("chunk_count") or 0),
            )
            for row in rows
        ]

    def chunks_for_book(self, book_id: str) -> Iterator[ChunkRecord]:
        rows = self._paged(
            "knowledge_chunks",
            CHUNK_COLUMNS,
            "chunk_index",
            book_id=book_id,
        )
        for row in rows:
            yield ChunkRecord(
                id=row["id"],
                book_id=row["book_id"],
                section_id=row.get("section_id"),
                chunk_index=int(row["chunk_index"]),
                content=row.get("content") or "",
                content_hash=row["content_hash"],
                token_count=row.get("token_count"),
                metadata=row.get("metadata") or {},
            )

    def sections_for_book(self, book_id: str) -> list[SectionRecord]:
        rows = self._paged(
            "knowledge_sections",
            SECTION_COLUMNS,
            "ordinal",
            book_id=book_id,
        )
        return [
            SectionRecord(
                id=row["id"],
                book_id=row["book_id"],
                ordinal=int(row["ordinal"]),
                heading=(row.get("heading") or "").strip(),
                path=tuple(row.get("path") or []),
                section_type=row.get("section_type"),
                page_start=row.get("page_start"),
                page_end=row.get("page_end"),
            )
            for row in rows
        ]
