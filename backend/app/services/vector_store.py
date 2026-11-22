"""Vector store abstraction.

Phase 1 ships the interface and a Supabase pgvector implementation stub. The
real implementation (tables, RPC functions, Row Level Security) arrives with the
database design phase — no vector database besides pgvector is used.
"""

from typing import Protocol


class VectorStore(Protocol):
    """Minimal similarity-search contract for RAG retrieval."""

    def similarity_search(
        self,
        query_embedding: list[float],
        k: int = 5,
        metadata_filter: dict[str, object] | None = None,
    ) -> list[dict[str, object]]:
        """Return the k most similar chunks with their metadata."""
        ...


class SupabasePgVectorStore:
    """Supabase pgvector-backed store (stub until Phase 2 schema exists)."""

    def __init__(self, table_name: str = "document_chunks") -> None:
        self._table_name = table_name

    def similarity_search(
        self,
        query_embedding: list[float],
        k: int = 5,
        metadata_filter: dict[str, object] | None = None,
    ) -> list[dict[str, object]]:
        raise NotImplementedError(
            "pgvector similarity search lands in Phase 2 together with the "
            "document_chunks schema and RLS policies."
        )
