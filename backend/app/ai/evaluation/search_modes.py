"""Compare the search modes on an existing case, without writing anything or calling a model.

The functions here are pure: they take the passages and the saved analysis that already
exist and measure them. Nothing is printed about the patient: no name, ID, contact or symptom
text. The support checks are a lexical heuristic (do the words of a claim appear in the cited
passages?), not clinical validation.
"""

from typing import Any

from app.ai.rag.retrieval import keyword_terms

SUPPORT_THRESHOLD = 0.5  # share of a claim's words that must appear in the cited passages


def passage_ids(passages: list[dict[str, Any]]) -> list[str]:
    return [p["chunk_id"] for p in passages]


def overlap(a: list[str], b: list[str]) -> dict[str, Any]:
    """How much two ranked id lists agree."""
    sa, sb = set(a), set(b)
    union = sa | sb
    return {
        "shared": len(sa & sb),
        "only_first": len(sa - sb),
        "only_second": len(sb - sa),
        "jaccard": round(len(sa & sb) / len(union), 3) if union else 1.0,
        "top5_shared": len(set(a[:5]) & set(b[:5])),
    }


def describe_passages(
    passages: list[dict[str, Any]], complete: dict[str, bool] | None = None
) -> dict[str, Any]:
    """Numbers about a result set: size, books, categories, pages, partly indexed share."""
    complete = complete or {}
    books = {p.get("book_title") for p in passages}
    with_pages = sum(1 for p in passages if p.get("page_start"))
    partial = sum(1 for p in passages if complete.get(p.get("book_id", ""), True) is False)
    return {
        "passages": len(passages),
        "distinct_books": len(books),
        "categories": sorted({p.get("book_category", "") for p in passages}),
        "with_pdf_page": with_pages,
        "from_partly_indexed_books": partial,
    }


def _supported(claim: str, text: str) -> bool:
    terms = keyword_terms(claim)
    if not terms:
        return False
    found = sum(1 for term in terms if term in text)
    return found / len(terms) >= SUPPORT_THRESHOLD


def check_citations(analysis: dict[str, Any]) -> list[dict[str, Any]]:
    """Per remedy: do the citations exist, and are the stated fits/against backed by the text?

    Returns counts only (never the symptom wording).
    """
    by_id = {p["chunk_id"]: p for p in analysis.get("passages") or []}
    results = []
    for remedy in analysis.get("remedies") or []:
        cited = remedy.get("citations") or []
        resolved = [c for c in cited if c in by_id]
        text = " ".join(by_id[c].get("content", "") for c in resolved).lower()
        fits = remedy.get("matching_symptoms") or []
        against = remedy.get("contradicting_symptoms") or []
        results.append(
            {
                "remedy": remedy.get("remedy"),
                "confidence": remedy.get("confidence"),
                "citations": len(cited),
                "citations_resolved": len(resolved),
                "books": sorted({by_id[c].get("book_title", "") for c in resolved}),
                "pages": sorted(
                    {by_id[c]["page_start"] for c in resolved if by_id[c].get("page_start")}
                ),
                "fits": len(fits),
                "fits_supported": sum(1 for f in fits if _supported(f, text)),
                "against": len(against),
                "against_supported": sum(1 for a in against if _supported(a, text)),
            }
        )
    return results


def merge_query_hits(per_query: list[list[Any]], limit: int = 24) -> list[Any]:
    """Merge several searches the way the analyzer does: best score per passage, top `limit`."""
    best: dict[str, Any] = {}
    for hits in per_query:
        for hit in hits:
            if hit.chunk_id not in best or hit.similarity > best[hit.chunk_id].similarity:
                best[hit.chunk_id] = hit
    return sorted(best.values(), key=lambda p: p.similarity, reverse=True)[:limit]
