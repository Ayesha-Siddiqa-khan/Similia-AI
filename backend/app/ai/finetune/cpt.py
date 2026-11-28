"""Continued pre-training documents built at book and section level.

Chunk overlap is removed by using the deduplicated, cleaned chunks in order.
Documents are large enough to preserve chapter context and carry full
provenance so every training document can be traced to its source pages.
"""

from __future__ import annotations

from typing import Any

from app.ai.finetune.config import CPT_DOCUMENT_CHARS
from app.ai.finetune.models import CleanChunk, LicenceDecision, SplitAssignment


def _book_documents(clean_chunks: list[CleanChunk], book_id: str) -> list[dict[str, Any]]:
    ordered = sorted(
        (clean for clean in clean_chunks if clean.book.id == book_id and clean.usable),
        key=lambda clean: clean.chunk.chunk_index,
    )
    if not ordered:
        return []

    documents: list[dict[str, Any]] = []
    buffer: list[CleanChunk] = []
    size = 0

    def flush() -> None:
        nonlocal buffer, size
        if not buffer:
            return
        book = buffer[0].book
        text = "\n\n".join(clean.text for clean in buffer)
        headings: list[str] = []
        for clean in buffer:
            heading = (
                clean.section.heading if clean.section else clean.chunk.metadata.get("section")
            )
            if heading and heading not in headings:
                headings.append(str(heading))
        pages = [clean.chunk.page_start for clean in buffer if clean.chunk.page_start is not None]
        end_pages = [clean.chunk.page_end for clean in buffer if clean.chunk.page_end is not None]
        documents.append(
            {
                "id": f"cpt-{book.content_hash[:8]}-{len(documents):03d}",
                "text": text,
                "book": {
                    "book_id": book.id,
                    "title": book.title,
                    "author": book.author,
                    "category": book.category,
                    "source_filename": book.source_filename,
                    "content_hash": book.content_hash,
                },
                "sections": headings,
                "pages": {
                    "start": min(pages) if pages else None,
                    "end": max(end_pages) if end_pages else None,
                },
                "chunk_range": {
                    "start": buffer[0].chunk.chunk_index,
                    "end": buffer[-1].chunk.chunk_index,
                },
                "chunk_hashes": [clean.chunk.content_hash for clean in buffer],
                "characters": len(text),
                "token_estimate": max(1, len(text) // 4),
            }
        )
        buffer, size = [], 0

    for clean in ordered:
        if buffer and size + len(clean.text) > CPT_DOCUMENT_CHARS:
            flush()
        buffer.append(clean)
        size += len(clean.text) + 2
    flush()
    return documents


def build_cpt_documents(
    clean_chunks: list[CleanChunk],
    assignments: list[SplitAssignment],
    licences: dict[str, LicenceDecision],
) -> dict[str, list[dict[str, Any]]]:
    """Return CPT documents grouped by split."""
    split_by_book = {assignment.book_id: assignment.split for assignment in assignments}
    by_split: dict[str, list[dict[str, Any]]] = {"train": [], "validation": [], "test": []}

    book_ids = sorted({clean.book.id for clean in clean_chunks})
    for book_id in book_ids:
        split = split_by_book.get(book_id)
        if split is None:
            continue
        for document in _book_documents(clean_chunks, book_id):
            licence = licences[document["book"]["content_hash"]]
            if not (licence.cleared and licence.exportable):
                continue
            document["licence"] = {
                "status": licence.status,
                "basis": licence.basis,
                "legal_review": licence.legal_review,
            }
            document["split"] = split
            by_split[split].append(document)
    return by_split
