-- Phase 2, migration 3: RPC functions for backend retrieval and batch
-- embedding writes.
--
-- Both functions are SECURITY DEFINER with a pinned search_path and are
-- executable by service_role only: the anon and authenticated roles have no
-- grants on the knowledge tables (RLS deny-by-default, migration 2), so the
-- backend service-role client is the only trusted path.

-- Semantic search over knowledge_chunks. Returns passage text, source
-- identifiers, section information and cosine similarity. Prepared for
-- future keyword/hybrid retrieval: keyword scoring can be added as another
-- parameter/function and merged with RRF at the application layer.
create or replace function match_chunks(
    query_embedding extensions.vector(1024),
    match_count integer default 5,
    match_threshold double precision default 0.0,
    filter_category knowledge_category default null
)
returns table (
    chunk_id uuid,
    book_id uuid,
    section_id uuid,
    chunk_index integer,
    content text,
    chunk_metadata jsonb,
    book_title text,
    book_category knowledge_category,
    book_author text,
    section_heading text,
    section_path text[],
    similarity double precision
)
language sql
stable
security definer
set search_path = public
as $$
    select
        c.id as chunk_id,
        c.book_id,
        c.section_id,
        c.chunk_index,
        c.content,
        c.metadata as chunk_metadata,
        b.title as book_title,
        b.category as book_category,
        b.author as book_author,
        s.heading as section_heading,
        s.path as section_path,
        1 - (c.embedding operator(extensions.<=>) query_embedding) as similarity
    from knowledge_chunks c
    join knowledge_books b on b.id = c.book_id
    left join knowledge_sections s on s.id = c.section_id
    where c.embedding is not null
      and (filter_category is null or b.category = filter_category)
      and 1 - (c.embedding operator(extensions.<=>) query_embedding) > match_threshold
    order by c.embedding operator(extensions.<=>) query_embedding
    limit match_count;
$$;

revoke execute on function match_chunks(extensions.vector, integer, double precision, knowledge_category)
    from public, anon, authenticated;
grant execute on function match_chunks(extensions.vector, integer, double precision, knowledge_category)
    to service_role;

-- Batch-write embeddings produced by the provider back into knowledge_chunks.
-- Accepts jsonb [{"id": uuid, "embedding": [floats], "token_count": int}] and
-- updates atomically in one round trip. Used by the embedding stage; chunk
-- ids come from rows that already have embedding IS NULL, which is what makes
-- interrupted ingestion resume without duplicating or re-embedding work.
create or replace function apply_chunk_embeddings(items jsonb)
returns integer
language plpgsql
security definer
set search_path = public
as $$
declare
    updated_count integer;
begin
    update knowledge_chunks c
    set embedding = (x.embedding)::text::extensions.vector,
        token_count = x.token_count,
        metadata = c.metadata || jsonb_build_object('ingestion_status', 'stored')
    from jsonb_to_recordset(items) as x(id uuid, embedding jsonb, token_count integer)
    where c.id = x.id;
    get diagnostics updated_count = row_count;
    return updated_count;
end;
$$;

revoke execute on function apply_chunk_embeddings(jsonb) from public, anon, authenticated;
grant execute on function apply_chunk_embeddings(jsonb) to service_role;
