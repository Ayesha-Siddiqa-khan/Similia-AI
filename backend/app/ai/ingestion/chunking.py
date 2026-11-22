"""Structure-aware chunking, one strategy per knowledge category.

- Materia Medica: chunks stay inside remedy sections; every chunk is
  prefixed with its remedy (and symptom) heading so passages retrieve well
  standalone.
- Repertory: rubric hierarchies are preserved; each chunk carries the full
  rubric path ("chapter > rubric > sub-rubric") and keeps remedy entries
  with their rubric.
- Organon: aphorism identifiers (§-numbers) define chunk boundaries; a
  chunk is one or more whole aphorisms and never splits mid-aphorism
  unless a single aphorism exceeds the size budget.

ponytail: structure detection is regex/indentation heuristics over plain
extracted text. They are tolerant (fallback: paragraph chunking under the
nearest detected heading) but not perfect on heavily stylised PDFs; the
upgrade path is pymupdf "dict" mode font/size analysis.
"""

import hashlib
import re
from dataclasses import dataclass, field

from app.ai.ingestion.extraction import PageText

MAX_CHUNK_CHARS = 2000

_APHORISM_RE = re.compile(r"^\s*(?:§+\s*(\d+)|aph(?:orism)?\.?\s+(\d+))\s*[.):\-]?\s*", re.I)
_CAPS_HEADING_RE = re.compile(r"[A-Z0-9][A-Z0-9\s.'\-&,()/]{2,}")
_ENTRY_RE = re.compile(r"^[a-z][\w.\-]*\.?(?:\s*,?\s*[a-z][\w.\-]*\.?\s*\d+[+-]?)*$")
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?;:])\s+")


@dataclass
class Section:
    """A detected structural section (remedy, chapter, aphorism...)."""

    ordinal: int
    heading: str
    section_type: str
    path: list[str]
    page_start: int | None = None
    page_end: int | None = None
    metadata: dict = field(default_factory=dict)


