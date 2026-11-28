"""Embedding provider abstraction — Voyage AI by MongoDB (official Python SDK).

Model facts verified against current docs (docs.voyageai.com, Oct 2026):
- voyage-4-lite: 1024 output dimensions (default), 32,000-token context,
  max 1,000 texts per request (total-token cap: 1M for voyage-4-lite).
- voyageai.Client().embed(...) returns EmbeddingsObject with .embeddings
  and .total_tokens.
- input_type="document" for stored text, "query" for retrieval queries.

API key: created in the MongoDB Atlas UI under "AI Model APIs" -> "Create
model API key" and exported as VOYAGE_API_KEY. No MongoDB database, Atlas
CLI, or mongosh is involved in this architecture.
"""

import hmac
import logging
import math
import os
import random
import sqlite3
import time
from collections import OrderedDict
from collections.abc import Callable
from email.utils import parsedate_to_datetime
from functools import lru_cache
from pathlib import Path
from threading import Lock
from typing import Protocol

from pydantic import BaseModel

from app.core.config import get_settings
from app.core.paths import data_dir
from app.services.rag_metrics import count
from app.services.voyage_budget import VoyageBudget

logger = logging.getLogger(__name__)

# voyage-4-lite defaults (verified against Voyage AI docs; matches the
# vector(1024) column in supabase/migrations).
VOYAGE_DEFAULT_DIMENSION = 1024

# Well below the API cap of 1,000 texts; bounds request size and memory.
DEFAULT_BATCH_SIZE = 128
MAX_ATTEMPTS = 5
BACKOFF_BASE_SECONDS = 2.0
QUERY_ATTEMPTS = 2
_CACHE: OrderedDict[bytes, tuple[float, tuple[float, ...]]] = OrderedDict()
_CACHE_LOCK = Lock()
_CACHE_SECRET = os.urandom(32)
_SCOPE_LOCKS = [Lock() for _ in range(32)]


@lru_cache
def _tokenizer(model: str):
    path = data_dir() / "reports" / "ingestion" / "tokenizer" / "tokenizer.json"
    if model == "voyage-4-lite" and path.is_file():
        from tokenizers import Tokenizer

        counter = Tokenizer.from_file(str(path))
        counter.no_padding()
        counter.no_truncation()
        return counter
    return None


def _estimate_tokens(model: str, texts: list[str]) -> int:
    counter = _tokenizer(model)
    if counter is not None:
        return max(1, sum(len(part.ids) for part in counter.encode_batch(texts)))
    return max(1, sum(len(text.encode("utf-8")) for text in texts))


def quota_exhausted(exc: BaseException) -> bool:
    detail = str(exc).lower()
    return any(phrase in detail for phrase in (
        "quota exceeded", "quota exhausted", "insufficient quota", "billing",
        "credit", "payment", "free allowance",
    ))


def _retry_after(exc: BaseException) -> float | None:
    headers = getattr(exc, "headers", None) or {}
    value = headers.get("Retry-After") or headers.get("retry-after")
    if not value:
        return None
    try:
        seconds = float(value)
    except (TypeError, ValueError):
        try:
            seconds = parsedate_to_datetime(value).timestamp() - time.time()
        except (TypeError, ValueError, OverflowError):
            return math.inf
    return max(0, seconds) if math.isfinite(seconds) else math.inf


class EmbeddingResponseError(RuntimeError):
    """Voyage answered, but the returned vectors cannot be used."""


class EmbeddingResult(BaseModel):
    """Embeddings plus the real token usage reported by the API."""

    embeddings: list[list[float]]
    total_tokens: int


class EmbeddingProvider(Protocol):
    """Anything that can embed documents and queries."""

    dimension: int

    def embed_documents(self, texts: list[str]) -> EmbeddingResult:
        """Embed a batch of documents (input_type="document")."""
        ...

    def embed_query(self, text: str) -> list[float]:
        """Embed a single query string (input_type="query")."""
        ...


