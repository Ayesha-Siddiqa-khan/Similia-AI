"""Offline fault injection: no PDF, tokenizer download, provider or database calls."""

from pathlib import Path
from types import SimpleNamespace
from typing import Any
from urllib.parse import urlsplit

import pytest
from tokenizers import Tokenizer, models, pre_tokenizers
from voyageai import error

from app.ai.ingestion.adaptive import TokenCounter, make_chunks, processing_parts, structural_units
from app.ai.ingestion.local import batches, inventory, read_json
from app.ai.ingestion.resumable import Journal, Paused, ResumableRunner, retry_delay
from app.services.embeddings import VoyageEmbeddingProvider


def plan_fixture(count: int = 6) -> dict[str, Any]:
    chunks = []
    for i in range(count):
        chunks.append(
            {
                "id": str(i),
                "chunk_index": i,
                "content": f"text {i}",
                "content_hash": f"hash-{i}",
                "token_count": 20,
                "section_ordinal": i,
                "metadata": {
                    "processing_part": 1,
                    "page_start": i + 1,
                    "page_end": i + 1,
                    "section": f"Section {i}",
                    "source_byte_start": i * 10,
                    "source_byte_end": (i + 1) * 10,
                    "source_token_start": i * 20,
                    "source_token_end": (i + 1) * 20,
                },
            }
        )
    return {
        "book": {
            "file_hash": "source-hash",
            "filename": "synthetic.pdf",
            "title": "Test",
            "text_bytes": count * 10,
            "pdf_bytes": 100,
            "original_tokens": count * 20,
            "total_pages": count,
        },
        "chunks": chunks,
        "sections": [],
        "parts": [],
        "plan_hash": "plan-hash",
    }


class FakeSink:
    def __init__(self) -> None:
        self.stored: set[str] = set()
        self.fail = False
        self.uncertain_commit = False

    def prepare(self, plan: dict[str, Any]) -> tuple[str, str]:
        return "book-id", "job-id"

    def verified(self, chunks: list[dict[str, Any]]) -> set[str]:
        return self.stored & {c["id"] for c in chunks}

    def commit(self, chunks: list[dict[str, Any]], vectors: list[list[float]]) -> None:
        assert len(chunks) == len(vectors)
        if self.fail:
            raise ConnectionError("Database unavailable")
        self.stored.update(c["id"] for c in chunks)
        if self.uncertain_commit:
            self.uncertain_commit = False
            raise ConnectionError("Lost database response after commit")

    def progress(self, job_id: str, values: dict[str, Any]) -> None:
        pass


class FakeEmbedder:
    def __init__(self, failures: list[Exception] | None = None) -> None:
        self.calls = 0
        self.failures = failures or []

    def embed_documents(self, texts: list[str]) -> Any:
        self.calls += 1
        if self.failures:
            raise self.failures.pop(0)
        return SimpleNamespace(
            embeddings=[[0.01] * 1024 for _ in texts], total_tokens=len(texts) * 20
        )


def runner(path: Path, sink: FakeSink, embedder: FakeEmbedder, **kwargs: Any) -> ResumableRunner:
    return ResumableRunner(
        sink, embedder, path, max_chunks=2, interval=0, sleep=lambda _: None, **kwargs
    )


def test_database_failure_replays_cached_vectors_after_restart(tmp_path: Path) -> None:
    sink, embedder, plan = FakeSink(), FakeEmbedder(), plan_fixture()
    first = runner(tmp_path, sink, embedder)
    sink.fail = True
    with pytest.raises(ConnectionError):
        first.run_book(plan)
    assert embedder.calls == 1
    first.journal.connection.close()
    sink.fail = False
    resumed = runner(tmp_path, sink, embedder)
    resumed.run_book(plan)
    assert len(sink.stored) == 6
    assert embedder.calls == 3  # first batch's vectors came from the durable cache
    resumed.run_book(plan)
    assert embedder.calls == 3
    assert resumed.journal.usage()["provider_reported_tokens"] == 120


def test_lost_database_ack_does_not_reembed(tmp_path: Path) -> None:
    sink, embedder, plan = FakeSink(), FakeEmbedder(), plan_fixture(2)
    sink.uncertain_commit = True
    first = runner(tmp_path, sink, embedder)
    with pytest.raises(ConnectionError):
        first.run_book(plan)
    runner(tmp_path, sink, embedder).run_book(plan)
    assert embedder.calls == 1
    assert len(sink.stored) == 2


