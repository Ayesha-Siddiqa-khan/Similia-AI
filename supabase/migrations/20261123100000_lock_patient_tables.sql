-- Lock the patient, case and key tables so only the backend can touch them.
--
-- Why: Supabase grants table privileges to the signed-in role by default. The patient tables have an
-- owner policy (FOR ALL TO authenticated), so ANY signed-in Supabase user holding the public
-- publishable key could insert, change or delete their own rows directly through the REST API. That
-- skips the backend's role check, the consent rule and the audit log (for example, forging a
-- consent row). The app never reads these tables from the browser, so nothing is lost by revoking.
--
-- Row level security and its policies stay on as a second layer. The backend uses the service role,
-- which is not affected by these revokes.
--
-- Apply with the SQL Editor after reviewing. It only removes privileges; it deletes no data and is
-- safe to run more than once.

revoke all on
    public.patients,
    public.consents,
    public.cases,
    public.case_symptoms,
    public.case_analyses,
    public.case_reviews,
    public.audit_log,
    public.user_ai_settings
from anon, authenticated;

-- The knowledge tables are also backend-only (RLS enabled, no policies). Remove the default
-- grants as well, so the lock does not depend on RLS alone.
revoke all on
    public.knowledge_books,
    public.knowledge_sections,
    public.knowledge_chunks,
    public.ingestion_jobs,
    public.retrieval_evaluations
from anon, authenticated;

-- The audit log's id sequence is granted by default too.
revoke all on all sequences in schema public from anon, authenticated;

-- Check afterwards (should return no rows):
--   select grantee, table_name, privilege_type
--   from information_schema.role_table_grants
--   where table_schema = 'public' and grantee in ('anon', 'authenticated');
