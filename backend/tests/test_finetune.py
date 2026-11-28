"""Offline tests for the fine-tuning dataset module."""

from __future__ import annotations

import pytest

from app.ai.finetune.claims import classify_claim
from app.ai.finetune.cleaning import (
    clean_chunk_text,
    score_text,
    strip_heading_prefix,
    tidy_quote,
    trim_to_sentence_end,
    trim_to_sentence_start,
)
from app.ai.finetune.cpt import build_cpt_documents
from app.ai.finetune.dedupe import find_duplicates
from app.ai.finetune.licensing import decision_for
from app.ai.finetune.models import (
    BookRecord,
    ChunkRecord,
    CleanChunk,
    LicenceDecision,
    QualityScore,
    SplitAssignment,
)
from app.ai.finetune.pilot import build_pilot
from app.ai.finetune.reader import ReadOnlyKnowledgeReader, ReadOnlyViolation, _checked_columns
from app.ai.finetune.sft import build_sft_example, validate_example
from app.ai.finetune.splits import assign_splits


def make_book(
    *,
    book_id: str = "book-1",
    title: str = "A Test Book",
    author: str | None = "A. Teste",
    category: str = "materia_medica",
    content_hash: str = "a" * 64,
) -> BookRecord:
    return BookRecord(
        id=book_id,
        title=title,
        author=author,
        publisher=None,
        publication_year=None,
        language="en",
        category=category,
        source_filename="test.pdf",
        source_uri=None,
        content_hash=content_hash,
        section_count=1,
        chunk_count=1,
    )


