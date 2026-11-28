"""Typed records shared by the fine-tuning dataset modules."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class BookRecord:
    """A ``knowledge_books`` row without ``raw_text``."""

    id: str
    title: str
    author: str | None
    publisher: str | None
    publication_year: int | None
    language: str | None
    category: str
    source_filename: str
    source_uri: str | None
    content_hash: str
    section_count: int
    chunk_count: int

    @property
    def display_author(self) -> str:
        return (self.author or "Unknown author").strip()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ChunkRecord:
    """A ``knowledge_chunks`` row with the embedding column never selected."""

    id: str
    book_id: str
    section_id: str | None
    chunk_index: int
    content: str
    content_hash: str
    token_count: int | None
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def page_start(self) -> int | None:
        value = self.metadata.get("page_start")
        return int(value) if isinstance(value, (int, float)) else None

    @property
    def page_end(self) -> int | None:
        value = self.metadata.get("page_end")
        return int(value) if isinstance(value, (int, float)) else self.page_start


@dataclass(frozen=True)
class SectionRecord:
    """A ``knowledge_sections`` row used to restore chapter provenance."""

    id: str
    book_id: str
    ordinal: int
    heading: str
    path: tuple[str, ...]
    section_type: str | None
    page_start: int | None
    page_end: int | None


@dataclass(frozen=True)
class QualityScore:
    characters: int
    words: int
    alphabetic_ratio: float
    issues: tuple[str, ...]
    usable: bool
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class CleanChunk:
    """A cleaned chunk plus its quality result and duplicate resolution."""

    chunk: ChunkRecord
    book: BookRecord
    section: SectionRecord | None
    text: str
    removed: tuple[str, ...]
    quality: QualityScore
    duplicate_of: str | None = None
    duplicate_kind: str | None = None

    @property
    def usable(self) -> bool:
        return self.quality.usable and self.duplicate_of is None

    @property
    def pages(self) -> tuple[int | None, int | None]:
        return (self.chunk.page_start, self.chunk.page_end)


@dataclass(frozen=True)
class LicenceDecision:
    status: str
    basis: str
    evidence: tuple[str, ...]
    author_death_year: int | None
    legal_review: str
    exportable: bool
    display_author: str | None = None
    notes: str = ""

    @property
    def cleared(self) -> bool:
        return self.status == "cleared_public_domain"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class SplitAssignment:
    book_id: str
    content_hash: str
    title: str
    category: str
    split: str
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
