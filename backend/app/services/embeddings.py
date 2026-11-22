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

import logging
import time
from collections.abc import Callable
from typing import Protocol

from pydantic import BaseModel

from app.core.config import get_settings

logger = logging.getLogger(__name__)

# voyage-4-lite defaults (verified against Voyage AI docs; matches the
# vector(1024) column in supabase/migrations).
VOYAGE_DEFAULT_DIMENSION = 1024

# Well below the API cap of 1,000 texts; bounds request size and memory.
DEFAULT_BATCH_SIZE = 128
MAX_ATTEMPTS = 5
BACKOFF_BASE_SECONDS = 2.0


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
    ) -> None:
        self._model = model
        self._api_key = api_key
        self.dimension = dimension
        self.batch_size = max(1, batch_size)
        self._sleep = sleep
        self.max_attempts = max(1, max_attempts)
        self.total_tokens_used = 0

    def _client(self) -> object:
        import voyageai

        # api_key=None falls back to the VOYAGE_API_KEY environment variable.
        return voyageai.Client(api_key=self._client_key(), timeout=30, max_retries=0)

    def _client_key(self) -> str | None:
        return self._api_key or None

    def _embed_batch(self, texts: list[str], input_type: str) -> EmbeddingResult:
        from voyageai import error

        retryable = (
            error.RateLimitError,
            error.APIConnectionError,
            error.ServerError,
            error.ServiceUnavailableError,
            error.Timeout,
        )
        last_error: Exception | None = None
        for attempt in range(self.max_attempts):
            try:
                result = self._client().embed(
                    texts,
                    model=self._model,
                    input_type=input_type,
                    truncation=False,
                    output_dimension=self.dimension,
                )
                embeddings = [list(row) for row in result.embeddings]
                if len(embeddings) != len(texts):
                    raise RuntimeError("Embedding response count does not match request")
                for row in embeddings:
                    if len(row) != self.dimension:
                        raise RuntimeError(
                            f"Embedding dimension mismatch: model '{self._model}' returned "
                            f"{len(row)} dimensions, expected {self.dimension}. "
                            "Update the vector column or the provider dimension together."
                        )
                self.total_tokens_used += result.total_tokens
                return EmbeddingResult(embeddings=embeddings, total_tokens=result.total_tokens)
            except retryable as exc:
                last_error = exc
                if self.max_attempts == 1:
                    raise
                if attempt + 1 == self.max_attempts:
                    break
                wait = BACKOFF_BASE_SECONDS * (2**attempt)
                logger.warning(
                    "Voyage embed attempt %d/%d failed (%s); retrying in %.0fs",
                    attempt + 1,
                    self.max_attempts,
                    type(exc).__name__,
                    wait,
                )
                self._sleep(wait)
        raise RuntimeError(
            f"Voyage embedding failed after {self.max_attempts} attempts: "
            f"{type(last_error).__name__}"
        ) from last_error

    def embed_documents(self, texts: list[str]) -> EmbeddingResult:
        """Embed documents in bounded batches; tokens are summed per batch."""
        embeddings: list[list[float]] = []
        total_tokens = 0
        for start in range(0, len(texts), self.batch_size):
            batch = texts[start : start + self.batch_size]
            result = self._embed_batch(batch, input_type="document")
            embeddings.extend(result.embeddings)
            total_tokens += result.total_tokens
        return EmbeddingResult(embeddings=embeddings, total_tokens=total_tokens)

    def embed_query(self, text: str) -> list[float]:
        """Embed one retrieval query."""
        return self._embed_batch([text], input_type="query").embeddings[0]


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
    )