def make_clean_chunk(
    *,
    text: str,
    book: BookRecord | None = None,
    chunk_index: int = 0,
    metadata: dict | None = None,
) -> CleanChunk:
    book = book or make_book()
    chunk = ChunkRecord(
        id=f"chunk-{book.id}-{chunk_index}",
        book_id=book.id,
        section_id=None,
        chunk_index=chunk_index,
        content=text,
        content_hash="b" * 64,
        token_count=max(1, len(text) // 4),
        metadata=metadata or {"page_start": 1, "page_end": 1},
    )
    quality = QualityScore(
        characters=len(text),
        words=len(text.split()),
        alphabetic_ratio=0.8,
        issues=(),
        usable=True,
        reason="ok",
    )
    return CleanChunk(
        chunk=chunk,
        book=book,
        section=None,
        text=text,
        removed=(),
        quality=quality,
    )


def cleared_licence(display_author: str = "A. Teste") -> LicenceDecision:
    return LicenceDecision(
        status="cleared_public_domain",
        basis="test",
        evidence=("test",),
        author_death_year=1868,
        legal_review="required_before_redistribution",
        exportable=True,
        display_author=display_author,
    )


# ---------------------------------------------------------------------------
# Cleaning
# ---------------------------------------------------------------------------


def test_cleaning_removes_watermarks_and_running_headers() -> None:
    raw = (
        "www.drbidani.co.nr\n"
        "Dr. Bidani's Centre for Homoeopathy\n"
        "MEASLES, MORBIL.LI.                 17\n"
        "Aconite is to be continued while the symptoms remain.\n"
        "APHTHA.                   37\n"
        "The patient improves.\n"
    )
    result = clean_chunk_text(raw)
    assert "drbidani" not in result.text.lower()
    assert "MEASLES" not in result.text
    assert "APHTHA" not in result.text
    assert "Aconite is to be continued" in result.text
    assert {"digitisation_marker", "running_header"}.issubset(set(result.removed))


def test_cleaning_rejoins_hyphenated_line_breaks() -> None:
    result = clean_chunk_text("A long inflam-\nmation of the liver.")
    assert result.text == "A long inflammation of the liver."


def test_cleaning_removes_contact_details_and_urls() -> None:
    result = clean_chunk_text("See http://example.com for details.\nmail@example.com\nBody text.")
    assert "http" not in result.text
    assert "mail@example.com" not in result.text
    assert "Body text." in result.text


def test_quality_rejects_short_boilerplate() -> None:
    score = score_text("PSORA.", min_chars=160)
    assert not score.usable
    assert "too_short" in score.issues


def test_quality_accepts_substantive_prose() -> None:
    text = (
        "The remedy produces a sudden and violent train of symptoms, with great fear, "
        "restlessness and a rapid pulse. The patient is worse in a warm room and better "
        "in the open air. These observations are recorded in the historical source."
    )
    score = score_text(text, min_chars=160)
    assert score.usable


def test_strip_heading_prefix_and_sentence_helpers() -> None:
    text = "== ACONITUM ==\nACONITUM NAPELLUS\n\nThe remedy acts quickly."
    assert strip_heading_prefix(text, "ACONITUM NAPELLUS") == "The remedy acts quickly."
    assert trim_to_sentence_start("norrhagia, the patient was seen. He improved.") == (
        "He improved."
    )
    assert trim_to_sentence_end("A complete sentence. A partial fragment") == (
        "A complete sentence."
    )
    assert tidy_quote("Line one,\nline two.") == "Line one, line two."


# ---------------------------------------------------------------------------
# Read-only guard
# ---------------------------------------------------------------------------


def test_reader_rejects_embedding_and_raw_text() -> None:
    with pytest.raises(ReadOnlyViolation):
        _checked_columns(("id", "embedding"))
    with pytest.raises(ReadOnlyViolation):
        _checked_columns("id,raw_text")


def test_reader_rejects_non_knowledge_tables() -> None:
    reader = ReadOnlyKnowledgeReader(object())
    with pytest.raises(ReadOnlyViolation):
        reader._table("patients")


# ---------------------------------------------------------------------------
# Licence gate
# ---------------------------------------------------------------------------


def test_licence_gate_blocks_unknown_hash() -> None:
    decision = decision_for("f" * 64)
    assert decision.status == "blocked_unverified"
    assert not decision.exportable


def test_licence_gate_clears_a_known_public_domain_book() -> None:
    decision = decision_for("aa7bc8b98ac71942688f760f673c68c7cd5f9765c21e1c38c7c83690b40059c6")
    assert decision.cleared
    assert decision.exportable
    assert decision.display_author == "A. Teste"


def test_licence_gate_keeps_the_modern_organon_translation_blocked() -> None:
    decision = decision_for("87c0ebcccbb0857bc4667eec8c6c4b36e6c28f264907768762875c5bdf1d84c1")
    assert decision.status == "blocked_copyright"
    assert not decision.exportable


# ---------------------------------------------------------------------------
# Splits and deduplication
# ---------------------------------------------------------------------------


def test_splits_are_book_level_and_deterministic() -> None:
    books = [
        make_book(book_id=f"book-{index}", title=f"Book {index}", content_hash=f"{index:064d}")
        for index in range(1, 8)
    ]
    first = assign_splits(books)
    second = assign_splits(list(reversed(books)))
    assert [item.book_id for item in first] == [item.book_id for item in second]
    assert len({item.book_id for item in first}) == len(books)
    assert {item.split for item in first} == {"train", "validation", "test"}


def test_splits_keep_small_corpora_in_training() -> None:
    books = [make_book(book_id=f"book-{index}", content_hash=f"{index:064d}") for index in range(2)]
    assignments = assign_splits(books)
    assert {item.split for item in assignments} == {"train"}


def test_dedupe_finds_exact_and_normalised_copies() -> None:
    items = [
        ("a", "The same text, repeated."),
        ("b", "The same text, repeated."),
        ("c", "THE SAME TEXT REPEATED"),
        ("d", "A completely different passage about another remedy."),
    ]
    groups, assigned = find_duplicates(items)
    assert "b" in assigned
    assert assigned["b"][1] == "exact"
    assert "c" in assigned
    assert assigned["c"][1] == "normalised"
    assert "d" not in assigned
    assert groups


# ---------------------------------------------------------------------------
# SFT construction and verification
# ---------------------------------------------------------------------------


def test_sft_example_passes_validation_and_rejects_a_fabricated_quote() -> None:
    text = (
        "The remedy is described as producing sudden violent symptoms with great fear "
        "and restlessness. The patient is worse in a warm room and better in the open air."
    )
    clean = make_clean_chunk(text=text, metadata={"remedy": "ACONITUM", "page_start": 12})
    licence = cleared_licence()
    example = build_sft_example(
        example_id="sft-test-1",
        question="What does the source record about Aconitum?",
        answer_quote=text,
        clean_chunk=clean,
        licence=licence,
        classification=classify_claim(text),
        question_type="remedy_profile",
    )
    assert validate_example(example, clean, licence) == []

    example["metadata"]["answer_quote"] = "A sentence that is not in the source."
    assert "quote_not_in_source" in validate_example(example, clean, licence)


def test_pilot_builds_verified_examples_from_cleared_sources() -> None:
    book = make_book()
    body = (
        "The remedy produces sudden violent symptoms with great fear and restlessness. "
        "The patient is worse in a warm room and better in the open air. "
        "These observations are recorded in the historical source. "
    ) * 3
    clean = make_clean_chunk(
        text=f"ACONITUM NAPELLUS\n\n{body}",
        book=book,
        metadata={"remedy": "ACONITUM NAPELLUS", "page_start": 4, "page_end": 4},
    )
    result = build_pilot([clean], {book.content_hash: cleared_licence()}, target=1)
    assert len(result.examples) == 1
    assert result.verification["failed"] == 0
    example = result.examples[0]
    assert "Aconitum Napellus" in example["messages"][1]["content"]
    assert example["metadata"]["citation"]["page_start"] == 4
    assert example["metadata"]["evidence"]["evidence_class"] == "historical_homeopathic_claim"


# ---------------------------------------------------------------------------
# CPT construction
# ---------------------------------------------------------------------------


def test_cpt_documents_preserve_book_and_split_provenance() -> None:
    book = make_book()
    chunks = [
        make_clean_chunk(
            text=f"Paragraph {index}. " + "The remedy acts on the whole constitution. " * 4,
            book=book,
            chunk_index=index,
        )
        for index in range(3)
    ]
    assignment = SplitAssignment(
        book_id=book.id,
        content_hash=book.content_hash,
        title=book.title,
        category=book.category,
        split="train",
        reason="test",
    )
    documents = build_cpt_documents(
        chunks, [assignment], {book.content_hash: cleared_licence()}
    )
    assert len(documents["train"]) == 1
    document = documents["train"][0]
    assert document["chunk_range"] == {"start": 0, "end": 2}
    assert len(document["chunk_hashes"]) == 3
    assert document["licence"]["status"] == "cleared_public_domain"
    assert document["book"]["content_hash"] == book.content_hash
