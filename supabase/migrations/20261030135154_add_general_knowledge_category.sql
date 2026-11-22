-- Recorded version returned by the authenticated Supabase migration service.
-- General clinical/philosophy/reference PDFs use their own category.
alter type public.knowledge_category add value if not exists 'general';
