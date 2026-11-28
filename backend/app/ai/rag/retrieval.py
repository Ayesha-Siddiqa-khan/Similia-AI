"""Retrieval over the knowledge base (semantic vector search first).

Two retrievers share one contract: VectorRetriever (meaning-based, needs the embedding
provider) and KeywordRetriever (word matching over the stored text, needs no provider).
FallbackRetriever uses keyword matching when the provider cannot be reached, and says so:
every passage carries retrieval_mode, so no screen can pass keyword hits off as semantic ones.
"""

import logging
import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

from app.services import knowledge_db
from app.services.embeddings import EmbeddingProvider, EmbeddingResponseError, quota_exhausted
from app.services.rag_metrics import count, record_fallback
from app.services.voyage_budget import VoyageBudgetUnavailable

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
    # Which searches found it: ["semantic"], ["keyword"] or both (hybrid).
    matched_by: list[str] = field(default_factory=list)


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
        self._last_embedding: tuple[str, list[float]] | None = None
        self._prepared: dict[str, list[float]] = {}

    def prepare_queries(self, queries: list[str], scope: str | None) -> None:
        batch = getattr(self._embedder, "embed_queries", None)
        if batch is not None:
            try:
                self._prepared.update(batch(queries, scope))
            except Exception as exc:
                raise SemanticSearchError("embedding") from exc

    def search(
        self, query: str, k: int = 5, category: str | None = None, threshold: float = 0.0
    ) -> tuple[list[RetrievedPassage], int]:
        started = time.perf_counter()
        if self._last_embedding is None or self._last_embedding[0] != query:
            try:
                vector = self._prepared.get(query)
                self._last_embedding = (
                    query, vector if vector is not None else self._embedder.embed_query(query),
                )
            except Exception as exc:
                raise SemanticSearchError("embedding") from exc
        try:
            rows = knowledge_db.search_chunks(
                self._db,
                query_embedding=self._last_embedding[1],
                match_count=k,
                match_threshold=threshold,
                category=category,
            )
        except Exception as exc:
            raise SemanticSearchError("match_chunks") from exc
        latency_ms = int((time.perf_counter() - started) * 1000)
        try:
            passages = [_passage(row, "semantic") for row in rows]
        except (TypeError, ValueError, KeyError) as exc:
            raise SemanticSearchError("vector_response") from exc
        count("semantic_searches")
        count("retrieval_ms", latency_ms)
        return passages, latency_ms


class SemanticSearchError(RuntimeError):
    def __init__(self, stage: str) -> None:
        self.stage = stage
        super().__init__(stage)


_STOPWORDS = frozenset(
    "the and for that with this from have has had was were are but not you your his her its "
    "they them then than into out all any can may will would should could been being also "
    "when what which where while who whom whose how why per via only some such more most very "
    "after before during over under about above below between each other both few many much "
    "patient patients case remedy".split()
)
MAX_TERMS = 12


def describe_failure(exc: Exception) -> str:
    """Error type and HTTP status only: never the message, which could carry request text."""
    if isinstance(exc, SemanticSearchError):
        causes: list[BaseException] = [exc]
        while causes[-1].__cause__ is not None and len(causes) < 6:
            causes.append(causes[-1].__cause__)
        http_status = next(
            (
                status for cause in causes
                for status in (getattr(cause, "http_status", None),
                               getattr(cause, "status_code", None))
                if isinstance(status, int) and 100 <= status <= 599
            ),
            None,
        )
        db_code = next(
            (code for cause in causes for code in (getattr(cause, "code", None),)
             if code in ("PGRST202", "PGRST203", "22000", "22023", "42501", "57014", "42883")),
            None,
        )
        labels = {
            "embedding": "Voyage query embedding failed",
            "match_chunks": "Supabase vector search failed",
            "vector_response": "Supabase returned an invalid vector search result",
        }
        if exc.stage == "embedding":
            if http_status == 429:
                labels["embedding"] = (
                    "Voyage quota or credits are exhausted" if quota_exhausted(causes[-1])
                    else "Voyage temporarily rate-limited embeddings"
                )
            elif isinstance(causes[-1], VoyageBudgetUnavailable):
                labels["embedding"] = "The shared Voyage allowance was unavailable in time"
            elif http_status in (401, 403):
                labels["embedding"] = "Voyage denied access to query embeddings"
            elif isinstance(causes[-1], EmbeddingResponseError):
                labels["embedding"] = "Voyage returned an unusable query vector"
        details = [type(causes[-1]).__name__]
        if http_status:
            details.append(f"HTTP {http_status}")
        if db_code:
            details.append(db_code)
        return f"{labels[exc.stage]} ({', '.join(details)})"
    status = getattr(exc, "http_status", None) or getattr(exc, "status_code", None)
    suffix = f" (HTTP {status})" if isinstance(status, int) and 100 <= status <= 599 else ""
    return f"Meaning-based search was unavailable: {type(exc).__name__}{suffix}"


