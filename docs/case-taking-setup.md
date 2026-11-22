# Case-taking setup (Phase 1, practitioner workspace)

Follow these steps once before using Patients and AI Case Workspace with real services.
The application contains no demo or synthetic data: every page shows only the real records you create.

## 1. Apply the database migration

File: `supabase/migrations/20261122120000_patient_cases.sql` (adds `patients`, `consents`,
`cases`, `case_symptoms`, `case_analyses`, `case_reviews`, `audit_log`, all with RLS).

Option A, Supabase CLI (project must be linked):

```powershell
supabase db push
```

Option B: open the Supabase dashboard, SQL Editor, paste the file contents, run it.

Check: Table Editor shows the 7 new tables with RLS enabled.

## 2. Create a practitioner account

1. Supabase dashboard, Authentication, Users, Add user (email + password).
2. In the SQL Editor give that user the trusted role (replace the email). The role must be in
   `raw_app_meta_data` (app_metadata), never user metadata:

```sql
update auth.users
set raw_app_meta_data = coalesce(raw_app_meta_data, '{}'::jsonb) || '{"similia_role": "practitioner"}'
where email = 'doctor@example.com';
```

3. The user must sign out and in again so the new role is in their session.

Roles: `practitioner` sees Patients and AI Case Workspace only. `operator` and `admin` also
see the knowledge-base pages.

## 3. Check configuration (names only, keep values out of git)

Backend: `SUPABASE_URL`, `SUPABASE_SECRET_KEY`, `ANTHROPIC_API_KEY`, `ANTHROPIC_MODEL`,
`VOYAGE_API_KEY`, `VOYAGE_MODEL`, `CORS_ORIGINS`.
Frontend: `NEXT_PUBLIC_SUPABASE_URL`, `NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY`, `API_BASE_URL`.

## 4. Unblock search (needed for useful analysis)

Analysis returns 429 while `reports/ingestion/run_manifest.json` says
`stopped_provider_http_429`, and gives "insufficient sources" until enough chunks are embedded.
Per `docs/live-readiness-phase31.md`: verify your Voyage rate/usage limits first, then resume
ingestion only after you approve the spend. The Kent Repertory still needs ingesting.

## 5. Run

```powershell
cd backend; uv run uvicorn app.main:app --reload
```

```powershell
cd frontend; npm run dev
```

Restart `npm run dev` if styles look stale after a production build.

## 6. Smoke test with your own first patient

1. Sign in as the practitioner, open Patients, New patient, tick consent, create.
2. Start new case, fill a few steps, wait for "All changes saved".
3. Analyse, Run analysis. Expect cited remedies, or "insufficient sources" if the knowledge
   base is thin.
4. Enter "crushing chest pain" in the complaint and re-run: the analysis must stop with the
   urgent-concern notice.
5. Sign off the case; its status becomes "Signed off".

## Before real patients

Review the AI and embedding providers' data-retention terms, get legal review on
medical-device and privacy rules (DPDP/GDPR), and test with a pilot doctor first.
