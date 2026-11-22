"""Deterministic structural sections, token-bounded chunks and source coordinates.

No LLM calls: headings, aphorisms and rubric indentation define semantic units;
LangChain splits only inside a unit. Original source slices remain independently
addressable even when context prefixes and overlap repeat text for embeddings.
"""

import hashlib
import re
from bisect import bisect_right
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from langchain_text_splitters import RecursiveCharacterTextSplitter
from tokenizers import Tokenizer

VERSION = "adaptive-v1"
POLICIES = {
    "materia_medica": (450, 250, 650, 60),
    "repertory": (120, 40, 250, 0),
    "organon": (500, 1, 500, 0),
    "general": (450, 250, 650, 60),
}
APHORISM = re.compile(r"^\s*(?:§\s*|aphorism\s+)?(\d{1,3})[.)]?\s*$", re.I)
NAMED_APHORISM = re.compile(
    r"^\s*(?:\d{1,4})?(?:§\s*|aphorism\s+|p(?:r)?ara(?:graph)?\s*[-–—�:.]?\s*)(\d{1,3})\b",
    re.I,
)
CAPS = re.compile(r"^[A-Z][A-Z\s.,'’()\-\d]+$")
SUBHEADINGS = {
    "mind",
    "head",
    "stomach",
    "sleep",
    "modalities",
    "eyes",
    "ears",
    "nose",
    "face",
    "mouth",
    "throat",
    "abdomen",
    "stool",
    "urine",
    "chest",
    "back",
    "extremities",
    "skin",
    "fever",
    "generalities",
    "respiration",
    "relations",
    "common characteristics",
    "corresponding diseases",
}


class TokenCounter:
    """Official Voyage tokenizer artifact, explicitly loaded from the repository."""

    def __init__(self, path: Path) -> None:
        self.tokenizer = Tokenizer.from_file(str(path))
        self.tokenizer.no_truncation()
        self.tokenizer.no_padding()
        self.hash = hashlib.sha256(path.read_bytes()).hexdigest()

    def count(self, text: str) -> int:
        return len(self.tokenizer.encode(text).ids) if text else 0


@dataclass
class Unit:
    start: int
    end: int
    heading: str
    kind: str
    path: list[str]
    identifier: str | None = None


def materia_layout_hints(
    pages: list[dict[str, Any]],
    body_start: int,
) -> tuple[dict[int, str], dict[int, int]]:
    """Running titles provide a vocabulary, never an assumed remedy boundary."""
    font_starts = {
        hint["char_start"]: hint["title"]
        for page in pages
        for hint in page.get("remedy_heading_hints", [])
    }
    if len(font_starts) >= 10:
        return font_starts, {}
    headers: dict[int, int] = {}
    names: set[str] = set()
    for page in pages:
        if "text" not in page or page["char_start"] < body_start:
            continue
        offset = page["char_start"]
        for raw in page["text"].splitlines(keepends=True):
            line = raw.strip()
            if line:
                if line.isupper() and re.search(r"\d", line):
                    name = re.sub(r"^\d+\s+|\s+\d+$", "", line)
                    name = re.sub(r"\s+", " ", name).strip(" .")
                    if 3 <= len(name) <= 80:
                        headers[offset] = offset + len(raw)
                        if name.lower() not in SUBHEADINGS and not any(
                            word in name for word in ("GROUP", "INTRODUCTION", "PREFACE", "INDEX")
                        ):
                            names.update(re.split(r"\s+\.\s+", name))
                break
            offset += len(raw)
    starts: dict[int, str] = {}
    patterns = [
        (
            name,
            re.compile(
                r"^\s*" + r"\s+".join(re.escape(w) for w in name.split()) + r"\s*(?:[.,:—–-]|$)",
                re.I,
            ),
        )
        for name in sorted(names, key=len, reverse=True)
    ]
    for page in pages:
        if "text" not in page or page["char_start"] < body_start:
            continue
        offset = page["char_start"]
        for raw in page["text"].splitlines(keepends=True):
            if offset not in headers:
                for name, pattern in patterns:
                    if pattern.match(raw.strip()):
                        starts[offset] = name
                        break
            offset += len(raw)
    return starts, headers


