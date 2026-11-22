-- Keyword search over the stored book text. It needs no embedding provider, so passages stay
-- findable while meaning-based (vector) search is unavailable. Run once in the SQL editor of
-- project ivlmduwdkwgrxqxjjuyg only. It adds one index and one function; nothing is deleted.
--
-- p_tsquery is built by the backend from letters only, e.g. 'burning | warmth | night'.

create index if not exists knowledge_chunks_content_fts
    on public.knowledge_chunks using gin (to_tsvector('english', content));

create or replace function public.keyword_match_chunks(
    p_tsquery text,
    match_count integer default 10,
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
    with q as (select to_tsquery('english', p_tsquery) as tsq)
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
        -- Rank 0..1 (normalisation 32 = rank / (rank + 1)). It is a keyword score, not a
        -- cosine similarity.
        ts_rank_cd(to_tsvector('english', c.content), q.tsq, 32)::double precision as similarity
    from knowledge_chunks c
    join knowledge_books b on b.id = c.book_id
    left join knowledge_sections s on s.id = c.section_id
    cross join q
    where to_tsvector('english', c.content) @@ q.tsq
      and (filter_category is null or b.category = filter_category)
    order by similarity desc
    limit least(greatest(match_count, 1), 50);
$$;

revoke execute on function public.keyword_match_chunks(text, integer, knowledge_category)
    from public, anon, authenticated;
grant execute on function public.keyword_match_chunks(text, integer, knowledge_category)
    to service_role;
