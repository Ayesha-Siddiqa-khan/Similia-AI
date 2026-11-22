-- Phase 2, migration 2: knowledge-base schema.
--
-- Tables: knowledge_books, knowledge_sections, knowledge_chunks,
-- ingestion_jobs, retrieval_evaluations.
-- Embedding dimension is vector(1024) (voyage-4-lite default).
-- No patient records exist in this phase.

create type knowledge_category as enum ('materia_medica', 'repertory', 'organon');
create type ingestion_status as enum ('pending', 'running', 'completed', 'failed');

-- One row per registered book. content_hash gives duplicate detection;
-- raw_text (extracted at registration) enables re-chunking and resume
-- without re-uploading the source file.
-- ponytail: raw_text keeps the extracted text in Postgres instead of a
-- storage bucket; fine for a single-operator admin tool, upgrade path is a
-- Supabase Storage object referenced by source_uri.
create table knowledge_books (
    id uuid primary key default gen_random_uuid(),
    category knowledge_category not null,
    title text not null,
    author text,
    publisher text,
    publication_year integer,
    language text not null default 'en',
    source_filename text not null,
    source_uri text,
    content_hash text not null unique,
    raw_text text not null,
    metadata jsonb not null default '{}'::jsonb,
    section_count integer not null default 0,
    chunk_count integer not null default 0,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    constraint knowledge_books_title_not_blank check (length(trim(title)) > 0)
);

comment on column knowledge_books.content_hash is
    'sha256 hex digest of the uploaded source bytes; unique per book for duplicate detection';

-- Detected document structure (chapters, remedies, rubric branches,
-- aphorisms). path is the full heading ancestry, e.g.
-- {Nervous system, Head, Vertigo}. Sections are derived data: re-ingesting
-- a book replaces them (upsert keyed on book_id + ordinal).
create table knowledge_sections (
    id uuid primary key default gen_random_uuid(),
    book_id uuid not null references knowledge_books (id) on delete cascade,
    parent_section_id uuid references knowledge_sections (id) on delete set null,
    ordinal integer not null,
    heading text not null,
    section_type text not null default 'generic',
    path text[] not null default '{}'::text[],
    page_start integer,
    page_end integer,
    metadata jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now(),
    unique (book_id, ordinal)
);

create index knowledge_sections_book_idx on knowledge_sections (book_id);

-- Embeddable chunks. (book_id, chunk_index) is the resume key: chunking is
-- deterministic for identical source bytes, so an interrupted job re-inserts
-- with ignore-duplicates and only chunks whose embedding is still NULL are
-- sent to the embedding provider.
create table knowledge_chunks (
    id uuid primary key default gen_random_uuid(),
    book_id uuid not null references knowledge_books (id) on delete cascade,
    section_id uuid references knowledge_sections (id) on delete set null,
    chunk_index integer not null,
    content text not null,
    content_hash text not null,
    embedding extensions.vector(1024),
    token_count integer,
    metadata jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now(),
    unique (book_id, chunk_index)
);

create index knowledge_chunks_book_idx on knowledge_chunks (book_id);
create index knowledge_chunks_section_idx on knowledge_chunks (section_id);
-- HNSW + cosine: high-accuracy, read-heavy semantic search (Supabase docs
-- recommend HNSW when recall matters more than memory).
create index knowledge_chunks_embedding_idx on knowledge_chunks
    using hnsw (embedding extensions.vector_cosine_ops);

-- Progress and error tracking for ingestion runs. The partial unique index
-- enforces one active job per book at the database level.
create table ingestion_jobs (
    id uuid primary key default gen_random_uuid(),
    book_id uuid not null references knowledge_books (id) on delete cascade,
    status ingestion_status not null default 'pending',
    stage text not null default 'queued',
    total_chunks integer not null default 0,
    processed_chunks integer not null default 0,
    embedded_tokens bigint not null default 0,
    error text,
    started_at timestamptz,
    finished_at timestamptz,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create index ingestion_jobs_book_idx on ingestion_jobs (book_id);
create unique index ingestion_jobs_one_active_per_book
    on ingestion_jobs (book_id) where status in ('pending', 'running');

-- Retrieval-quality records for future evaluation loops (query, top-k,
-- retrieved chunk ids/scores, latency). Written by the backend only.
create table retrieval_evaluations (
    id uuid primary key default gen_random_uuid(),
    query_text text not null,
    category_filter knowledge_category,
    k integer not null,
    results jsonb not null default '[]'::jsonb,
    embedding_model text not null,
    latency_ms integer,
    notes text,
    created_at timestamptz not null default now()
);

-- ---------------------------------------------------------------------------
-- Row Level Security: deny-by-default. RLS is enabled on every knowledge
-- table and no policy grants anything to anon or authenticated, so all
-- reads and writes must go through the backend using the service-role key
-- (which bypasses RLS). If direct client reads are ever needed, add a
-- read-only select policy for authenticated explicitly.
-- ---------------------------------------------------------------------------
alter table knowledge_books enable row level security;
alter table knowledge_sections enable row level security;
alter table knowledge_chunks enable row level security;
alter table ingestion_jobs enable row level security;
alter table retrieval_evaluations enable row level security;