def structural_units(
    text: str,
    category: str,
    body_start: int = 0,
    remedy_starts: dict[int, str] | None = None,
    running_headers: dict[int, int] | None = None,
    strict_remedies: bool = False,
) -> list[Unit]:
    """Cover the full source once; never merge across detected boundaries."""
    starts: list[tuple[int, str, str, list[str], str | None]] = [
        (0, "Front matter", "generic", ["Front matter"], None)
    ]
    offset = 0
    last_aphorism = 0
    remedy: str | None = None
    rubric_stack: list[tuple[int, str]] = []
    last_heading: str | None = None
    for raw in text.splitlines(keepends=True):
        line = raw.strip()
        compact = re.sub(r"\s+", "", line.upper())
        artifact = bool(compact) and (
            bool(re.fullmatch(r"(?:PDF|BOOKS)+", compact))
            or bool(re.search(r"([A-Z]{8,})\1\1", compact))
            or (line.isupper() and "BOOKS" in compact and "HOMOEOPATHIC" in compact)
            or (category == "materia_medica" and compact == "AH")
        )
        if artifact or offset in (running_headers or {}):
            previous = starts[-1][1:]
            label = "Digitization watermark" if artifact else "Running page header"
            starts.append((offset, label, "artifact", [], None))
            starts.append((offset + len(raw), *previous))
            offset += len(raw)
            continue
        if remedy_starts and offset in remedy_starts:
            remedy = remedy_starts[offset]
            last_heading = remedy
            starts.append((offset, remedy, "remedy", [remedy], remedy))
            offset += len(raw)
            continue
        named_match = NAMED_APHORISM.match(line)
        match = named_match or APHORISM.fullmatch(line)
        if category == "organon" and match:
            number = int(match.group(1))
            if (named_match or number == last_aphorism + 1) and 1 <= number <= 291:
                heading = f"§{number}"
                starts.append((offset, heading, "aphorism", [heading], str(number)))
                last_aphorism = number
        elif category == "materia_medica":
            line = re.sub(r"^\d+\s+|\s+\d+$", "", line).strip()
            is_subheading = line.rstrip(" .:").lower() in SUBHEADINGS or (
                strict_remedies
                and line.rstrip(" .:").lower()
                in {
                    "region",
                    "leading symptoms",
                    "repertory",
                    "notes",
                    "differential diagnosis",
                    "rectum",
                    "bladder",
                    "female genitalia",
                    "male genitalia",
                    "larynx",
                    "vision",
                    "hearing",
                    "limbs",
                    "appetite",
                    "perspiration",
                }
            )
            is_caps = bool(CAPS.fullmatch(line)) and 3 <= len(line) <= 85 and not is_subheading
            if is_caps and any(c.isalpha() for c in line):
                # Running remedy headings repeat on successive pages.
                heading = re.sub(r"\s+", " ", line).strip(" .")
                if heading != last_heading:
                    if strict_remedies:
                        offset += len(raw)
                        continue
                    generic = any(
                        word in heading
                        for word in (
                            "GROUP ",
                            "INTRODUCTION",
                            "PREFACE",
                            "CORRESPONDING DISEASES",
                            "MATERIA MEDICA",
                            "CONTENTS",
                        )
                    )
                    if remedy_starts is not None:
                        generic = True  # Unverified capital titles are not asserted as remedies.
                    if offset < body_start and not generic:
                        offset += len(raw)
                        continue
                    remedy = None if generic else heading
                    last_heading = heading
                    starts.append(
                        (offset, heading, "chapter" if generic else "remedy", [heading], remedy)
                    )
            elif is_subheading:
                heading = line.rstrip(" .:")
                path = [remedy, heading] if remedy else [heading]
                starts.append((offset, heading, "subsection", path, remedy))
        elif category == "repertory" and CAPS.fullmatch(line) and 3 <= len(line) <= 80:
            rubric_stack = [(-1, line)]
            starts.append((offset, line, "chapter", [line], None))
        elif category == "repertory" and ":" in line and len(line.split(":", 1)[0]) <= 150:
            heading = line.split(":", 1)[0].strip()
            depth = len(raw) - len(raw.lstrip(" \t"))
            rubric_stack = [(d, h) for d, h in rubric_stack if d < depth]
            rubric_stack.append((depth, heading))
            path = [h for _, h in rubric_stack]
            starts.append((offset, heading, "rubric", path, " > ".join(path)))
        elif category == "general" and CAPS.fullmatch(line) and 3 <= len(line) <= 80:
            starts.append((offset, line, "chapter", [line], None))
        offset += len(raw)
    # Deduplicate a boundary at source offset zero.
    boundaries = {
        start: (heading, kind, path, ident) for start, heading, kind, path, ident in starts
    }
    positions = sorted(boundaries)
    return [
        Unit(start, positions[i + 1] if i + 1 < len(positions) else len(text), *boundaries[start])
        for i, start in enumerate(positions)
    ]