@dataclass
class Chunk:
    """An embeddable chunk with its structural context."""

    chunk_index: int
    content: str
    section_ordinal: int | None
    page_start: int | None
    page_end: int | None
    metadata: dict = field(default_factory=dict)

    @property
    def token_estimate(self) -> int:
        return max(1, len(self.content) // 4)

    @property
    def content_hash(self) -> str:
        return hashlib.sha256(self.content.encode("utf-8")).hexdigest()


@dataclass
class ChunkingResult:
    sections: list[Section]
    chunks: list[Chunk]


@dataclass
class _Paragraph:
    text: str
    page: int


def chunk_document(pages: list[PageText], category: str) -> ChunkingResult:
    """Chunk cleaned pages using the category's strategy."""
    if category == "organon":
        return _chunk_organon(pages)
    if category == "materia_medica":
        return _chunk_materia_medica(pages)
    if category == "repertory":
        return _chunk_repertory(pages)
    if category == "general":
        return _chunk_general(pages)
    raise ValueError(f"Unknown knowledge category: {category}")


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _paragraphs(pages: list[PageText]) -> list[_Paragraph]:
    paragraphs: list[_Paragraph] = []
    for page in pages:
        for block in re.split(r"\n\s*\n", page.text):
            block = block.strip()
            if block:
                paragraphs.append(_Paragraph(text=block, page=page.page))
    return paragraphs


def _is_caps_heading(line: str, max_len: int = 80) -> bool:
    stripped = line.strip()
    if not (3 <= len(stripped) <= max_len) or not _CAPS_HEADING_RE.fullmatch(stripped):
        return False
    letters = [c for c in stripped if c.isalpha()]
    return len(letters) >= 3 and sum(c.isupper() for c in letters) / len(letters) > 0.8


def _split_long(text: str, limit: int = MAX_CHUNK_CHARS) -> list[str]:
    """Hard-split an oversized block at sentence, then word, boundaries."""
    if len(text) <= limit:
        return [text]
    pieces: list[str] = []
    current = ""
    for sentence in _SENTENCE_SPLIT_RE.split(text):
        while len(sentence) > limit:  # pathological single sentence
            pieces.append(sentence[:limit])
            sentence = sentence[limit:]
        candidate = f"{current} {sentence}".strip()
        if len(candidate) > limit and current:
            pieces.append(current)
            current = sentence
        else:
            current = candidate
    if current:
        pieces.append(current)
    return pieces


class _ChunkBuilder:
    """Accumulates finalized chunks with sequential indexes."""

    def __init__(self) -> None:
        self.chunks: list[Chunk] = []

    def add(
        self,
        content: str,
        section_ordinal: int | None,
        page_start: int | None,
        page_end: int | None,
        metadata: dict,
    ) -> None:
        content = content.strip()
        if not content:
            return
        for piece in _split_long(content):
            self.chunks.append(
                Chunk(
                    chunk_index=len(self.chunks),
                    content=piece,
                    section_ordinal=section_ordinal,
                    page_start=page_start,
                    page_end=page_end,
                    metadata=dict(metadata),
                )
            )


# ---------------------------------------------------------------------------
# Materia Medica: remedy sections + symptom-aware paragraph chunks
# ---------------------------------------------------------------------------


def _chunk_materia_medica(pages: list[PageText]) -> ChunkingResult:
    sections: list[Section] = []
    builder = _ChunkBuilder()
    current_section: Section | None = None
    remedy_heading: str | None = None
    symptom_heading: str | None = None
    buffer: list[_Paragraph] = []
    buffer_chars = 0

    def close_buffer() -> None:
        nonlocal buffer, buffer_chars
        if buffer:
            prefix_parts = [p for p in (remedy_heading, symptom_heading) if p]
            prefix = "\n".join(f"== {p} ==" for p in prefix_parts)
            body = "\n\n".join(p.text for p in buffer)
            content = f"{prefix}\n\n{body}" if prefix else body
            builder.add(
                content=content,
                section_ordinal=current_section.ordinal if current_section else None,
                page_start=buffer[0].page,
                page_end=buffer[-1].page,
                metadata={
                    "remedy": remedy_heading,
                    "symptom_heading": symptom_heading,
                },
            )
            buffer, buffer_chars = [], 0

    for paragraph in _paragraphs(pages):
        lines = paragraph.text.split("\n")
        first = lines[0].strip()
        if _is_caps_heading(first) and len(lines) <= 3:
            close_buffer()
            remedy_heading = first.rstrip(".")
            symptom_heading = None
            current_section = Section(
                ordinal=len(sections),
                heading=remedy_heading,
                section_type="remedy",
                path=[remedy_heading],
                page_start=paragraph.page,
                page_end=paragraph.page,
            )
            sections.append(current_section)
            # A short caps paragraph can itself carry content.
            remainder = "\n".join(lines[1:]).strip()
            if remainder:
                buffer = [_Paragraph(text=remainder, page=paragraph.page)]
                buffer_chars = len(remainder)
            continue
        if remedy_heading and ":" in first and len(first.split(":", 1)[0]) <= 70:
            close_buffer()
            symptom_heading = first.split(":", 1)[0]
            if current_section:
                current_section.path = [remedy_heading, symptom_heading]
        if buffer_chars + len(paragraph.text) > MAX_CHUNK_CHARS and buffer:
            close_buffer()
        buffer.append(paragraph)
        buffer_chars += len(paragraph.text)
    close_buffer()
    return ChunkingResult(sections=sections, chunks=builder.chunks)


# ---------------------------------------------------------------------------
# General books: plain paragraph packing, keeping page numbers for citations
# ---------------------------------------------------------------------------


def _chunk_general(pages: list[PageText]) -> ChunkingResult:
    """Books without a remedy/rubric/aphorism structure: pack paragraphs up to the size budget."""
    section = Section(ordinal=0, heading="General text", section_type="text", path=["General text"])
    builder = _ChunkBuilder()
    buffer: list[_Paragraph] = []
    size = 0

    def close() -> None:
        nonlocal buffer, size
        if buffer:
            builder.add(
                content="\n\n".join(p.text for p in buffer),
                section_ordinal=0,
                page_start=buffer[0].page,
                page_end=buffer[-1].page,
                metadata={},
            )
            buffer, size = [], 0

    for paragraph in _paragraphs(pages):
        if buffer and size + len(paragraph.text) > MAX_CHUNK_CHARS:
            close()
        buffer.append(paragraph)
        size += len(paragraph.text)
    close()
    if builder.chunks:
        section.page_start = builder.chunks[0].page_start
        section.page_end = builder.chunks[-1].page_end
    return ChunkingResult(sections=[section] if builder.chunks else [], chunks=builder.chunks)


# ---------------------------------------------------------------------------
# Repertory: rubric-hierarchy-preserving chunks
# ---------------------------------------------------------------------------


def _chunk_repertory(pages: list[PageText]) -> ChunkingResult:
    sections: list[Section] = []
    builder = _ChunkBuilder()
    chapter: Section | None = None
    stack: list[tuple[int, str]] = []
    current_lines: list[str] = []
    current_path: list[str] = []
    page_start = page_end = 0
    front: list[_Paragraph] = []
    explicit_chapters = any(
        re.match(r"^\s*CHAPTER\b", line) for page in pages for line in page.text.splitlines()
    )

    def close_unit() -> None:
        nonlocal current_lines
        if current_lines and chapter:
            builder.add(
                f"Path: {' > '.join(current_path)}\n" + "\n".join(current_lines),
                chapter.ordinal,
                page_start,
                page_end,
                {"rubric_path": list(current_path)},
            )
        current_lines = []

    for page in pages:
        for raw_line in page.text.splitlines():
            stripped = raw_line.strip()
            if not stripped:
                continue
            is_chapter = (
                bool(re.match(r"^CHAPTER\b", stripped))
                if explicit_chapters
                else (
                    _is_caps_heading(stripped, max_len=60)
                    and not _ENTRY_RE.fullmatch(stripped.lower())
                )
            )
            if is_chapter:
                close_unit()
                stack = []
                chapter = Section(
                    len(sections), stripped, "chapter", [stripped], page.page, page.page
                )
                sections.append(chapter)
                current_path = [stripped]
                continue
            if chapter is None:
                front.append(_Paragraph(stripped, page.page))
                continue
            chapter.page_end = page.page
            depth = len(raw_line) - len(raw_line.lstrip(" "))
            remedy_entry = bool(re.search(r"\b\d+[+-]?\b", stripped)) or (
                stripped[0].islower() and bool(_ENTRY_RE.fullmatch(stripped.lower()))
            )
            if not remedy_entry:
                close_unit()
                stack = [(d, heading) for d, heading in stack if d < depth]
                stack.append((depth, stripped.rstrip(":")))
                current_path = [chapter.heading] + [heading for _, heading in stack]
                page_start = page.page
            elif not current_lines:
                page_start = page.page
            current_lines.append(raw_line)
            page_end = page.page
    close_unit()
    if front:
        builder.add(
            "\n".join(p.text for p in front),
            None,
            front[0].page,
            front[-1].page,
            {"rubric_path": [], "section_type": "front_matter"},
        )
    return ChunkingResult(sections=sections, chunks=builder.chunks)


# ---------------------------------------------------------------------------
# Organon: aphorism-preserving chunks
# ---------------------------------------------------------------------------


def _chunk_organon(pages: list[PageText]) -> ChunkingResult:
    sections: list[Section] = []
    builder = _ChunkBuilder()
    aphorisms: list[tuple[int | None, list[str], int, int]] = []  # (number, lines, start, end)
    front_lines: list[str] = []
    front_page = 0

    for page in pages:
        for raw_line in page.text.split("\n"):
            match = _APHORISM_RE.match(raw_line)
            if match:
                number = int(match.group(1) or match.group(2))
                rest = raw_line[match.end() :].strip()
                marker = f"§{number}."
                aphorisms.append((number, [f"{marker} {rest}".strip()], page.page, page.page))
            elif aphorisms:
                number, lines, page_start, _ = aphorisms[-1]
                if raw_line.strip():
                    lines.append(raw_line)
                    aphorisms[-1] = (number, lines, page_start, page.page)
            elif raw_line.strip():
                if not front_lines:
                    front_page = page.page
                front_lines.append(raw_line)

    if front_lines:
        section = Section(
            ordinal=0,
            heading="Front matter",
            section_type="generic",
            path=["Front matter"],
            page_start=front_page,
        )
        sections.append(section)
        text = "\n".join(front_lines).strip()
        builder.add(text, 0, front_page, front_page, {"aphorism": None})

    for number, lines, page_start, page_end in aphorisms:
        section = Section(
            ordinal=len(sections),
            heading=f"§{number}",
            section_type="aphorism",
            path=[f"§{number}"],
            page_start=page_start,
            page_end=page_end,
            metadata={"aphorism": number},
        )
        sections.append(section)
        builder.add(
            content="\n".join(lines).strip(),
            section_ordinal=section.ordinal,
            page_start=page_start,
            page_end=page_end,
            metadata={"aphorism": number},
        )

    # Keep each aphorism independent, including short aphorisms and front matter.
    merged: list[Chunk] = []
    index = 0
    while index < len(builder.chunks):
        chunk = builder.chunks[index]
        parts = [chunk.content]
        end = index
        numbers = [
            builder.chunks[i].metadata.get("aphorism")
            for i in range(index, end + 1)
            if builder.chunks[i].metadata.get("aphorism") is not None
        ]
        merged.append(
            Chunk(
                chunk_index=len(merged),
                content="\n\n".join(parts),
                section_ordinal=chunk.section_ordinal,
                page_start=chunk.page_start,
                page_end=builder.chunks[end].page_end,
                metadata={
                    "aphorism_start": numbers[0] if numbers else None,
                    "aphorism_end": numbers[-1] if numbers else None,
                },
            )
        )
        index = end + 1
    return ChunkingResult(sections=sections, chunks=merged)