def test_budget_is_durable_and_stops_before_request(tmp_path: Path) -> None:
    sink, embedder, plan = FakeSink(), FakeEmbedder(), plan_fixture()
    first = runner(tmp_path, sink, embedder, budget=100)
    with pytest.raises(Paused, match="budget"):
        first.run_book(plan)
    assert embedder.calls == 1
    assert len(sink.stored) == 2
    with pytest.raises(Paused, match="budget"):
        runner(tmp_path, sink, embedder, budget=100).run_book(plan)
    assert embedder.calls == 1
    progress = read_json(tmp_path / "ingestion_progress.json")
    assert progress["books"][0]["completion_percent"] < 100


def test_interrupted_provider_request_is_not_silently_replayed(tmp_path: Path) -> None:
    journal = Journal(tmp_path / "checkpoint.sqlite3")
    journal.reserve("interrupted-batch", 50, 100)
    journal.connection.close()
    sink, embedder = FakeSink(), FakeEmbedder()
    with pytest.raises(Paused, match="manual reconciliation"):
        runner(tmp_path, sink, embedder).run_book(plan_fixture())
    assert embedder.calls == 0


def test_rate_limit_retry_after_and_usage(tmp_path: Path) -> None:
    exc = error.RateLimitError("rate limited", http_status=429, headers={"Retry-After": "45"})
    embedder, sink = FakeEmbedder([exc]), FakeSink()
    sleeps: list[float] = []
    worker = runner(tmp_path, sink, embedder)
    worker.sleep = sleeps.append
    worker.run_book(plan_fixture(2))
    assert embedder.calls == 2
    assert max(sleeps) >= 44
    assert worker.journal.usage()["failed_requests"] == 1
    assert worker.journal.usage()["budget_charged_tokens"] == 40
    assert retry_delay(exc, 1) == 45


def test_a_429_that_mentions_quota_is_retried_after_a_real_wait_before_stopping(
    tmp_path: Path,
) -> None:
    always = [error.RateLimitError("quota exhausted", http_status=429) for _ in range(20)]
    embedder = FakeEmbedder(always)
    worker = runner(tmp_path, FakeSink(), embedder)
    sleeps: list[float] = []
    worker.sleep = sleeps.append
    with pytest.raises(Paused, match="HTTP 429") as stopped:
        worker.run_book(plan_fixture())
    assert embedder.calls >= 3  # not stopped by the keyword on the first answer
    assert max(sleeps) >= 60  # waited at least a minute between tries
    assert worker.journal.usage()["budget_charged_tokens"] == 0  # a 429 is never charged
    assert "provider said" in str(stopped.value)


def test_a_429_that_clears_after_a_wait_completes_the_book(tmp_path: Path) -> None:
    flaky = [error.RateLimitError("Rate limit exceeded", http_status=429)]
    embedder, sink = FakeEmbedder(flaky), FakeSink()
    worker = runner(tmp_path, sink, embedder)
    waits: list[float] = []
    worker.sleep = waits.append
    worker.run_book(plan_fixture(2))
    assert len(sink.stored) == 2 and max(waits) >= 59


def test_a_billing_error_stops_at_once_without_retry(tmp_path: Path) -> None:
    exc = error.InvalidRequestError("payment required: add billing", http_status=402)
    embedder = FakeEmbedder([exc])
    with pytest.raises(Paused, match="HTTP 402"):
        runner(tmp_path, FakeSink(), embedder).run_book(plan_fixture())
    assert embedder.calls == 1


def test_the_stop_message_never_contains_a_key(tmp_path: Path) -> None:
    exc = error.RateLimitError("bad key al-abcdef1234567890XYZ", http_status=429)
    embedder = FakeEmbedder([exc for _ in range(20)])
    worker = runner(tmp_path, FakeSink(), embedder)
    with pytest.raises(Paused) as stopped:
        worker.run_book(plan_fixture())
    assert "al-abcdef1234567890XYZ" not in str(stopped.value)


def test_oversize_batch_is_split_dynamically(tmp_path: Path) -> None:
    embedder = FakeEmbedder([error.InvalidRequestError("too large", http_status=413)])
    worker = runner(tmp_path, FakeSink(), embedder)
    worker.run_book(plan_fixture(2))
    assert embedder.calls == 3
    assert worker.journal.usage()["provider_reported_tokens"] == 40