class VoyageEmbeddingProvider:
    """Voyage AI embeddings via the official voyageai.Client.

    The client is constructed lazily so importing this module (and starting
    the app) never requires an API key or performs network calls. Requests
    are sent in bounded batches with exponential backoff on transient errors
    (rate limits, connection issues, 5xx).
    """

    def __init__(
        self,
        model: str,
        api_key: str,
        dimension: int = VOYAGE_DEFAULT_DIMENSION,
        batch_size: int = DEFAULT_BATCH_SIZE,
        sleep: Callable[[float], None] = time.sleep,
        max_attempts: int = MAX_ATTEMPTS,
        budget: VoyageBudget | None = None,
        query_wait_seconds: float = 15,
    ) -> None:
        self._model = model
        self._api_key = api_key
        self.dimension = dimension
        self.batch_size = max(1, batch_size)
        self._sleep = sleep
        self.max_attempts = max(1, max_attempts)
        self.total_tokens_used = 0
        self._budget = budget
        self._query_wait_seconds = query_wait_seconds

    def _client(self) -> object:
        import voyageai

        # api_key=None falls back to the VOYAGE_API_KEY environment variable.
        return voyageai.Client(api_key=self._client_key(), timeout=30, max_retries=0)

    def _client_key(self) -> str | None:
        return self._api_key or None

    def document_token_reservation(self, text: str) -> int:
        return _estimate_tokens(self._model, [text])

    @property
    def tokens_per_minute(self) -> int:
        return self._budget.tpm if self._budget else 0

    @property
    def uses_shared_budget(self) -> bool:
        return self._budget is not None

    def _embed_batch(
        self, texts: list[str], input_type: str, cancelled: Callable[[], bool] = lambda: False,
    ) -> EmbeddingResult:
        from voyageai import error

        retryable = (
            error.RateLimitError,
            error.APIConnectionError,
            error.ServerError,
            error.ServiceUnavailableError,
            error.Timeout,
        )
        attempts = self.max_attempts
        if input_type == "query" or self._budget:
            attempts = min(attempts, QUERY_ATTEMPTS)
        last_error: Exception | None = None
        estimate = _estimate_tokens(self._model, texts) if self._budget else 0
        deadline = time.monotonic() + self._query_wait_seconds
        for attempt in range(attempts):
            slot = None
            if self._budget:
                began = time.monotonic()
                try:
                    slot = self._budget.reserve(
                        estimate, max(0, deadline - began) if input_type == "query" else 65,
                        cancelled=cancelled,
                    )
                finally:
                    count("rate_wait_ms", int(1000 * (time.monotonic() - began)))
            try:
                count("embedding_requests")
                count("embedding_inputs", len(texts))
                result = self._client().embed(
                    texts,
                    model=self._model,
                    input_type=input_type,
                    truncation=False,
                    output_dimension=self.dimension,
                )
                if slot is not None and self._budget:
                    try:
                        self._budget.settle(slot, result.total_tokens)
                    except sqlite3.Error:
                        logger.warning("Voyage budget could not reconcile this reservation")
                count("embedding_tokens", result.total_tokens)
                embeddings = [list(row) for row in result.embeddings]
                if len(embeddings) != len(texts):
                    raise EmbeddingResponseError("Embedding response count does not match request")
                for row in embeddings:
                    if len(row) != self.dimension:
                        raise EmbeddingResponseError(
                            f"Embedding dimension mismatch: model '{self._model}' returned "
                            f"{len(row)} dimensions, expected {self.dimension}. "
                            "Update the vector column or the provider dimension together."
                        )
                    if input_type == "query" and (
                        not all(math.isfinite(value) for value in row) or not any(row)
                    ):
                        raise EmbeddingResponseError("Query vector is non-finite or all zero")
                self.total_tokens_used += result.total_tokens
                return EmbeddingResult(embeddings=embeddings, total_tokens=result.total_tokens)
            except retryable as exc:
                last_error = exc
                retry_after = _retry_after(exc)
                if isinstance(exc, error.RateLimitError):
                    count("embedding_http_429")
                    if quota_exhausted(exc):
                        if self._budget:
                            self._budget.defer(3600)
                        raise
                    if self._budget:
                        self._budget.defer(
                            retry_after if retry_after is not None
                            and math.isfinite(retry_after) else 20,
                        )
                if attempts == 1:
                    raise
                if attempt + 1 == attempts:
                    break
                wait = BACKOFF_BASE_SECONDS * (2**attempt)
                if retry_after is not None:
                    wait = max(wait, retry_after)
                if self._budget:
                    wait += random.uniform(0, 0.5)
                if wait > (5 if input_type == "query" else 65):
                    raise
                count("embedding_retries")
                logger.warning(
                    "Voyage embed attempt %d/%d failed (%s); retrying in %.0fs",
                    attempt + 1,
                    attempts,
                    type(exc).__name__,
                    wait,
                )
                self._sleep(wait)
        if input_type == "query" and last_error is not None:
            raise last_error
        raise RuntimeError(
            f"Voyage embedding failed after {attempts} attempts: "
            f"{type(last_error).__name__}"
        ) from last_error

    def embed_documents(
        self, texts: list[str], *, cancelled: Callable[[], bool] = lambda: False,
    ) -> EmbeddingResult:
        """Embed documents in bounded batches; tokens are summed per batch."""
        embeddings: list[list[float]] = []
        total_tokens = 0
        for start in range(0, len(texts), self.batch_size):
            batch = texts[start : start + self.batch_size]
            result = self._embed_batch(batch, input_type="document", cancelled=cancelled)
            embeddings.extend(result.embeddings)
            total_tokens += result.total_tokens
        return EmbeddingResult(embeddings=embeddings, total_tokens=total_tokens)

    def embed_query(self, text: str) -> list[float]:
        """Embed one retrieval query."""
        return self._embed_batch([text], input_type="query").embeddings[0]

    def embed_queries(self, texts: list[str], scope: str | None = None) -> dict[str, list[float]]:
        unique = list(dict.fromkeys(texts))
        if not unique:
            return {}
        if scope is None:
            return dict(zip(unique, self._embed_batch(unique, "query").embeddings, strict=True))
        with _SCOPE_LOCKS[hash(scope) % len(_SCOPE_LOCKS)]:
            keys = {
                text: hmac.digest(
                    _CACHE_SECRET, repr((scope, self._model, self.dimension, text)).encode(),
                    "sha256",
                )
                for text in unique
            }
            now = time.monotonic()
            with _CACHE_LOCK:
                found = {
                    text: list(entry[1]) for text, key in keys.items()
                    if (entry := _CACHE.get(key)) and entry[0] > now
                }
            missing = [text for text in unique if text not in found]
            count("cache_hits", len(found))
            count("cache_misses", len(missing))
            if missing:
                vectors = self._embed_batch(missing, "query").embeddings
                with _CACHE_LOCK:
                    for text, vector in zip(missing, vectors, strict=True):
                        _CACHE[keys[text]] = (time.monotonic() + 300, tuple(vector))
                        _CACHE.move_to_end(keys[text])
                        found[text] = vector
                    while len(_CACHE) > 256:
                        _CACHE.popitem(last=False)
            return found


def get_embedding_provider(
    batch_size: int = DEFAULT_BATCH_SIZE,
    max_attempts: int = MAX_ATTEMPTS,
) -> VoyageEmbeddingProvider:
    """Factory for the configured embedding provider."""
    settings = get_settings()
    return VoyageEmbeddingProvider(
        model=settings.voyage_model,
        api_key=settings.voyage_api_key,
        batch_size=batch_size,
        max_attempts=max_attempts,
        budget=_shared_budget(
            settings.embedding_requests_per_minute, settings.embedding_tokens_per_minute,
            settings.embedding_budget_path,
        ),
        query_wait_seconds=settings.embedding_query_wait_seconds,
    )


@lru_cache
def _shared_budget(rpm: int, tpm: int, path: str) -> VoyageBudget | None:
    if rpm <= 0 and tpm <= 0:
        return None
    location = Path(path) if path else Path(__file__).resolve().parents[2] / (
        ".runtime/voyage-budget.sqlite"
    )
    return VoyageBudget(location, rpm, tpm)
