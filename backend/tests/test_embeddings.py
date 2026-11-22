"""Voyage embedding provider tests with a stubbed voyageai client:
batching, retry with exponential backoff, token tracking, input types,
and the dimension guard. No network access."""

from types import SimpleNamespace

import pytest
from voyageai import error

from app.services.embeddings import (
    MAX_ATTEMPTS,
    VOYAGE_DEFAULT_DIMENSION,
    VoyageEmbeddingProvider,
)


class StubVoyageClient:
    """Mimics voyageai.Client.embed without network."""

    def __init__(self, dimension: int = VOYAGE_DEFAULT_DIMENSION, fail_times: int = 0,
                 error_cls: type = error.RateLimitError, token_per_text: int = 3) -> None:
        self.dimension = dimension
        self.fail_times = fail_times
        self.error_cls = error_cls
        self.token_per_text = token_per_text
        self.calls: list[dict] = []

    def embed(self, texts, model=None, input_type=None, truncation=True,
              output_dtype=None, output_dimension=None):
        self.calls.append({"texts": list(texts), "model": model, "input_type": input_type})
        if self.fail_times > 0:
            self.fail_times -= 1
            raise self.error_cls("simulated failure")
        embeddings = [[float(len(texts))] * self.dimension for _ in texts]
        return SimpleNamespace(embeddings=embeddings, total_tokens=len(texts) * self.token_per_text)


def make_provider(stub: StubVoyageClient, sleeps: list[float] | None = None,
                  batch_size: int = 128) -> VoyageEmbeddingProvider:
    provider = VoyageEmbeddingProvider(
        model="voyage-4-lite", api_key="test-key", batch_size=batch_size,
        sleep=(sleeps.append if sleeps is not None else lambda _s: None),
    )
    provider._client = lambda: stub  # type: ignore[method-assign]
    return provider


def test_documents_are_sent_in_bounded_batches() -> None:
    stub = StubVoyageClient()
    provider = make_provider(stub, batch_size=128)
    texts = [f"chunk {i}" for i in range(300)]
    result = provider.embed_documents(texts)
    assert len(result.embeddings) == 300
    assert [len(c["texts"]) for c in stub.calls] == [128, 128, 44]
    assert result.total_tokens == 300 * 3


def test_document_and_query_input_types() -> None:
    stub = StubVoyageClient()
    provider = make_provider(stub)
    provider.embed_documents(["doc text"])
    provider.embed_query("query text")
    assert stub.calls[0]["input_type"] == "document"
    assert stub.calls[1]["input_type"] == "query"
    assert stub.calls[1]["model"] == "voyage-4-lite"


def test_rate_limit_retries_with_exponential_backoff() -> None:
    stub = StubVoyageClient(fail_times=2)
    sleeps: list[float] = []
    provider = make_provider(stub, sleeps=sleeps)
    result = provider.embed_documents(["hello"])
    assert len(result.embeddings) == 1
    assert sleeps == [2.0, 4.0]  # exponential backoff, one per failed attempt
    assert provider.total_tokens_used == 3


def test_retries_exhausted_raises() -> None:
    stub = StubVoyageClient(fail_times=MAX_ATTEMPTS + 5)
    provider = make_provider(stub)
    with pytest.raises(RuntimeError, match=f"after {MAX_ATTEMPTS} attempts"):
        provider.embed_documents(["hello"])


def test_auth_errors_are_not_retried() -> None:
    stub = StubVoyageClient(fail_times=1, error_cls=error.AuthenticationError)
    sleeps: list[float] = []
    provider = make_provider(stub, sleeps=sleeps)
    with pytest.raises(error.AuthenticationError):
        provider.embed_documents(["hello"])
    assert sleeps == []


def test_dimension_mismatch_is_rejected() -> None:
    stub = StubVoyageClient(dimension=768)
    provider = make_provider(stub)
    with pytest.raises(RuntimeError, match="dimension mismatch"):
        provider.embed_documents(["hello"])


def test_embed_query_returns_single_vector() -> None:
    stub = StubVoyageClient()
    provider = make_provider(stub)
    vector = provider.embed_query(" Which remedy? ")
    assert len(vector) == VOYAGE_DEFAULT_DIMENSION
