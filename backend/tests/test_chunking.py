"""Category-aware chunking tests: structure detection, metadata
preservation, and size bounds for all three knowledge categories."""

import pytest

from app.ai.ingestion.chunking import MAX_CHUNK_CHARS, chunk_document
from app.ai.ingestion.extraction import PageText
from tests.sample_data import MM_SAMPLE, ORGANON_SAMPLE, REPERTORY_SAMPLE


def pages_from(text: str) -> list[PageText]:
    return [PageText(page=1, text=text)]


# ---------------------------------------------------------------------------
# Organon
# ---------------------------------------------------------------------------


def test_organon_chunks_start_with_aphorism_ids() -> None:
    result = chunk_document(pages_from(ORGANON_SAMPLE), "organon")
    aphorism_chunks = [c for c in result.chunks if c.metadata.get("aphorism_start")]
    assert aphorism_chunks, "expected aphorism chunks"
    assert aphorism_chunks[0].content.startswith("§1.")
    covered = [
        n
        for c in aphorism_chunks
        for n in range(c.metadata["aphorism_start"], c.metadata["aphorism_end"] + 1)
    ]
    assert covered == list(range(1, 8))  # every aphorism whole, in order


def test_organon_sections_are_one_per_aphorism() -> None:
    result = chunk_document(pages_from(ORGANON_SAMPLE), "organon")
    aphorism_sections = [s for s in result.sections if s.section_type == "aphorism"]
    assert [s.heading for s in aphorism_sections] == [f"§{n}" for n in range(1, 8)]
    assert all(len(s.path) == 1 for s in aphorism_sections)


def test_organon_never_splits_mid_aphorism() -> None:
    long_aphorisms = "\n\n".join(
        f"§ {n}. " + "Sentence about the remedy. " * 40 for n in range(1, 4)
    )
    result = chunk_document(pages_from(long_aphorisms), "organon")
    for chunk in result.chunks:
        if chunk.metadata.get("aphorism_start") is not None:
            assert len(chunk.content) <= MAX_CHUNK_CHARS


# ---------------------------------------------------------------------------
# Materia Medica
# ---------------------------------------------------------------------------


def test_materia_medica_sections_are_remedies() -> None:
    result = chunk_document(pages_from(MM_SAMPLE), "materia_medica")
    remedies = [s.heading for s in result.sections]
    assert "ACONITUM NAPELLUS" in remedies
    assert "ARNICA MONTANA" in remedies
    assert all(s.section_type == "remedy" for s in result.sections)


def test_materia_medica_chunks_carry_remedy_context() -> None:
    result = chunk_document(pages_from(MM_SAMPLE), "materia_medica")
    aconite_chunks = [c for c in result.chunks if c.metadata.get("remedy") == "ACONITUM NAPELLUS"]
    assert aconite_chunks
    assert all("== ACONITUM NAPELLUS ==" in c.content for c in aconite_chunks)
    assert any(c.metadata.get("symptom_heading") == "Mind" for c in aconite_chunks)
    # No chunk leaks content from the other remedy.
    assert all("ARNICA" not in c.content for c in aconite_chunks)


def test_materia_medica_oversized_paragraph_is_split_within_budget() -> None:
    huge = "ACONITUM NAPELLUS\n\n" + "Restless fear. " * 500
    result = chunk_document(pages_from(huge), "materia_medica")
    assert len(result.chunks) > 1
    assert all(len(c.content) <= MAX_CHUNK_CHARS for c in result.chunks)


# ---------------------------------------------------------------------------
# Repertory
# ---------------------------------------------------------------------------


def test_repertory_sections_are_chapters() -> None:
    result = chunk_document(pages_from(REPERTORY_SAMPLE), "repertory")
    assert [s.heading for s in result.sections] == ["CHAPTER I. MIND", "CHAPTER II. HEAD"]


def test_repertory_chunks_preserve_rubric_hierarchy() -> None:
    result = chunk_document(pages_from(REPERTORY_SAMPLE), "repertory")
    first = result.chunks[0]
    assert first.content.startswith("Path: CHAPTER I. MIND")
    assert first.metadata["rubric_path"][0] == "CHAPTER I. MIND"
    fear_chunks = [c for c in result.chunks if "Fear of death" in c.content]
    assert fear_chunks
    assert "Fear of death" in fear_chunks[0].metadata["rubric_path"]
    # Distinct complete rubrics retain their own remedy relationships.
    assert "Fear, open air, in" not in fear_chunks[0].content
    open_air = next(c for c in result.chunks if "Fear, open air, in" in c.content)
    assert open_air.metadata["rubric_path"] == ["CHAPTER I. MIND", "Fear, open air, in"]
    assert "sulph. 1" in open_air.content


def test_repertory_keeps_remedy_entries_with_their_rubric() -> None:
    result = chunk_document(pages_from(REPERTORY_SAMPLE), "repertory")
    vertigo = next(c for c in result.chunks if "Vertigo" in c.content)
    assert "bry. 2" in vertigo.content
    assert vertigo.metadata["rubric_path"] == ["CHAPTER II. HEAD", "Vertigo, rising, on"]


# ---------------------------------------------------------------------------
# Shared invariants
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("sample", "category"),
    [(ORGANON_SAMPLE, "organon"), (MM_SAMPLE, "materia_medica"), (REPERTORY_SAMPLE, "repertory")],
)
def test_chunking_is_deterministic_and_indexed(sample: str, category: str) -> None:
    first = chunk_document(pages_from(sample), category)
    second = chunk_document(pages_from(sample), category)
    assert [c.content for c in first.chunks] == [c.content for c in second.chunks]
    assert [c.chunk_index for c in first.chunks] == list(range(len(first.chunks)))
    assert all(c.content.strip() for c in first.chunks)
    assert all(c.page_start is not None and c.page_start >= 1 for c in first.chunks)
    assert len({c.content_hash for c in first.chunks}) >= 1


def test_unknown_category_rejected() -> None:
    with pytest.raises(ValueError, match="Unknown knowledge category"):
        chunk_document(pages_from(MM_SAMPLE), "homeopathy")
