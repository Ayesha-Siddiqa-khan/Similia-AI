"""Service layer: Supabase, LLM, embeddings, vector store, and RAG services.

Each service initialises safely without making external API calls; clients are
created lazily on first real use.
"""

from app.services.embeddings import EmbeddingProvider, VoyageEmbeddingProvider
from app.services.llm import AnthropicLLMProvider, LLMProvider
from app.services.rag import DocumentIngestionService, RetrievalService
from app.services.supabase import get_supabase_client
from app.services.vector_store import SupabasePgVectorStore, VectorStore

__all__ = [
    "AnthropicLLMProvider",
    "DocumentIngestionService",
    "EmbeddingProvider",
    "LLMProvider",
    "RetrievalService",
    "SupabasePgVectorStore",
    "VectorStore",
    "VoyageEmbeddingProvider",
    "get_supabase_client",
]
