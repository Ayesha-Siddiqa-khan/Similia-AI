"""Search coverage: which books are fully searchable, and which PDF pages a passage came from."""

from typing import Any

from app.services import knowledge_db


def book_completeness(db: Any) -> dict[str, bool]:
    """book_id -> True when every chunk has a vector (otherwise search misses parts)."""
    return {
        row["book_id"]: int(row["total_chunks"]) > 0
        and int(row["embedded_chunks"]) == int(row["total_chunks"])
        for row in knowledge_db.book_stats(db)
    }


_PAGE_KEYS = (("page_start", "page_end"), ("start_page", "end_page"), ("first_page", "last_page"))


def _page(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else None


def page_range(metadata: dict[str, Any] | None) -> tuple[int | None, int | None]:
    """PDF page numbers stored with a chunk (None when the chunk has none). Never guessed."""
    meta = metadata or {}
    for first, last in _PAGE_KEYS:
        start = _page(meta.get(first))
        if start is not None:
            return start, _page(meta.get(last)) or start
    pages = meta.get("pages")
    if isinstance(pages, (list, tuple)) and pages:
        start, end = _page(pages[0]), _page(pages[-1])
        if start is not None:
            return start, end or start
    return None, None
