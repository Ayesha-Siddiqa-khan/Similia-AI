"""Knowledge-base persistence over Supabase Postgres (pgvector).

Every function takes the Supabase client so tests can inject a fake. All
writes go through the service-role (secret) client: RLS is enabled on all
knowledge_* tables with no anon/authenticated policies (migration 2), so the
backend is the only trusted write path.
"""

import logging
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

# Bounds for single PostgREST round trips.
INSERT_BATCH_SIZE = 200

# Columns returned by list/get book calls; raw_text (potentially megabytes)
# is only fetched when the ingestion engine explicitly needs it.
BOOK_COLUMNS = (
    "id, category, title, author, publisher, publication_year, language, "
    "source_filename, source_uri, content_hash, metadata, section_count, "
    "chunk_count, created_at, updated_at"
)


class KnowledgeDBError(RuntimeError):
    """A knowledge-base database operation failed."""


def _execute(operation: str, fn: "callable") -> Any:
    try:
        return fn().execute()
    except Exception as exc:  # postgrest raises APIError subclasses
        raise KnowledgeDBError(f"{operation} failed: {exc}") from exc


# ---------------------------------------------------------------------------
# Books
# ---------------------------------------------------------------------------


def create_book(client: Any, book: dict[str, Any]) -> dict[str, Any]:
    response = _execute("create_book", lambda: client.table("knowledge_books").insert(book))
    return response.data[0]


def get_book(client: Any, book_id: str, include_text: bool = False) -> dict[str, Any] | None:
    columns = "*" if include_text else BOOK_COLUMNS
    response = _execute(
        "get_book", lambda: client.table("knowledge_books").select(columns).eq("id", book_id)
    )
    return response.data[0] if response.data else None


def list_books(client: Any) -> list[dict[str, Any]]:
    response = _execute(
        "list_books",
        lambda: client.table("knowledge_books").select(BOOK_COLUMNS).order("created_at"),
    )
    return response.data


def find_book_by_content_hash(client: Any, content_hash: str) -> dict[str, Any] | None:
    response = _execute(
        "find_book_by_content_hash",
        lambda: (
            client.table("knowledge_books").select(BOOK_COLUMNS).eq("content_hash", content_hash)
        ),
    )
    return response.data[0] if response.data else None


def update_book_counts(client: Any, book_id: str, *, section_count: int, chunk_count: int) -> None:
    _execute(
        "update_book_counts",
        lambda: (
            client.table("knowledge_books")
            .update(
                {
                    "section_count": section_count,
                    "chunk_count": chunk_count,
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                }
            )
            .eq("id", book_id)
        ),
    )


# ---------------------------------------------------------------------------
# Sections and chunks
# ---------------------------------------------------------------------------


