"""Text cleaning for ingested books.

Normalises unicode, repairs hyphenation broken across lines, removes page
number lines and running headers/footers, and collapses noisy whitespace.
Cleaning is deterministic: resumed ingestion re-derives identical text.
"""

import re
import unicodedata

from app.ai.ingestion.extraction import PageText

# A line repeated on most pages (running header/footer) is dropped.
_HEADER_REPEAT_RATIO = 0.5
_PAGE_NUMBER_LINE = re.compile(r"^\s*[-–—.]?\s*\d{1,5}\s*[-–—.]?\s*$")
_HYPHEN_BREAK = re.compile(r"(\w)-\n(\w)")
_MULTI_SPACE = re.compile(r"[ \t]+")
_MULTI_BLANK = re.compile(r"\n{3,}")


def clean_text(text: str) -> str:
    """Clean a single block of text."""
    text = unicodedata.normalize("NFC", text)
    text = text.replace("\r\n", "\n").replace("\xa0", " ")
    # Rejoin words hyphenated across a line break: "ver-\ntum" -> "vertum".
    text = _HYPHEN_BREAK.sub(r"\1\2", text)
    if _PAGE_NUMBER_LINE.match(text.strip() or " "):
        return ""
    lines = [_MULTI_SPACE.sub(" ", line).strip() for line in text.split("\n")]
    lines = [line for line in lines if not _PAGE_NUMBER_LINE.match(line)]
    text = "\n".join(lines)
    return _MULTI_BLANK.sub("\n\n", text).strip()


def clean_pages(pages: list[PageText]) -> list[PageText]:
    """Clean every page and drop lines repeated across most pages.

    ponytail: repeated-line removal only inspects first/last lines of each
    page (where headers/footers live); a header appearing mid-page survives.
    Upgrade path: position-aware layout analysis via pymupdf "dict" mode.
    """
    cleaned = [PageText(page=p.page, text=clean_text(p.text)) for p in pages]
    if len(cleaned) < 3:
        return [p for p in cleaned if p.text]

    counts: dict[str, int] = {}
    candidates: set[str] = set()
    for page in cleaned:
        lines = [line for line in page.text.split("\n") if line.strip()]
        if not lines:
            continue
        for line in {lines[0], lines[-1]}:
            if len(line) <= 120:
                candidates.add(line)
                counts[line] = counts.get(line, 0) + 1
    threshold = max(3, int(len(cleaned) * _HEADER_REPEAT_RATIO))
    repeated = {line for line, count in counts.items() if count >= threshold}

    result: list[PageText] = []
    for page in cleaned:
        lines = [line for line in page.text.split("\n") if line.strip() not in repeated]
        text = _MULTI_BLANK.sub("\n\n", "\n".join(lines)).strip()
        if text:
            result.append(PageText(page=page.page, text=text))
    return result
