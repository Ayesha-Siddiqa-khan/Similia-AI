-- Phase 2, migration 1: enable pgvector (the only vector database used).
--
-- Embedding dimension: 1024. Verified against current Voyage AI docs
-- (docs.voyageai.com, Oct 2026): voyage-4-lite outputs 1024 dimensions by
-- default. If the model or output_dimension changes, the vector columns in
-- migration 2 must change with it.

create extension if not exists vector with schema extensions;
