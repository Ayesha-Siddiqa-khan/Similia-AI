"""Pilot SFT dataset: extractive, source-grounded question-answer pairs.

No language model is called. Each answer is a verbatim span from a cleaned
chunk, so grounding is checkable by construction: the span must appear in the
source, the page must exist, and the book must be cleared for export.
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass
from typing import Any

from app.ai.finetune.claims import classify_claim
from app.ai.finetune.cleaning import (
    extract_answer_span,
    strip_heading_prefix,
    tidy_quote,
    trim_to_sentence_end,
    trim_to_sentence_start,
)
from app.ai.finetune.config import (
    MAX_SFT_ANSWER_CHARS,
    MIN_SFT_CHARS,
    MIN_SFT_WORDS,
    PILOT_MIN_PER_BOOK,
    PILOT_TARGET,
)
from app.ai.finetune.models import CleanChunk, LicenceDecision
from app.ai.finetune.sft import build_sft_example, validate_example, verification_summary

_GENERIC_SECTIONS = {
    "front matter",
    "general text",
    "text",
    "unknown",
    "preface",
    "introduction",
    "contents",
    "table of contents",
    "index",
    "title page",
    "dedication",
    "translator's preface",
    "author's preface",
    "editor's preface",
    "notes",
    "bibliography",
    "appendix",
    "errata",
    "advertisement",
    "copyright",
    "the",
    "theory",
    "homeopathic",
    "homoeopathic",
    "materia medica",
    "countway library",
    "yale medical library",
    "college of osteopathic physicians",
    "and surgeons los angeles california",
    "william radde",
    "importer, bookseller, and publisher",
    "transferred to",
    "a. teste",
    "studies in the philosophy of healing",
}
_GENERIC_PREFIXES = ("translator", "author's preface", "editor's preface")
_TRAILING_PAGE = re.compile(r"\s+\d{1,4}\s*$")
_TRAILING_PAGE_TOKEN = re.compile(r"\s{2,}(?:\d{1,4}|[IVXLC]{1,5}|[A-Z]{1,3})\s*$")
_TRAILING_PARENTHETICAL = re.compile(r"\s*\([^)]*\)\s*$")
_PAGE_REFERENCE = re.compile(r"^(?:[IVXLC]+\.?,?\s*)?(?:PP?\.?\s*)?\d", re.IGNORECASE)
_LECTURE = re.compile(
    r"LECTURE\s+(\d+)\s*[:.\-]\s*(.{3,80}?)(?:\.\s+[A-Z]|\n|$)",
    re.IGNORECASE,
)
_SECTION_REMEDY = re.compile(
    r"([A-Z][A-Za-z0-9 ,.'’\-()/&]{2,60}?)\.?\s*[-\u2013\u2014]\s*"
    r"\(([A-Z][A-Za-z0-9 .'\-]{2,40})\)"
)
_REMEDY_NAME = re.compile(
    r"^([A-Z][A-Z ]{2,40})\s*\(([A-Z][A-Za-z .'\-]{2,40})\)\s*\.?\s*$",
    re.MULTILINE,
)
_DATE_RANGE = re.compile(r"\s*,?\s*\d{4}\s*-\s*\d{4}\s*$")
_YEAR = re.compile(r"\b(?:1[5-9]\d{2}|20\d{2})\b")
_SMALL_WORDS = {"of", "and", "the", "in", "on", "for", "to", "a", "an"}
_PII = re.compile(
    r"\b[\w.+-]+@[\w-]+\.[\w.]+\b|\+\d{1,3}[\s-]?\d{6,}|\b\d{10,}\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class ChunkEntity:
    name: str
    start: int | None = None
    end: int | None = None
    confident: bool = False


@dataclass(frozen=True)
class PilotCandidate:
    clean_chunk: CleanChunk
    entity: str
    question: str
    question_type: str
    quote: str
    score: float


@dataclass
class PilotResult:
    examples: list[dict[str, Any]]
    verification: dict[str, Any]
    per_book: dict[str, int]
    candidates: int
    shortfall: int


def _clean_entity(value: str) -> str | None:
    text = " ".join((value or "").split())
    text = re.split(r"[>|]", text)[0].strip()
    text = _TRAILING_PARENTHETICAL.sub("", text).strip()
    text = _TRAILING_PAGE_TOKEN.sub("", text).strip()
    text = _TRAILING_PAGE.sub("", text).strip(" .,:;-\u2013\u2014?!")
    if len(text) < 3 or len(text) > 90:
        return None
    lowered = text.casefold()
    if lowered in _GENERIC_SECTIONS or lowered.startswith(_GENERIC_PREFIXES):
        return None
    if _PAGE_REFERENCE.match(text):
        return None
    if _YEAR.search(text):
        return None
    if "www." in lowered or "http" in lowered:
        return None
    # Reject OCR noise such as "M1Llari" and abbreviations such as "N.H.D".
    if re.search(r"[A-Za-z]\d|\d[A-Za-z]", text):
        return None
    if re.search(r"\.\S", text) or text.count(".") > 1:
        return None
    if "(" in text or ")" in text:
        return None
    words = [word for word in text.split() if word]
    if not words:
        return None
    if sum(len(word.strip(".,;:")) == 1 for word in words) / len(words) > 0.3:
        return None
    if not any(len(word.strip(".,;:")) >= 3 for word in words):
        return None
    if text.isupper():
        text = text.title()
    return text


def _question_author(book, licence: LicenceDecision | None = None) -> str:
    if licence and licence.display_author:
        return licence.display_author
    author = _DATE_RANGE.sub("", (book.author or "Unknown author").strip())
    parts = [part.strip() for part in author.split(",") if part.strip()]
    if len(parts) == 2 and all(part.replace(".", "").isalpha() for part in parts):
        return f"{parts[1]} {parts[0]}"
    return author or "Unknown author"


def _display_title(title: str) -> str:
    if not title.islower():
        return title.strip()
    words = title.split()
    return " ".join(
        word.capitalize() if index == 0 or word not in _SMALL_WORDS else word
        for index, word in enumerate(words)
    )


def _looks_like_heading(line: str) -> bool:
    text = line.strip()
    if not 3 <= len(text) <= 80:
        return False
    if text.endswith((".", ",", ";")):
        return False
    if len(text.split()) > 10:
        return False
    letters = [char for char in text if char.isalpha()]
    if len(letters) < 3:
        return False
    uppercase = sum(char.isupper() for char in letters) / len(letters)
    return uppercase >= 0.8 or text.istitle()


def _heading_candidate(line: str) -> str | None:
    text = line.strip()
    if not text:
        return None
    if len(text) > 80:
        match = re.match(
            r"^([A-Z][A-Z0-9 ,.'’\-()/&?!]{2,79})(?:[.?!]\s+|$)",
            text,
        )
        if not match:
            return None
        text = match.group(1)
    if _looks_like_heading(text):
        return _clean_entity(text)
    return None


def _remedy_headings(text: str) -> list[tuple[int, str]]:
    """Find section or remedy headings that carry a parenthetical name."""
    headings: list[tuple[int, str]] = []
    for match in _SECTION_REMEDY.finditer(text):
        name = _clean_entity(match.group(2))
        if name:
            headings.append((match.start(), name))
    for match in _REMEDY_NAME.finditer(text):
        name = _clean_entity(match.group(1))
        if name:
            headings.append((match.start(), name))
    headings.sort(key=lambda item: item[0])
    unique: list[tuple[int, str]] = []
    for position, name in headings:
        if unique and abs(position - unique[-1][0]) < 2:
            continue
        unique.append((position, name))
    return unique


def _entity_map(clean_chunks: list[CleanChunk]) -> dict[str, ChunkEntity]:
    """Resolve a running heading and, where useful, a focused span per chunk."""
    by_book: dict[str, list[CleanChunk]] = defaultdict(list)
    for clean in clean_chunks:
        by_book[clean.book.id].append(clean)

    entities: dict[str, ChunkEntity] = {}
    for book_chunks in by_book.values():
        running: str | None = None
        running_span: tuple[int | None, int | None] = (None, None)
        for clean in sorted(book_chunks, key=lambda item: item.chunk.chunk_index):
            metadata = clean.chunk.metadata or {}
            local: str | None = None
            start: int | None = None
            end: int | None = None
            confident = False

            for key in ("remedy", "section", "symptom_heading"):
                candidate = _clean_entity(str(metadata.get(key) or ""))
                if candidate:
                    local = candidate
                    confident = True
                    break

            if local is None:
                headings = _remedy_headings(clean.text)
                if headings:
                    local = headings[0][1]
                    confident = True
                    start = 0
                    for position, name in headings[1:]:
                        if name.casefold() != local.casefold():
                            end = position
                            break
                    if end is not None and end - start < MIN_SFT_CHARS:
                        start, end = 0, None

            if local is None:
                lecture = _LECTURE.search(clean.text)
                if lecture:
                    title = _clean_entity(lecture.group(2))
                    if title:
                        local = f"Lecture {lecture.group(1)}: {title}"
                        confident = True

            if local is None:
                for line in clean.text.split("\n", 3)[:3]:
                    candidate = _heading_candidate(line)
                    if candidate:
                        local = candidate
                        confident = True
                        break

            if local is not None:
                running = local
                running_span = (start, end)
                entities[clean.chunk.id] = ChunkEntity(local, start, end, True)
            elif running is not None:
                entities[clean.chunk.id] = ChunkEntity(
                    running, running_span[0], running_span[1], True
                )
            else:
                entities[clean.chunk.id] = ChunkEntity(clean.book.title, confident=False)
    return entities


def _is_philosophy(book) -> bool:
    title = book.title.casefold()
    return "philosoph" in title or "lecture" in title


def _question(
    clean: CleanChunk,
    entity: str,
    index: int,
    licence: LicenceDecision | None = None,
) -> tuple[str, str]:
    book = clean.book
    title = _display_title(book.title)
    author = _question_author(book, licence)
    page = clean.chunk.page_start or 0

    if book.category == "materia_medica" and not _is_philosophy(book):
        templates = (
            (
                f"What does {title} record about {entity} on page {page}?",
                "page_lookup",
            ),
            (
                f"According to {author}'s {title}, "
                f"what observations are associated with {entity}?",
                "remedy_profile",
            ),
            (
                f"Summarise the passage on {entity} from {title} (page {page}).",
                "section_summary",
            ),
            (
                f"Quote the passage about {entity} in {title}.",
                "passage_quotation",
            ),
            (
                f"What historical symptoms or provings does {title} describe "
                f"for {entity}?",
                "remedy_profile",
            ),
            (
                f"Explain what {author} records about {entity} in {title}.",
                "section_summary",
            ),
        )
    else:
        templates = (
            (
                f"What does {author}'s {title} record in the section on {entity}?",
                "section_summary",
            ),
            (
                f"Summarise the passage on {entity} from {title} (page {page}).",
                "section_summary",
            ),
            (
                f"What observations does {author} make about {entity} in {title}?",
                "remedy_profile",
            ),
            (
                f"Quote and explain what {title} says about {entity}.",
                "passage_quotation",
            ),
            (
                f"What historical argument or observation does {title} "
                f"present about {entity}?",
                "section_summary",
            ),
            (
                f"Explain the passage on {entity} in {title}.",
                "section_summary",
            ),
        )
    return templates[index % len(templates)]


def _candidate(
    clean: CleanChunk,
    entity_info: ChunkEntity,
    index: int,
    licence: LicenceDecision | None = None,
) -> PilotCandidate | None:
    entity = entity_info.name
    if not entity_info.confident:
        return None
    if entity.casefold() == clean.book.title.casefold():
        return None
    if entity.casefold() in _GENERIC_SECTIONS:
        return None
    if clean.chunk.page_start is None or clean.chunk.page_start < 5:
        return None

    text = clean.text
    if entity_info.start is not None:
        text = text[entity_info.start : entity_info.end]

    heading = (
        clean.chunk.metadata.get("remedy")
        or clean.chunk.metadata.get("section")
        or entity
    )
    body = strip_heading_prefix(text, str(heading) if heading else None)
    if body.casefold().startswith(entity.casefold()):
        body = body[len(entity) :].lstrip(" .:;-\u2013\u2014?!")
    lines = body.split("\n")
    if lines and entity.casefold() in lines[0].casefold() and len(lines[0]) <= 90:
        body = "\n".join(lines[1:]).strip()
    body = trim_to_sentence_start(body)
    if len(body) < MIN_SFT_CHARS or len(body.split()) < MIN_SFT_WORDS:
        return None
    quote = tidy_quote(extract_answer_span(body, MAX_SFT_ANSWER_CHARS))
    quote = trim_to_sentence_end(quote)
    if len(quote) < MIN_SFT_CHARS or len(quote.split()) < MIN_SFT_WORDS:
        return None
    if _PII.search(quote):
        return None

    question, question_type = _question(clean, entity, index, licence)
    score = round(
        min(len(quote), MAX_SFT_ANSWER_CHARS) / MAX_SFT_ANSWER_CHARS
        + clean.quality.alphabetic_ratio
        + 0.2
        + (0.1 if clean.section else 0.0),
        4,
    )
    return PilotCandidate(
        clean_chunk=clean,
        entity=entity,
        question=question,
        question_type=question_type,
        quote=quote,
        score=score,
    )


def _allocate(counts: dict[str, int], target: int) -> dict[str, int]:
    if not counts:
        return {}
    total = sum(counts.values())
    if total <= target:
        return dict(counts)

    quotas = {
        book_id: max(PILOT_MIN_PER_BOOK, round(target * count / total))
        for book_id, count in counts.items()
    }
    quotas = {book_id: min(quota, counts[book_id]) for book_id, quota in quotas.items()}

    while sum(quotas.values()) > target:
        book_id = max(
            (key for key in quotas if quotas[key] > PILOT_MIN_PER_BOOK),
            key=lambda key: quotas[key],
            default=None,
        )
        if book_id is None:
            book_id = max(quotas, key=lambda key: quotas[key])
        if quotas[book_id] <= 1:
            break
        quotas[book_id] -= 1

    while sum(quotas.values()) < target:
        book_id = max(
            (key for key in quotas if quotas[key] < counts[key]),
            key=lambda key: counts[key] - quotas[key],
            default=None,
        )
        if book_id is None:
            break
        quotas[book_id] += 1

    return quotas


def _evenly_spaced(candidates: list[PilotCandidate], quota: int) -> list[PilotCandidate]:
    ordered = sorted(candidates, key=lambda item: item.clean_chunk.chunk.chunk_index)
    if quota >= len(ordered):
        return ordered
    if quota <= 1:
        return [ordered[len(ordered) // 2]]
    step = (len(ordered) - 1) / (quota - 1)
    picked = [ordered[round(index * step)] for index in range(quota)]
    seen: set[str] = set()
    unique: list[PilotCandidate] = []
    for item in picked:
        if item.clean_chunk.chunk.id not in seen:
            seen.add(item.clean_chunk.chunk.id)
            unique.append(item)
    for item in ordered:
        if len(unique) >= quota:
            break
        if item.clean_chunk.chunk.id not in seen:
            seen.add(item.clean_chunk.chunk.id)
            unique.append(item)
    return unique


def _select_diverse(
    candidates: list[PilotCandidate], quota: int, per_entity: int = 3
) -> list[PilotCandidate]:
    ordered = sorted(
        candidates,
        key=lambda item: (-item.score, item.clean_chunk.chunk.chunk_index),
    )
    counts: dict[str, int] = defaultdict(int)
    selected: list[PilotCandidate] = []
    for item in ordered:
        key = item.entity.casefold()
        if counts[key] >= per_entity:
            continue
        selected.append(item)
        counts[key] += 1
        if len(selected) >= quota:
            return selected
    chosen = {item.clean_chunk.chunk.id for item in selected}
    for item in ordered:
        if item.clean_chunk.chunk.id in chosen:
            continue
        selected.append(item)
        if len(selected) >= quota:
            break
    return selected


def build_pilot(
    clean_chunks: list[CleanChunk],
    licences: dict[str, LicenceDecision],
    target: int = PILOT_TARGET,
) -> PilotResult:
    """Build a balanced pilot of verified, extractive SFT examples."""
    usable = [
        clean
        for clean in clean_chunks
        if clean.usable and clean.book.content_hash in licences
    ]
    entities = _entity_map(usable)

    by_book: dict[str, list[PilotCandidate]] = defaultdict(list)
    for clean in usable:
        licence = licences[clean.book.content_hash]
        if not (licence.cleared and licence.exportable):
            continue
        entity_info = entities.get(
            clean.chunk.id, ChunkEntity(clean.book.title, confident=False)
        )
        candidate = _candidate(
            clean, entity_info, clean.chunk.chunk_index, licence
        )
        if candidate is not None:
            by_book[clean.book.id].append(candidate)

    counts = {book_id: len(items) for book_id, items in by_book.items()}
    quotas = _allocate(counts, target)

    examples: list[dict[str, Any]] = []
    per_book: dict[str, int] = {}
    checks: list[list[str]] = []

    for book_id in sorted(by_book):
        quota = quotas.get(book_id, 0)
        if quota == 0:
            continue
        pool_size = min(len(by_book[book_id]), max(quota * 4, quota))
        pool = _evenly_spaced(by_book[book_id], pool_size)
        selected = _select_diverse(pool, quota)
        built = 0
        for candidate in selected:
            clean = candidate.clean_chunk
            licence = licences[clean.book.content_hash]
            example_id = f"sft-{clean.book.content_hash[:8]}-{clean.chunk.chunk_index:05d}"
            example = build_sft_example(
                example_id=example_id,
                question=candidate.question,
                answer_quote=candidate.quote,
                clean_chunk=clean,
                licence=licence,
                classification=classify_claim(candidate.quote),
                question_type=candidate.question_type,
                display_author=licence.display_author,
            )
            errors = validate_example(example, clean, licence)
            checks.append(errors)
            if errors:
                continue
            examples.append(example)
            built += 1
        per_book[book_id] = built

    verification = verification_summary(checks)
    verification["verified_examples"] = len(examples)
    shortfall = max(0, target - len(examples))
    return PilotResult(
        examples=examples,
        verification=verification,
        per_book=per_book,
        candidates=sum(counts.values()),
        shortfall=shortfall,
    )
