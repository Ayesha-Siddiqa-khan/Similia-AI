"""Cleaning and quality gates for fine-tuning text.

The RAG pipeline cleans PDFs at ingestion time. This module applies a second,
stricter pass for training data: it removes digitisation watermarks, running
headers, page numbers, contact details and URLs, repairs line-break
hyphenation, and scores whether a chunk is substantive enough to train on.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from app.ai.finetune.config import MIN_ALPHABETIC_RATIO
from app.ai.finetune.models import QualityScore

# Lines that are pure digitisation or reprint furniture.
ARTEFACT_MARKERS: tuple[str, ...] = (
    "www.drbidani.co.nr",
    "www.drbidani.com",
    "dr. bidani's",
    "dr bidani's",
    "centre for homoeopathy",
    "nalanda digital library",
    "public domain text converted",
    "books.google.com",
    "digitized by google",
    "digitised by google",
    "this is a reproduction of a library book",
    "my digital reference library",
    "tanvir ul islam",
    "you have either reached a page that is unavailable",
    "serving homoeopathy since",
    "red square market",
    "courtesy:",
)

_PAGE_NUMBER = re.compile(r"^\s*[-–—.]?\s*\d{1,5}\s*[-–—.]?\s*$")
_RUNNING_HEADER_RIGHT = re.compile(
    r"^(.*?)\s{2,}(\d{1,4}|[IVXLC]{1,5}|[A-Z]{1,3})$"
)
_RUNNING_HEADER_LEFT = re.compile(
    r"^\s*\d{1,4}\s{2,}[A-Z][A-Z0-9 ,.'’\-()/&]{2,}\s*$"
)
_URL = re.compile(r"(?:https?://|www\.)\S+", re.IGNORECASE)
_EMAIL = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.]+\b")
_PHONE = re.compile(r"\+\d{1,3}[\s-]?\d{6,}|\b\d{10,}\b")
_ISBN = re.compile(r"\bISBN(?:-1[03])?:?\s*[\dXx -]{10,}\b", re.IGNORECASE)
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_HYPHEN_BREAK = re.compile(r"(\w)-\s*\n\s*(\w)")
_MULTI_SPACE = re.compile(r"[ \t]+")
_MULTI_BLANK = re.compile(r"\n{3,}")
_HEADING_PREFIX = re.compile(r"^\s*==\s*(.*?)\s*==\s*$")
_SENTENCE_END = re.compile(r"[.!?]")


@dataclass(frozen=True)
class CleanResult:
    text: str
    removed: tuple[str, ...]


def _is_running_header(line: str) -> bool:
    match = _RUNNING_HEADER_RIGHT.match(line.strip())
    if not match:
        return False
    heading = match.group(1)
    letters = [char for char in heading if char.isalpha()]
    if len(letters) < 3:
        return False
    # Tolerate OCR damage such as "MORBILLt" while rejecting prose lines.
    return sum(char.isupper() for char in letters) / len(letters) >= 0.7


def _is_artefact_line(line: str) -> str | None:
    lowered = line.lower()
    for marker in ARTEFACT_MARKERS:
        if marker in lowered:
            return "digitisation_marker"
    if _PAGE_NUMBER.match(line):
        return "page_number"
    if _is_running_header(line) or _RUNNING_HEADER_LEFT.match(line):
        return "running_header"
    if _ISBN.search(line):
        return "isbn"
    if _EMAIL.search(line):
        return "contact_details"
    if _PHONE.search(line):
        return "contact_details"
    return None


def clean_chunk_text(raw: str) -> CleanResult:
    """Return cleaned text and the artefact kinds that were removed."""
    text = unicodedata.normalize("NFC", raw or "")
    text = text.replace("\r\n", "\n").replace("\r", "\n").replace("\xa0", " ")
    text = text.replace("\u00ad", "")
    # Form feeds separate PDF pages; treat them as line boundaries.
    text = text.replace("\f", "\n")
    text = _CONTROL.sub("", text)

    removed: set[str] = set()
    kept: list[str] = []
    for raw_line in text.split("\n"):
        line = raw_line.rstrip()
        kind = _is_artefact_line(line.strip())
        if kind is not None:
            removed.add(kind)
            continue
        # Strip URLs but keep the surrounding prose.
        cleaned_line = _URL.sub("", line)
        if _URL.search(line):
            removed.add("url")
        cleaned_line = _MULTI_SPACE.sub(" ", cleaned_line).strip()
        kept.append(cleaned_line)

    text = "\n".join(kept)
    # Rejoin words hyphenated across a line break: "inflam-\nmation" -> "inflammation".
    text = _HYPHEN_BREAK.sub(r"\1\2", text)
    text = _MULTI_SPACE.sub(" ", text)
    text = "\n".join(line.strip() for line in text.split("\n"))
    text = _MULTI_BLANK.sub("\n\n", text).strip()
    return CleanResult(text=text, removed=tuple(sorted(removed)))


def strip_heading_prefix(text: str, heading: str | None) -> str:
    """Remove a repeated heading and ``== heading ==`` prefixes from a chunk."""
    result = text.strip()
    while True:
        lines = result.split("\n")
        if not lines:
            return ""
        first = lines[0].strip()
        match = _HEADING_PREFIX.match(first)
        if match:
            result = "\n".join(lines[1:]).strip()
            continue
        if heading and first.casefold() == heading.strip().casefold():
            result = "\n".join(lines[1:]).strip()
            continue
        return result


def score_text(
    text: str,
    *,
    min_chars: int,
    min_words: int = 20,
    min_alphabetic_ratio: float = MIN_ALPHABETIC_RATIO,
) -> QualityScore:
    """Score whether cleaned text is substantive training material."""
    characters = len(text)
    words = len(text.split())
    non_space = sum(1 for char in text if not char.isspace())
    letters = sum(1 for char in text if char.isalpha())
    digits = sum(1 for char in text if char.isdigit())
    ratio = letters / max(1, non_space)
    digit_ratio = digits / max(1, non_space)

    issues: list[str] = []
    if characters < min_chars:
        issues.append("too_short")
    if words < min_words:
        issues.append("too_few_words")
    if ratio < min_alphabetic_ratio:
        issues.append("low_alphabetic_ratio")
    if digit_ratio > 0.25:
        issues.append("mostly_digits")
    if not _SENTENCE_END.search(text):
        issues.append("no_sentence")
    if len(set(text.lower().split())) < 12:
        issues.append("repetitive_vocabulary")

    usable = not issues
    return QualityScore(
        characters=characters,
        words=words,
        alphabetic_ratio=round(ratio, 4),
        issues=tuple(issues),
        usable=usable,
        reason="ok" if usable else issues[0],
    )


def trim_to_sentence_start(text: str, max_scan: int = 400) -> str:
    """Drop a partial opening sentence left by a chunk boundary."""
    stripped = text.lstrip()
    if not stripped:
        return ""
    first = stripped[0]
    if first.isupper() or first in "\"'([":
        return stripped
    window = stripped[:max_scan]
    for match in re.finditer(r"[.!?][\"')\]]?\s+(?=[A-Z\"'(])", window):
        return stripped[match.end() :].lstrip()
    newline = stripped.find("\n")
    remainder = stripped[newline + 1 :].lstrip() if newline != -1 else stripped
    if remainder[:1].islower():
        space = remainder.find(" ")
        if 0 < space <= 12:
            remainder = remainder[space + 1 :].lstrip()
    return remainder


def tidy_quote(text: str) -> str:
    """Remove blank lines and rejoin soft-wrapped lines without losing lists."""
    lines = [line.strip() for line in text.split("\n") if line.strip()]
    merged: list[str] = []
    for line in lines:
        if merged and (
            not merged[-1].endswith((".", "!", "?", ":", ";"))
            or line[:1].islower()
        ):
            merged[-1] = f"{merged[-1]} {line}"
        else:
            merged.append(line)
    return "\n".join(merged)


def trim_to_sentence_end(text: str, min_chars: int = 200) -> str:
    """End a quote on a complete sentence when a chunk boundary cut it short."""
    stripped = text.rstrip()
    if not stripped or stripped[-1] in ".!?\"'":
        return stripped
    matches = list(re.finditer(r"[.!?][\"')\]]?(?=\s|$)", stripped))
    for match in reversed(matches):
        if match.end() >= min_chars:
            return stripped[: match.end()].strip()
    # No sentence boundary beyond the preferred length: still drop the
    # dangling fragment rather than shipping a half sentence.
    if matches:
        return stripped[: matches[-1].end()].strip()
    return stripped


def extract_answer_span(text: str, max_chars: int = 2_200) -> str:
    """Take the first complete sentences up to ``max_chars``.

    The span is always a contiguous substring of ``text`` so it can be verified
    against the cleaned source.
    """
    body = text.strip()
    if len(body) <= max_chars:
        return body
    window = body[:max_chars]
    cut = max(window.rfind(". "), window.rfind("! "), window.rfind("? "))
    if cut >= 200:
        return body[: cut + 1].strip()
    cut = window.rfind(" ")
    return body[:cut].strip() if cut > 0 else window.strip()