def prepare_queries(retriever: Retriever, queries: list[str], scope: str | None) -> None:
    prepare = getattr(retriever, "prepare_queries", None)
    if prepare is not None and queries:
        prepare(queries, scope)


def analysis_search_info(analysis: dict[str, Any]) -> dict[str, str | None]:
    """Read execution metadata, with a conservative fallback for legacy snapshots."""
    queries = analysis.get("queries")
    if isinstance(queries, dict) and "retrieval" in queries:
        return queries["retrieval"]
    passages = [p for p in analysis.get("passages") or [] if isinstance(p, dict)]
    modes = {p.get("retrieval_mode") for p in passages} - {None}
    used = "mixed" if len(modes) > 1 else next(iter(modes), None)
    if not used:
        used = "not_run" if analysis.get("outcome") == "red_flag" else (
            "semantic" if passages else "unknown"
        )
    return {
        "requested_mode": next((p["requested_mode"] for p in passages
                                if p.get("requested_mode")), used),
        "retrieval_mode": used,
        "fallback_reason": next((p["fallback_reason"] for p in passages
                                 if p.get("fallback_reason")), None),
    }


def keyword_terms(text: str) -> list[str]:
    """Plain lower-case words (letters only, 3+ long, no stop words), most useful first."""
    words = re.findall(r"[a-z]{3,}", text.lower())
    seen: dict[str, None] = {}
    for word in words:
        if word not in _STOPWORDS:
            seen.setdefault(word)
    return list(seen)[:MAX_TERMS]


def supports_query(query: str, hit: RetrievedPassage) -> bool:
    """Screen weak hits for a complaint anchor while retaining strong semantic paraphrases."""
    if "semantic" in (hit.matched_by or [hit.retrieval_mode]):
        if hit.retrieval_mode == "semantic" and hit.similarity >= 0.62:
            return True
    modifiers = {
        "skin", "chronic", "worse", "better", "winter", "summer", "warmth", "warm", "cold",
        "night", "morning", "evening", "bed", "thick", "sticky", "case", "history", "symptoms",
    }
    terms = [word for word in keyword_terms(query) if word not in modifiers]
    if len(terms) < 2:
        return True
    evidence = set(re.findall(r"[a-z]{3,}", hit.content.casefold()))
    return bool(evidence.intersection(terms)) or any(
        len(term) >= 5 and any(word.startswith(term[:5]) for word in evidence)
        for term in terms
    )


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
        matched_by=[mode],
    )


class KeywordRetriever:
    """Word matching over the stored chunk text (Postgres full-text search). No provider call."""

    mode = "keyword"
    requested = "keyword"
    fallback_reason: str | None = None

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
        elapsed = int((time.perf_counter() - started) * 1000)
        count("retrieval_ms", elapsed)
        if self.requested != "keyword" and self.fallback_reason:
            count("keyword_fallbacks")
            record_fallback(self.fallback_reason)
        return [_passage(row, "keyword") for row in rows], elapsed