def make_chunks(
    text: str,
    pages: list[dict[str, Any]],
    category: str,
    counter: TokenCounter,
    source_hash: str,
    model: str = "voyage-4-lite",
    body_start: int = 0,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    target, minimum, maximum, overlap = POLICIES[category]
    page_starts = [p["char_start"] for p in pages]
    # This also supplies exact unique source-token coordinates, excluding context prefixes.
    token_offsets = [s for s, e in counter.tokenizer.encode(text).offsets if e > s]
    byte_offsets = [0]
    for character in text:
        byte_offsets.append(byte_offsets[-1] + len(character.encode("utf-8")))
    chunks: list[dict[str, Any]] = []
    sections: list[dict[str, Any]] = []
    hints, headers = (
        materia_layout_hints(pages, body_start)
        if category == "materia_medica" and pages and "text" in pages[0]
        else (None, None)
    )
    if hints == {} and headers == {}:
        hints = None  # Unpaginated PDFs can still expose ordinary remedy headings.
    strict_remedies = sum(len(p.get("remedy_heading_hints", [])) for p in pages) >= 10
    units = structural_units(text, category, body_start, hints, headers, strict_remedies)
    for ordinal, unit in enumerate(units):
        section = asdict(unit) | {"ordinal": ordinal}
        sections.append(section)
        if unit.kind == "artifact":
            continue
        body = text[unit.start : unit.end]
        if not body.strip():
            continue
        prefix = " > ".join(unit.path) + "\n\n"
        prefix_tokens = counter.count(prefix)
        body_limit = max(10, maximum - prefix_tokens - 4)
        preferred = max(10, min(target - prefix_tokens - 4, body_limit))
        # Whole independent aphorisms / small rubrics stay intact, even below minimum.
        if counter.count(prefix + body) <= maximum:
            pieces = [(body.strip(), len(body) - len(body.lstrip()))]
        else:
            splitter = RecursiveCharacterTextSplitter(
                chunk_size=preferred,
                chunk_overlap=min(overlap, preferred // 3),
                length_function=counter.count,
                keep_separator="end",
                separators=[r"\n\s*\n", r"(?<=[.!?;:])\s+", r"\n", r" ", ""],
                is_separator_regex=True,
                add_start_index=True,
            )
            pieces = [
                (d.page_content, d.metadata["start_index"])
                for d in splitter.create_documents([body])
            ]
        frontier = unit.start
        previous_start = -1
        local_tokens = [s for s, e in counter.tokenizer.encode(body).offsets if e > s]
        for part, (piece, local_start) in enumerate(pieces, 1):
            # LangChain's start_index overlap arithmetic assumes characters;
            # locate token-overlapped slices explicitly instead.
            if previous_start >= 0:
                previous_end = frontier - unit.start
                token_index = max(0, bisect_right(local_tokens, previous_end) - overlap - 3)
                search_start = previous_end if not overlap else local_tokens[token_index]
                local_start = body.find(piece, max(previous_start + 1, search_start))
            elif local_start < 0 or body[local_start : local_start + len(piece)] != piece:
                local_start = body.find(piece)
            if local_start < 0 or body[local_start : local_start + len(piece)] != piece:
                raise ValueError("Splitter source coordinates could not be verified")
            previous_start = local_start
            start = unit.start + local_start
            end = start + len(piece)
            if text[frontier:start].strip():
                raise ValueError("Chunking lost non-whitespace source text")
            frontier = max(frontier, end)
            content = prefix + piece
            count = counter.count(content)
            if count > maximum:
                raise ValueError(f"Chunk exceeds {maximum}-token maximum: {count}")
            index = len(chunks)
            content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
            token_start = max(0, bisect_right(token_offsets, start) - 1)
            token_end = bisect_right(token_offsets, end - 1)
            chunks.append(
                {
                    "chunk_index": index,
                    "content": content,
                    "content_hash": content_hash,
                    "token_count": count,
                    "section_ordinal": ordinal,
                    "metadata": {
                        "pipeline_version": VERSION,
                        "source_hash": source_hash,
                        "page_start": bisect_right(page_starts, start),
                        "page_end": bisect_right(page_starts, end - 1),
                        "source_char_start": start,
                        "source_char_end": end,
                        "source_byte_start": byte_offsets[start],
                        "source_byte_end": byte_offsets[end],
                        "source_token_start": token_start,
                        "source_token_end": token_end,
                        "section": unit.heading,
                        "section_path": unit.path,
                        "section_type": unit.kind,
                        "identifier": unit.identifier,
                        "aphorism": unit.identifier if unit.kind == "aphorism" else None,
                        "source_marker_gap_after": (
                            list(
                                range(int(unit.identifier) + 1, int(units[ordinal + 1].identifier))
                            )
                            if unit.kind == "aphorism"
                            and ordinal + 1 < len(units)
                            and units[ordinal + 1].kind == "aphorism"
                            else []
                        ),
                        "remedy": unit.identifier if category == "materia_medica" else None,
                        "rubric_path": unit.path if category == "repertory" else None,
                        "linked_part": part,
                        "linked_parts": len(pieces),
                        "utf8_bytes": len(content.encode("utf-8")),
                        "embedding_model": model,
                        "embedding_dimensions": 1024,
                        "tokenizer_hash": counter.hash,
                        "preferred_minimum": minimum,
                    },
                }
            )
        if text[frontier : unit.end].strip():
            raise ValueError("Chunking did not cover the end of a section")
    return sections, chunks


def processing_parts(
    chunks: list[dict[str, Any]],
    source_bytes: int,
    source_tokens: int,
    threshold: int = 100_000,
) -> list[dict[str, Any]]:
    """Two independent contiguous workloads, preferably divided at a section."""
    if not chunks:
        return []
    cuts = [0, len(chunks)]
    if source_tokens > threshold and len(chunks) > 1:
        candidates = [
            i
            for i in range(1, len(chunks))
            if chunks[i]["section_ordinal"] != chunks[i - 1]["section_ordinal"]
        ]
        candidates = candidates or list(range(1, len(chunks)))
        cut = min(
            candidates,
            key=lambda i: abs(chunks[i]["metadata"]["source_token_start"] - source_tokens / 2),
        )
        cuts.insert(1, cut)
    parts = []
    for n, (start, end) in enumerate(zip(cuts, cuts[1:]), 1):
        first, last = chunks[start]["metadata"], chunks[end - 1]["metadata"]
        for chunk in chunks[start:end]:
            chunk["metadata"]["processing_part"] = n
        parts.append(
            {
                "part": n,
                "chunk_start": start,
                "chunk_end": end,
                "page_start": first["page_start"],
                "page_end": last["page_end"],
                "section_start": first["section"],
                "section_end": last["section"],
                "source_byte_start": 0 if start == 0 else first["source_byte_start"],
                "source_byte_end": source_bytes
                if end == len(chunks)
                else chunks[end]["metadata"]["source_byte_start"],
                "source_token_start": 0 if start == 0 else first["source_token_start"],
                "source_token_end": source_tokens
                if end == len(chunks)
                else chunks[end]["metadata"]["source_token_start"],
            }
        )
    return parts