def upsert_sections(client: Any, sections: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Upsert sections keyed on (book_id, ordinal); returns rows with ids.

    Upsert (not delete+insert) keeps section ids stable across resumed jobs
    so existing chunk->section links survive re-ingestion.
    """
    if not sections:
        return []
    rows: list[dict[str, Any]] = []
    for start in range(0, len(sections), INSERT_BATCH_SIZE):
        batch = sections[start : start + INSERT_BATCH_SIZE]
        response = _execute(
            "upsert_sections",
            lambda: client.table("knowledge_sections").upsert(
                batch, on_conflict="book_id,ordinal", returning="representation"
            ),
        )
        rows.extend(response.data)
    return rows


def upsert_chunks(client: Any, chunks: list[dict[str, Any]]) -> None:
    """Insert chunks ignoring duplicates on (book_id, chunk_index).

    ignore-duplicates makes interrupted ingestion resume-safe: re-running the
    deterministic chunker produces identical rows and nothing is duplicated
    or re-embedded.
    """
    for start in range(0, len(chunks), INSERT_BATCH_SIZE):
        batch = chunks[start : start + INSERT_BATCH_SIZE]
        _execute(
            "upsert_chunks",
            lambda: client.table("knowledge_chunks").upsert(
                batch, on_conflict="book_id,chunk_index", ignore_duplicates=True
            ),
        )


def chunks_needing_embeddings(
    client: Any, book_id: str, limit: int = INSERT_BATCH_SIZE
) -> list[dict[str, Any]]:
    """Unembedded chunks in book order — the resume frontier."""
    response = _execute(
        "chunks_needing_embeddings",
        lambda: (
            client.table("knowledge_chunks")
            .select("id,chunk_index,content,token_count")
            .eq("book_id", book_id)
            .is_("embedding", "null")
            .order("chunk_index")
            .limit(limit)
        ),
    )
    return response.data


def apply_chunk_embeddings(client: Any, items: list[dict[str, Any]]) -> int:
    """Write a batch of embeddings atomically via RPC; returns rows updated."""
    if not items:
        return 0
    response = _execute(
        "apply_chunk_embeddings",
        lambda: client.rpc("apply_chunk_embeddings", {"items": items}),
    )
    return int(response.data or 0)


# ---------------------------------------------------------------------------
# Ingestion jobs
# ---------------------------------------------------------------------------


def create_ingestion_job(
    client: Any, book_id: str, extra: dict[str, Any] | None = None
) -> dict[str, Any]:
    response = _execute(
        "create_ingestion_job",
        lambda: client.table("ingestion_jobs").insert({"book_id": book_id, **(extra or {})}),
    )
    return response.data[0]


def list_ingestion_jobs(
    client: Any,
    *,
    book_id: str | None = None,
    statuses: tuple[str, ...] | None = None,
    limit: int = 10,
) -> list[dict[str, Any]]:
    """Newest first."""

    def query() -> Any:
        q = client.table("ingestion_jobs").select("*")
        if book_id:
            q = q.eq("book_id", book_id)
        if statuses:
            q = q.in_("status", list(statuses))
        return q.order("created_at", desc=True).limit(limit)

    return _execute("list_ingestion_jobs", query).data


def budget_tokens_used(client: Any) -> int:
    """Embedding tokens used by every website ingestion job so far (the spend ledger)."""
    rows = _execute(
        "budget_tokens_used", lambda: client.table("ingestion_jobs").select("embedded_tokens")
    ).data
    return sum(int(row.get("embedded_tokens") or 0) for row in rows)


def add_ingestion_event(
    client: Any,
    *,
    job_id: str | None,
    book_id: str,
    level: str,
    kind: str,
    message: str,
    details: dict[str, Any] | None = None,
) -> None:
    """Processing history. Never put secrets or patient data in `details`."""
    _execute(
        "add_ingestion_event",
        lambda: client.table("ingestion_events").insert(
            {
                "job_id": job_id,
                "book_id": book_id,
                "level": level,
                "kind": kind,
                "message": message[:1000],
                "details": details or {},
            }
        ),
    )


def list_ingestion_events(
    client: Any, *, book_id: str | None = None, job_id: str | None = None, limit: int = 50
) -> list[dict[str, Any]]:
    """Newest first."""

    def query() -> Any:
        q = client.table("ingestion_events").select("*")
        if book_id:
            q = q.eq("book_id", book_id)
        if job_id:
            q = q.eq("job_id", job_id)
        return q.order("id", desc=True).limit(limit)

    return _execute("list_ingestion_events", query).data


def book_stats(client: Any) -> list[dict[str, Any]]:
    """Real index counts per book, from the database."""
    response = _execute("book_stats", lambda: client.rpc("knowledge_book_stats", {}))
    return response.data or []


def list_chunks(
    client: Any,
    book_id: str,
    *,
    offset: int = 0,
    limit: int = 20,
    query: str | None = None,
    embedded: bool | None = None,
) -> list[dict[str, Any]]:
    """One page of chunks with an `embedded` flag and the running `total` on every row."""
    response = _execute(
        "list_chunks",
        lambda: client.rpc(
            "knowledge_chunk_page",
            {
                "p_book": book_id,
                "p_offset": offset,
                "p_limit": limit,
                "p_query": query,
                "p_embedded": embedded,
            },
        ),
    )
    return response.data or []


def get_ingestion_job(client: Any, job_id: str) -> dict[str, Any] | None:
    response = _execute(
        "get_ingestion_job",
        lambda: client.table("ingestion_jobs").select("*").eq("id", job_id),
    )
    return response.data[0] if response.data else None


def update_ingestion_job(client: Any, job_id: str, fields: dict[str, Any]) -> None:
    fields = {**fields, "updated_at": datetime.now(timezone.utc).isoformat()}
    _execute(
        "update_ingestion_job",
        lambda: client.table("ingestion_jobs").update(fields).eq("id", job_id),
    )


# ---------------------------------------------------------------------------
# Search and evaluation
# ---------------------------------------------------------------------------


def search_chunks(
    client: Any,
    query_embedding: list[float],
    match_count: int = 5,
    match_threshold: float = 0.0,
    category: str | None = None,
) -> list[dict[str, Any]]:
    params: dict[str, Any] = {
        "query_embedding": query_embedding,
        "match_count": match_count,
        "match_threshold": match_threshold,
    }
    if category is not None:
        params["filter_category"] = category
    response = _execute("search_chunks", lambda: client.rpc("match_chunks", params))
    return response.data


def keyword_search_chunks(
    client: Any, tsquery: str, match_count: int = 10, category: str | None = None
) -> list[dict[str, Any]]:
    params: dict[str, Any] = {"p_tsquery": tsquery, "match_count": match_count}
    if category is not None:
        params["filter_category"] = category
    return _execute(
        "keyword_search_chunks", lambda: client.rpc("keyword_match_chunks", params)
    ).data


def save_retrieval_evaluation(client: Any, evaluation: dict[str, Any]) -> None:
    _execute(
        "save_retrieval_evaluation",
        lambda: client.table("retrieval_evaluations").insert(evaluation),
    )


# ---------------------------------------------------------------------------
# System flags (the provider stop)
# ---------------------------------------------------------------------------


def get_system_flag(client: Any, key: str) -> dict[str, Any] | None:
    rows = _execute(
        "get_system_flag",
        lambda: client.table("system_flags").select("key,paused,reason,set_at").eq("key", key),
    ).data
    return rows[0] if rows else None


def set_system_flag(client: Any, key: str, *, paused: bool, reason: str | None, by: str) -> None:
    """Upsert a flag. The application only ever uses this to SET the provider stop."""
    _execute(
        "set_system_flag",
        lambda: client.table("system_flags").upsert(
            {
                "key": key,
                "paused": paused,
                "reason": reason,
                "set_at": datetime.now(timezone.utc).isoformat(),
                "set_by": by,
            }
        ),
    )
