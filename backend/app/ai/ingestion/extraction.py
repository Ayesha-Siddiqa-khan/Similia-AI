"""Text extraction from uploaded knowledge-base sources.

Supports machine-readable PDFs (via pymupdf) and plain text files. Page
boundaries are preserved: pages are separated by \f (form feed) in the
stored raw_text and reconstructed by the chunkers, so page metadata survives
the round trip through the database.
"""

import pymupdf

SUPPORTED_EXTENSIONS = (".pdf", ".txt")
PAGE_SEPARATOR = "\f"


class ExtractionError(ValueError):
    """The uploaded file could not be converted to text."""


class PageText:
    """Text of one source page (1-based page number)."""

    __slots__ = ("page", "text")

    def __init__(self, page: int, text: str) -> None:
        self.page = page
        self.text = text


class ExtractedDocument:
    """Extraction result: ordered page texts."""

    def __init__(self, pages: list[PageText]) -> None:
        self.pages = pages

    @property
    def text(self) -> str:
        """Full text with \f page separators (the stored raw_text format)."""
        return PAGE_SEPARATOR.join(page.text for page in self.pages)


def extract_document(data: bytes, filename: str) -> ExtractedDocument:
    """Extract page texts from PDF or TXT bytes; raises ExtractionError."""
    lower = filename.lower()
    if lower.endswith(".pdf"):
        return _extract_pdf(data)
    if lower.endswith(".txt"):
        return _extract_txt(data)
    supported = ", ".join(SUPPORTED_EXTENSIONS)
    raise ExtractionError(f"Unsupported file type '{filename}'. Supported: {supported}")


def _extract_pdf(data: bytes) -> ExtractedDocument:
    # A real PDF starts with "%PDF-" (readers tolerate a little junk before it). Checking the
    # content, not just the file name, stops a renamed file reaching the PDF parser.
    if b"%PDF-" not in data[:1024]:
        raise ExtractionError("The file is not a PDF (it does not start with a PDF header)")
    try:
        document = pymupdf.open(stream=data, filetype="pdf")
    except Exception as exc:
        raise ExtractionError(f"Not a readable PDF: {exc}") from exc
    try:
        if document.needs_pass:
            raise ExtractionError("Password-protected PDFs are not supported")
        pages = [
            PageText(page=index + 1, text=page.get_text("text"))
            for index, page in enumerate(document)
        ]
    finally:
        document.close()
    if not any(page.text.strip() for page in pages):
        raise ExtractionError(
            "No extractable text found (scanned or image-only PDFs are not supported)"
        )
    return ExtractedDocument(pages)


def _extract_txt(data: bytes) -> ExtractedDocument:
    if b"\x00" in data:  # a binary file renamed to .txt; Postgres text also cannot store NUL
        raise ExtractionError("The file is binary, not a text file")
    for encoding in ("utf-8-sig", "utf-8", "latin-1"):
        try:
            text = data.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    else:
        raise ExtractionError("Could not decode text file (expected UTF-8 or Latin-1)")
    if not text.strip():
        raise ExtractionError("Text file is empty")
    return ExtractedDocument([PageText(page=1, text=text)])