def test_representative_sample_is_not_marked_complete(tmp_path: Path) -> None:
    sink, embedder, plan = FakeSink(), FakeEmbedder(), plan_fixture(10)
    worker = runner(tmp_path, sink, embedder)
    with pytest.raises(Paused, match="Representative sample"):
        worker.run_book(plan, sample_limit=4)
    assert sink.stored == {"0", "3", "6", "9"}
    assert worker.journal.get("sample:plan-hash") is True
    worker.run_book(plan)
    assert len(sink.stored) == 10
    assert worker.journal.usage()["provider_reported_tokens"] == 200


def test_changed_plan_is_rejected(tmp_path: Path) -> None:
    sink, embedder, plan = FakeSink(), FakeEmbedder(), plan_fixture(2)
    worker = runner(tmp_path, sink, embedder)
    worker.run_book(plan)
    plan["plan_hash"] = "different"
    with pytest.raises(Paused, match="Plan changed"):
        worker.run_book(plan)
    assert embedder.calls == 1


def test_structural_boundaries_and_token_batches() -> None:
    units = structural_units("Para - 1\nShort.\nPrara 2\nSecond.\n99PARA-3\nThird.", "organon")
    assert [u.identifier for u in units if u.kind == "aphorism"] == ["1", "2", "3"]
    units = structural_units(
        "MIND\n  Anxiety: acon., bell.\n    night: ars.\nHEAD\n Pain: bry.", "repertory"
    )
    assert next(u for u in units if u.heading == "night").path == ["MIND", "Anxiety", "night"]
    chunks = plan_fixture()["chunks"]
    assert [len(b) for b in batches(chunks, max_tokens=75)] == [2, 2, 2]
    parts = processing_parts(chunks, 60, 120, threshold=100)
    assert len(parts) == 2
    assert parts[0]["source_byte_end"] == parts[1]["source_byte_start"]
    assert parts[0]["chunk_end"] == parts[1]["chunk_start"]


@pytest.mark.parametrize(
    "key,host", [("al-synthetic", "ai.mongodb.com"), ("pa-synthetic", "api.voyageai.com")]
)
def test_sdk_automatic_endpoint_selection(key: str, host: str) -> None:
    client = VoyageEmbeddingProvider("voyage-4-lite", key)._client()
    assert urlsplit(client._params["base_url"]).hostname == host


def test_token_splitting_preserves_source_and_remedy_boundaries(tmp_path: Path) -> None:
    tokenizer = Tokenizer(models.WordLevel({"[UNK]": 0}, unk_token="[UNK]"))
    tokenizer.pre_tokenizer = pre_tokenizers.Whitespace()
    path = tmp_path / "tokenizer.json"
    tokenizer.save(str(path))
    counter = TokenCounter(path)
    text = "ACONITUM\nMind\n" + "A complete sentence about anxiety. " * 190
    text += "\n\nBELLADONNA\nHead\nA short complete section.\nPDFPDF BOOKSBOOKS\n"
    pages = [{"char_start": 0}]
    sections, chunks = make_chunks(text, pages, "materia_medica", counter, "source")
    assert len(chunks) > 2
    assert any(s["kind"] == "artifact" for s in sections)
    for chunk in chunks:
        meta = chunk["metadata"]
        assert chunk["token_count"] == counter.count(chunk["content"])
        assert chunk["token_count"] <= 650
        original = text[meta["source_char_start"] : meta["source_char_end"]]
        assert chunk["content"].endswith(original)
        assert not ("ACONITUM" in chunk["content"] and "BELLADONNA" in chunk["content"])
        assert "PDFPDF" not in chunk["content"]


def test_aphorisms_are_not_merged(tmp_path: Path) -> None:
    tokenizer = Tokenizer(models.WordLevel({"[UNK]": 0}, unk_token="[UNK]"))
    tokenizer.pre_tokenizer = pre_tokenizers.Whitespace()
    path = tmp_path / "tokenizer.json"
    tokenizer.save(str(path))
    text = "Para - 1\nFirst aphorism.\nPara - 2\nSecond aphorism."
    _, chunks = make_chunks(text, [{"char_start": 0}], "organon", TokenCounter(path), "source")
    assert len(chunks) == 2
    assert [c["metadata"]["aphorism"] for c in chunks] == ["1", "2"]


