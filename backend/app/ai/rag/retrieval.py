"""Retrieval over the knowledge base (semantic vector search first).

Two retrievers share one contract: VectorRetriever (meaning-based, needs the embedding
provider) and KeywordRetriever (word matching over the stored text, needs no provider).
FallbackRetriever uses keyword matching when the provider cannot be reached, and says so:
every passage carries retrieval_mode, so no screen can pass keyword hits off as semantic ones.
"""

import logging
import re
import time
from dataclasses import dataclass
from typing import Any, Protocol

from app.services import knowledge_db
from app.services.embeddings import EmbeddingProvider

logger = logging.getLogger(__name__)


@dataclass
class RetrievedPassage:
    """A search hit with full source traceability."""

    chunk_id: str
    book_id: str
    section_id: str | None
    book_title: str
    book_category: str
    book_author: str | None
    section_heading: str | None
    section_path: list[str]
    content: str
    similarity: float
    metadata: dict
    # "semantic": cosine similarity of meaning. "keyword": a word-match score (not comparable).
    retrieval_mode: str = "semantic"


class Retriever(Protocol):
    """Anything that can rank passages for a query."""

    def search(
        self, query: str, k: int = 5, category: str | None = None, threshold: float = 0.0
    ) -> tuple[list[RetrievedPassage], int]:
        """Return passages and latency in milliseconds."""
        ...


class VectorRetriever:
    """Cosine similarity search over knowledge_chunks via the match_chunks RPC."""

    def __init__(self, db: Any, embedder: EmbeddingProvider) -> None:
        self._db = db
        self._embedder = embedder

    def search(
        self, query: str, k: int = 5, category: str | None = None, threshold: float = 0.0
    ) -> tuple[list[RetrievedPassage], int]:
        started = time.perf_counter()
        query_embedding = self._embedder.embed_query(query)
        rows = knowledge_db.search_chunks(
            self._db,
            query_embedding=query_embedding,
            match_count=k,
            match_threshold=threshold,
            category=category,
        )
        latency_ms = int((time.perf_counter() - started) * 1000)
        passages = [_passage(row, "semantic") for row in rows]
        return passages, latency_ms


_STOPWORDS = frozenset(
    "the and for that with this from have has had was were are but not you your his her its "
    "they them then than into out all any can may will would should could been being also "
    "when what which where while who whom whose how why per via only some such more most very "
    "after before during over under about above below between each other both few many much "
    "patient patients case remedy".split()
)
MAX_TERMS = 12


def keyword_terms(text: str) -> list[str]:
    """Plain lower-case words (letters only, 3+ long, no stop words), most useful first."""
    words = re.findall(r"[a-z]{3,}", text.lower())
    seen: dict[str, None] = {}
    for word in words:
        if word not in _STOPWORDS:
            seen.setdefault(word)
    return list(seen)[:MAX_TERMS]


def to_tsquery(terms: list[str]) -> str:
    """'a | b | c'. Built from letters only, so it can never be a malformed query."""
    return " | ".join(terms)


def _passage(row: dict[str, Any], mode: str) -> RetrievedPassage:
    return RetrievedPassage(
        chunk_id=row["chunk_id"],
        book_id=row["book_id"],
        section_id=row.get("section_id"),
        book_title=row["book_title"],
        book_category=row["book_category"],
        book_author=row.get("book_author"),
        section_heading=row.get("section_heading"),
        section_path=row.get("section_path") or [],
        content=row["content"],
        similarity=float(row["similarity"]),
        metadata=row.get("chunk_metadata") or {},
        retrieval_mode=mode,
    )


class KeywordRetriever:
    """Word matching over the stored chunk text (Postgres full-text search). No provider call."""

    mode = "keyword"

    def __init__(self, db: Any) -> None:
        self._db = db

    def search(
        self, query: str, k: int = 5, category: str | None = None, threshold: float = 0.0
    ) -> tuple[list[RetrievedPassage], int]:
        started = time.perf_counter()
        terms = keyword_terms(query)
        rows = (
            knowledge_db.keyword_search_chunks(
                self._db, tsquery=to_tsquery(terms), match_count=k, category=category
            )
            if terms
            else []
        )
        return [_passage(row, "keyword") for row in rows], int(
            (time.perf_counter() - started) * 1000
        )


class FallbackRetriever:
    """Meaning-based search first; word matching when the provider cannot be used.

    After the first provider failure it stops trying the provider for the rest of this request
    (one analysis runs several searches). `mode` tells the caller which kind of search happened.
    """

    def __init__(self, primary: Retriever, fallback: Retriever) -> None:
        self._primary, self._fallback = primary, fallback
        self.fell_back = False

    @property
    def mode(self) -> str:
        return "keyword" if self.fell_back else "semantic"

    def search(
        self, query: str, k: int = 5, category: str | None = None, threshold: float = 0.0
    ) -> tuple[list[RetrievedPassage], int]:
        if not self.fell_back:
            try:
                return self._primary.search(query, k=k, category=category, threshold=threshold)
            except Exception as exc:  # provider refused or unreachable: log the type only
                logger.warning(
                    "Semantic search unavailable (%s, http_status=%s); using keyword matching",
                    type(exc).__name__,
                    getattr(exc, "http_status", None) or getattr(exc, "status_code", None),
                )
                self.fell_back = True
        return self._fallback.search(query, k=k, category=category, threshold=threshold)
