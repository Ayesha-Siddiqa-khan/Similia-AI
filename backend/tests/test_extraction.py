"""Text extraction tests: PDF (built in-memory), TXT, and error paths."""

import pymupdf
import pytest

from app.ai.ingestion.extraction import (
    PAGE_SEPARATOR,
    ExtractionError,
    extract_document,
)


def make_pdf(pages: list[str]) -> bytes:
    """Build a small machine-readable PDF in memory (original test text)."""
    document = pymupdf.open()
    for text in pages:
        page = document.new_page(width=595, height=842)
        page.insert_text((72, 100), text, fontsize=11)
    data = document.tobytes()
    document.close()
    return data


def test_extract_pdf_preserves_pages_and_text() -> None:
    data = make_pdf(["First page about Aconitum.", "Second page about Arsenicum."])
    document = extract_document(data, "sample.pdf")
    assert len(document.pages) == 2
    assert "Aconitum" in document.pages[0].text
    assert document.pages[1].page == 2
    assert PAGE_SEPARATOR in document.text


def test_extract_txt_utf8() -> None:
    document = extract_document("§ 1. Rápide, doux et permanent.".encode("utf-8"), "book.txt")
    assert len(document.pages) == 1
    assert "Rápide" in document.pages[0].text


def test_extract_unsupported_extension() -> None:
    with pytest.raises(ExtractionError, match="Unsupported file type"):
        extract_document(b"data", "book.docx")


def test_extract_empty_txt() -> None:
    with pytest.raises(ExtractionError, match="empty"):
        extract_document(b"   \n  ", "book.txt")


def test_extract_garbage_pdf() -> None:
    with pytest.raises(ExtractionError):
        extract_document(b"%PDF-1.4 not really a pdf", "broken.pdf")