def test_running_header_does_not_relabel_previous_remedy(tmp_path: Path) -> None:
    tokenizer = Tokenizer(models.WordLevel({"[UNK]": 0}, unk_token="[UNK]"))
    tokenizer.pre_tokenizer = pre_tokenizers.Whitespace()
    path = tmp_path / "tokenizer.json"
    tokenizer.save(str(path))
    first = "SENEGA 528\nSenega. Start of its description.\n"
    second = (
        "CANTHARIDES 529\nSenega does not admit of other applications.\n"
        "Cantharides. Description of the next remedy.\nBOOKS HOMOEOPATHIC AH\nAH\n"
    )
    pages = [{"char_start": 0, "text": first}, {"char_start": len(first) + 1, "text": second}]
    _, chunks = make_chunks(
        first + "\f" + second, pages, "materia_medica", TokenCounter(path), "source"
    )
    previous = next(c for c in chunks if "Senega does not" in c["content"])
    assert previous["metadata"]["remedy"] == "SENEGA"
    following = next(c for c in chunks if "Description of the next remedy" in c["content"])
    assert following["metadata"]["remedy"] == "CANTHARIDES"
    assert all("BOOKS HOMOEOPATHIC" not in c["content"] for c in chunks)


def test_parts_checkpoint_and_recover_independently(tmp_path: Path) -> None:
    class PartSink(FakeSink):
        fail_part_two = True

        def commit(self, chunks: list[dict[str, Any]], vectors: list[list[float]]) -> None:
            if chunks[0]["metadata"]["processing_part"] == 2 and self.fail_part_two:
                raise ConnectionError("Part 2 database failure")
            super().commit(chunks, vectors)

    plan, sink, embedder = plan_fixture(4), PartSink(), FakeEmbedder()
    for chunk in plan["chunks"][2:]:
        chunk["metadata"]["processing_part"] = 2
    worker = runner(tmp_path, sink, embedder)
    with pytest.raises(ConnectionError):
        worker.run_book(plan)
    assert sink.stored == {"0", "1"}
    assert worker.journal.get("part:plan-hash:1")["completed_batch_ids"]
    assert worker.journal.get("part:plan-hash:2") is None
    sink.fail_part_two = False
    worker.run_book(plan)
    assert sink.stored == {"0", "1", "2", "3"}
    assert embedder.calls == 2  # Part 2 reuses the pre-failure vector outbox.
    assert worker.journal.get("part:plan-hash:2")["completed_batch_ids"]
    assert worker.journal.usage("batch:plan-hash:1:")["provider_reported_tokens"] == 40
    assert worker.journal.usage("batch:plan-hash:2:")["provider_reported_tokens"] == 40


def test_added_books_preserve_original_exclusion_and_padded_indexes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Page:
        def __init__(self, text: str) -> None:
            self.text = text

        def get_text(self, *args: Any, **kwargs: Any) -> str:
            return self.text

        def get_images(self) -> list[Any]:
            return []

    class Document:
        needs_pass = False
        metadata: dict[str, Any] = {}

        def __init__(self, path: Path) -> None:
            count = 100 if path.stem == "Kent-Repertory" else 10
            self.pages = [Page((" " * 50 + "Readable index entry 12\n") * count)]

        def __enter__(self) -> "Document":
            return self

        def __exit__(self, *args: Any) -> None:
            pass

        def __iter__(self):
            return iter(self.pages)

        def __len__(self) -> int:
            return len(self.pages)

        def get_toc(self) -> list[Any]:
            return []

    class Counter:
        hash = "test-tokenizer"

        def count(self, text: str) -> int:
            return len(text.split())

    monkeypatch.setattr("app.ai.ingestion.local.pymupdf.open", Document)
    source = tmp_path / "books"
    source.mkdir()
    for name in ("First", "Second", "Kent-Repertory"):
        (source / f"{name}.pdf").write_bytes(name.encode())
    output = tmp_path / "reports"
    first = inventory(Counter(), source, output)
    kent = next(b["file_hash"] for b in first["books"] if "Kent" in b["filename"])
    (source / "New-book.pdf").write_bytes(b"new-source")
    expanded = inventory(Counter(), source, output, include_added=True)
    assert len(expanded["books"]) == 4
    assert kent not in expanded["selected_hashes"]
    assert len(expanded["selected_hashes"]) == 3
    assert all(b["valid"] for b in expanded["books"])


def test_font_remedy_boundaries_ignore_capital_symptom_fragments() -> None:
    from app.ai.ingestion.adaptive import structural_units

    text = "Aconitum napellus\nG - BURNING\nMind\nFearful.\nBelladonna\nHead\nPain."
    starts = {0: "Aconitum napellus", text.index("Belladonna"): "Belladonna"}
    units = structural_units(text, "materia_medica", remedy_starts=starts, strict_remedies=True)
    assert [u.identifier for u in units if u.kind == "remedy"] == [
        "Aconitum napellus",
        "Belladonna",
    ]
    assert next(u for u in units if u.heading == "Mind").identifier == "Aconitum napellus"
