"""AI package: provider adapters' future pipeline modules.

Provider protocols and concrete adapters live in app/services (single wiring
point). The subpackages here are reserved for the Phase 2+ pipeline:
llm/ (chains & prompts), embeddings/ (batch jobs), rag/ (retrieval logic),
ingestion/ (document loaders & chunking), graphs/ (LangGraph workflows),
evaluation/ (RAG eval harness).
"""
