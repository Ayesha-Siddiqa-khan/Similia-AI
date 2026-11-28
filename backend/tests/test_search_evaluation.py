"""The evaluation helpers: pure measurements, no patient wording, no model call."""

from app.ai.evaluation.search_modes import (
    check_citations,
    describe_passages,
    merge_query_hits,
    overlap,
)
from tests.test_case_analysis import passage


def test_overlap_counts_agreement_between_two_rankings() -> None:
    result = overlap(["a", "b", "c", "d"], ["c", "a", "x"])
    assert result["shared"] == 2 and result["only_first"] == 2 and result["only_second"] == 1
    assert result["jaccard"] == 0.4 and result["top5_shared"] == 2
    assert overlap([], [])["jaccard"] == 1.0


def test_describe_passages_counts_books_pages_and_partly_indexed_sources() -> None:
    rows = [
        {"book_id": "b1", "book_title": "A", "book_category": "organon", "page_start": 3},
        {"book_id": "b2", "book_title": "B", "book_category": "materia_medica", "page_start": None},
        {"book_id": "b2", "book_title": "B", "book_category": "materia_medica", "page_start": 9},
    ]
    summary = describe_passages(rows, {"b1": True, "b2": False})
    assert summary == {
        "passages": 3,
        "distinct_books": 2,
        "categories": ["materia_medica", "organon"],
        "with_pdf_page": 2,
        "from_partly_indexed_books": 2,
    }


def test_citations_are_resolved_and_claims_are_checked_against_the_cited_text() -> None:
    analysis = {
        "passages": [
            {
                "chunk_id": "c1",
                "book_title": "MM",
                "page_start": 12,
                "content": "Burning itching, worse at night and relieved by warmth.",
            },
            {"chunk_id": "c2", "book_title": "MM", "page_start": None, "content": "Unrelated."},
        ],
        "remedies": [
            {
                "remedy": "Sulphur",
                "confidence": "low",
                "citations": ["c1", "ghost"],
                "matching_symptoms": ["burning itching worse at night", "thirst for cold water"],
                "contradicting_symptoms": ["relieved by warmth"],
            }
        ],
    }
    (row,) = check_citations(analysis)
    assert row["citations"] == 2 and row["citations_resolved"] == 1  # "ghost" does not exist
    assert row["books"] == ["MM"] and row["pages"] == [12]
    assert row["fits"] == 2 and row["fits_supported"] == 1  # the thirst claim has no support
    assert row["against"] == 1 and row["against_supported"] == 1
    assert "burning" not in str(row)  # no symptom wording in the output


def test_merging_keeps_the_best_score_per_passage_and_caps_the_list() -> None:
    low, high = passage("a", 0.2), passage("a", 0.7)
    merged = merge_query_hits([[low, passage("b", 0.5)], [high]], limit=2)
    assert [(p.chunk_id, p.similarity) for p in merged] == [("a", 0.7), ("b", 0.5)]