class FallbackRetriever:
    """Meaning-based search first; word matching when the provider cannot be used.

    After the first provider failure it stops trying the provider for the rest of this request
    (one analysis runs several searches). `mode` tells the caller which kind of search happened.
    """

    requested = "semantic"

    def __init__(self, primary: Retriever, fallback: Retriever) -> None:
        self._primary, self._fallback = primary, fallback
        self.fell_back = False
        self.fallback_reason: str | None = None

    @property
    def mode(self) -> str:
        return "keyword" if self.fell_back else "semantic"

    def _fail(self, exc: Exception) -> None:
        self.fell_back = True
        self.fallback_reason = describe_failure(exc)
        record_fallback(self.fallback_reason)
        logger.warning("Semantic query fallback: %s", self.fallback_reason)

    def prepare_queries(self, queries: list[str], scope: str | None) -> None:
        if not self.fell_back:
            try:
                prepare_queries(self._primary, queries, scope)
            except Exception as exc:
                self._fail(exc)

    def search(
        self, query: str, k: int = 5, category: str | None = None, threshold: float = 0.0
    ) -> tuple[list[RetrievedPassage], int]:
        if not self.fell_back:
            try:
                return self._primary.search(query, k=k, category=category, threshold=threshold)
            except Exception as exc:  # provider refused or unreachable: log the type only
                self._fail(exc)
        count("keyword_fallbacks")
        return self._fallback.search(query, k=k, category=category, threshold=threshold)


class HybridRetriever:
    """Meaning-based and keyword results merged by reciprocal rank fusion.

    A passage found by both searches ranks above one found by only one. If the meaning-based
    search cannot be used, the keyword results are returned and `mode` says "keyword", so the
    method used is never overstated.
    """

    requested = "hybrid"
    RRF_K = 60

    def __init__(self, semantic: Retriever, keyword: Retriever) -> None:
        self._semantic, self._keyword = semantic, keyword
        self.fell_back = False
        self.fallback_reason: str | None = None

    @property
    def mode(self) -> str:
        return "keyword" if self.fell_back else "hybrid"

    def _fail(self, exc: Exception) -> None:
        self.fell_back = True
        self.fallback_reason = describe_failure(exc)
        record_fallback(self.fallback_reason)
        logger.warning("Hybrid query fallback: %s", self.fallback_reason)

    def prepare_queries(self, queries: list[str], scope: str | None) -> None:
        if not self.fell_back:
            try:
                prepare_queries(self._semantic, queries, scope)
            except Exception as exc:
                self._fail(exc)

    def search(
        self, query: str, k: int = 5, category: str | None = None, threshold: float = 0.0
    ) -> tuple[list[RetrievedPassage], int]:
        pool = min(max(k * 3, 15), 50)
        keyword_hits, keyword_ms = self._keyword.search(query, k=pool, category=category)
        if self.fell_back:
            count("keyword_fallbacks")
            return keyword_hits[:k], keyword_ms
        try:
            semantic_hits, semantic_ms = self._semantic.search(
                query, k=pool, category=category, threshold=threshold
            )
        except Exception as exc:  # provider refused or unreachable: keyword results only
            self._fail(exc)
            count("keyword_fallbacks")
            return keyword_hits[:k], keyword_ms
        merged: dict[str, RetrievedPassage] = {}
        scores: dict[str, float] = {}
        for hits in (semantic_hits, keyword_hits):
            for rank, hit in enumerate(hits, start=1):
                scores[hit.chunk_id] = scores.get(hit.chunk_id, 0.0) + 1.0 / (self.RRF_K + rank)
                if hit.chunk_id in merged:
                    merged[hit.chunk_id].matched_by = sorted(
                        {*merged[hit.chunk_id].matched_by, *hit.matched_by}
                    )
                else:
                    merged[hit.chunk_id] = hit
        ranked = sorted(merged.values(), key=lambda p: scores[p.chunk_id], reverse=True)[:k]
        for hit in ranked:
            hit.similarity = scores[hit.chunk_id]  # fused rank score, not a cosine similarity
            hit.retrieval_mode = "hybrid"
        return ranked, semantic_ms + keyword_ms


SEARCH_MODES = ("semantic", "keyword", "hybrid")


def build_retriever(
    requested: str,
    db: Any,
    embedder_factory: Callable[[], EmbeddingProvider],
    paused: bool = False,
) -> Any:
    """The retriever for a requested mode, with a safe fallback to keyword matching.

    The result has `requested`, `mode` (what actually ran) and `fallback_reason`.
    """
    keyword = KeywordRetriever(db)
    if requested == "keyword":
        return keyword
    if paused:
        keyword.requested = requested
        keyword.fallback_reason = "Embedding access is paused or the provider stop is unreadable."
        return keyword
    vector = VectorRetriever(db=db, embedder=embedder_factory())
    if requested == "hybrid":
        return HybridRetriever(vector, keyword)
    return FallbackRetriever(vector, keyword)
