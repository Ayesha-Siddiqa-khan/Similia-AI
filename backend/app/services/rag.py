"""RAG services and traceability metadata.

Pipeline (Phase 2): ingestion -> cleaning -> structure-aware chunking ->
Voyage embeddings -> Supabase pgvector -> retrieval -> Claude -> structured
output. Metadata here preserves source traceability for every chunk.
"""

from enum import Enum
from typing import Protocol

from pydantic import BaseModel


class KnowledgeSource(str, Enum):
    """Knowledge categories, including general clinical and philosophy texts."""

    MATERIA_MEDICA = "materia_medica"
    REPERTORY = "repertory"
    ORGANON = "organon"
    GENERAL = "general"


class DocumentMetadata(BaseModel):
    """Traceability metadata attached to every ingested chunk."""

    source: KnowledgeSource
    title: str
    author: str | None = None
    section: str | None = None
    page: int | None = None


class IngestedChunk(BaseModel):
    """A chunk of text ready for embedding, with its source metadata."""

    text: str
    metadata: DocumentMetadata


class DocumentIngestionService(Protocol):
    """Ingests documents and produces embeddable chunks (implemented Phase 2)."""

    def ingest(self, raw_text: str, metadata: DocumentMetadata) -> list[IngestedChunk]:
        """Clean and structure-aware chunk a raw document."""
        ...


class RetrievalService(Protocol):
    """Retrieves relevant chunks for a query (implemented Phase 2)."""

    def retrieve(self, query: str, k: int = 5) -> list[IngestedChunk]:
        """Embed the query and return the k most relevant chunks."""
        ...
