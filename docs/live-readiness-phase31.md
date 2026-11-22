# Similia AI — Phase 3.1 readiness verification

Verified 2026-10-30, Asia/Karachi. Project: `ivlmduwdkwgrxqxjjuyg`.

Configuration and read-only storage verification are complete. Authenticated
acceptance testing is blocked on creation/identification of the intended test
operator. Live embedding and retrieval remain stopped pending provider evidence
and explicit approval. No clinical features were added.

## 1. Authentication readiness

All five requested settings are now configured and consistent:

| Setting | Result |
|---|---|
| NEXT_PUBLIC_SUPABASE_URL | Configured for the selected Similia project |
| NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY | Existing active modern publishable key reused |
| API_BASE_URL | Configured for the local FastAPI server |
| SUPABASE_URL | Existing selected project retained |
| SUPABASE_PUBLISHABLE_KEY | Configured to match the frontend public key |

The authenticated project-scoped MCP connection retrieved existing key metadata.
No key was generated or rotated, and no credential was printed. Only the public
URL/key and API base URL were written to ignored `frontend/.env.local`; only
SUPABASE_PUBLISHABLE_KEY was added to existing `backend/.env`. Secret and AI keys
were not placed in frontend configuration or reports. No credentials were committed.

The hosted Supabase plugin still denied its project-key lookup with the exact
message “You do not have permission to perform this action.” Its account access
is separate from the working local project MCP connection. The latter successfully
performed the key lookup and read-only SQL audit; Data API connectivity alone was
not treated as evidence of management or migration permission.

SSR uses getAll/setAll, early getClaims in proxy.ts, getUser in protected layouts
and API handlers, cookie propagation, and private/no-store responses. The backend
independently verifies bearer identities. Missing auth never falls back to a live
unauthenticated workspace. This follows the current [Supabase SSR documentation](https://supabase.com/docs/guides/auth/server-side/nextjs).

After configuration, Next.js was rebuilt and the owned local production/backend
processes restarted. The login form is enabled. A read-only Auth settings request
returned HTTP 200 and confirmed email authentication is enabled. This verifies
configuration/service reachability, not a successful user login.

## 2. Operator readiness and required owner action

Read-only Auth verification found **0 users, 0 confirmed users, 0 operators**.
No account or role was created or changed. The operator identity cannot be chosen
on the owner's behalf.

Authorization requires verified `app_metadata.similia_role` equal to `operator`
or `admin`. User-editable user_metadata is ignored by both frontend and backend.
An ordinary authenticated account does not gain library access. Current
[Supabase RLS guidance](https://supabase.com/docs/guides/database/postgres/row-level-security)
distinguishes trusted app metadata from user-editable metadata.

Owner action:

1. In the **Similia** project, open Supabase Dashboard → Authentication → Users →
   Add user and create the intended non-patient test account. Choose and retain
   its password locally; do not send a password or session token in chat.
2. Provide the exact Auth user UUID and identify it as the intended operator.
   Only that account should receive `app_metadata.similia_role = operator`.
3. An authorized administrator can use the server-only Auth Admin API, preserving
   existing app metadata. Do not change user_metadata or grant roles to all users.

The precise server-side role operation, **not executed**, is:

```python
from app.services.supabase import get_supabase_admin_client

client = get_supabase_admin_client()
user_id = "<owner-approved Auth user UUID>"
user = client.auth.admin.get_user_by_id(user_id).user
assert user is not None
client.auth.admin.update_user_by_id(
    user_id,
    {"app_metadata": {**user.app_metadata, "similia_role": "operator"}},
)
```

This uses the existing backend-only credential through its configured client.
See the [official Auth Admin API](https://supabase.com/docs/reference/python/auth-admin-updateuserbyid).
Sign out and sign in again after role assignment so refreshed session claims are
used. Then test login, authorized pages and logout in the browser. No real patient
information is needed.

## 3. Supabase connectivity and vector audit

Authenticated project MCP SQL and the existing backend admin Data API client both
worked. The SQL audit was read-only; no tables, migrations, grants or policies
were modified.

* Seven knowledge books and **6,903 planned chunk rows** are present.
* **2,676 non-null vectors** are committed. Every per-book count and the exact set
  of embedded chunk indexes match the SQLite checkpoint.
* The actual column type is `vector(1024)`; every stored vector has 1,024 dimensions.
* Global duplicate chunk IDs: **0**. Per-book duplicate sequence indexes: **0**.
* All book plan hashes match frozen local plans.
* All 6,903 rows have source byte/token/page metadata; source hashes and checked
  bounds have **0 mismatches**.
* Fourteen representative stored passages, two per book, exactly match frozen
  content, content hashes, byte/token coordinates and page ranges.
* RLS remains enabled on knowledge_books, knowledge_sections, knowledge_chunks,
  ingestion_jobs and retrieval_evaluations. Existing policy count is zero,
  preserving the intended direct-client deny-by-default arrangement.
* A publishable-key anonymous library request returned HTTP 200 with **0 rows**;
  this is not authorized operator access.
* No active jobs; excluded Kent book absent.

## 4. HTTP 429 findings

The last provider failure was request 176, `RateLimitError`, HTTP 429, at
**20:15:54 PKT on 2026-10-30**. The SDK endpoint was `ai.mongodb.com`, using
voyage-4-lite. It follows 175 successful requests and 637,443 provider tokens.

The journal retained status, time and token reservation, but **not** the provider
response body, error code, request ID, Retry-After or rate-limit headers. A
quota/billing keyword matched the existing safety guard on the first failure.
That classification is not proof that free credits were exhausted.

| Possible cause | Finding |
|---|---|
| Request rate | Possible; 429 is documented for RPM limits; account/project limits and provider receipt times are unavailable |
| Token throughput | Possible; this pipeline's local rolling-minute reservation was only 3,650 tokens, but lower configured limits or other clients cannot be excluded |
| Temporary restriction | Not confirmed or excluded by saved evidence |
| Account quota restriction | Not confirmed; original error body and account balance are unavailable |

At failure, the journal shows three attempts in the preceding rolling minute,
including the rejected attempt. This cannot reconstruct provider-side accounting
or traffic from other keys/clients. Exact root cause therefore remains **undetermined**.

MongoDB documents separate RPM and TPM limits and free-trial defaults of 3 RPM /
10,000 TPM without a payment method. Project limits can be lower than organization
limits. These are throughput limits, not remaining free-token balances. See the
[API overview](https://www.mongodb.com/docs/voyageai/api-reference/overview/) and
[rate-limit management documentation](https://www.mongodb.com/docs/voyageai/management/rate-limits/).

The user's original allowance remains recorded as 1,000,000; the cumulative
pipeline cap remains **900,000**, including prior usage, with 100,000 outside the
pipeline cap. Remaining pipeline headroom is **262,557**. Neither monthly usage
nor current public offers establish the account's remaining free allowance.

Safest recovery, **not performed**:

1. Leave provider stop, selection and ledger intact. There are zero in-flight
   requests requiring ambiguous-response reconciliation.
2. In Atlas AI Model APIs, inspect the correct organization/project's usage,
   remaining free allowance, actual voyage-4-lite RPM/TPM limits and any restrictions
   around the failure time. Rate-limit viewing needs Project Read Only or higher
   at project level. Do not reset limits, add a payment method or buy credits for
   this investigation.
3. Obtain the provider's original error details from existing dashboard/support
   records if available. Do not send a new embedding request just to reproduce it.
4. After the condition is understood/resolved, obtain explicit approval for any
   bounded, journal-accounted embedding/retrieval test. Use pacing appropriate to
   verified limits and honor Retry-After; keep the same cumulative cap.
5. Only after explicit resume approval, resume the **same frozen selection** with
   the existing CLI from backend, without --include-added-books. Do not reset or
   edit journal rows. Reconcile any later ambiguous request before replay.

No live vector retrieval, embedding probe, batch retry or resume ran in Phase 3.1.

## 5. Inventory and scope reconciliation

Actual PDF hashes match all eight saved inventory entries. The original three
were Organon, The Homoeopathic Materia Medica and Kent. The original two-smallest
selection used **source-token counts**, not PDF file bytes; it selected Organon
and Materia Medica while excluding Kent.

The owner subsequently added five PDFs and authorized processing the added books
within the original free allowance. The expanded run saved seven selected hashes,
kept Kent excluded and retained prior checkpoint usage. The later 900,000 cap
applies cumulatively, not separately to each new run. No scope expansion occurred
during Phase 3 or this readiness task.

| PDF | Saved status | Committed vectors / planned chunks | Actual provider tokens |
|---|---|---:|---:|
| Antidote_List.pdf | Completed | 6 / 6 | 2,024 |
| Organon of Medicine 6th edition.pdf | Completed | 353 / 353 | 75,534 |
| TheChronicDiseases.pdf | Completed | 615 / 615 | 127,342 |
| Hartman's Acute Disease_vol2.pdf | Completed | 545 / 545 | 135,280 |
| Hartman's Chronic Diseases IIIrd Edition.pdf | Completed | 641 / 641 | 162,260 |
| Synoptic_Materia_medica_I.pdf.pdf | Paused on provider stop | 174 / 3,537 | 14,418 |
| The_Homoeopathic_Materia_Medica.pdf | Paused earlier at the original cap; expanded run stopped before reaching it again | 342 / 1,206 | 120,585 |
| KENT-Repertory-Rev- from Homeoint.pdf | Excluded | 0 / no selected plan | 0 in this pipeline |

Five selected books completed, two partial, **4,227 chunks remain**. Total requests:
175 successful, one rejected, zero in-flight/ambiguous. Remote historical paused
jobs use status failed with stage paused; this does not mean stored vectors were
lost.

The screenshot's **Demonstration · Organon, 28/40 = 70%** is a synthetic fixture
at `/preview/*`. Its paused status is illustrative. The real Organon is
**353/353 = 100%**. Synthetic preview records are not actual ingestion results.

## 6. Integration verification

After configuring auth and rebuilding:

| Check | Result |
|---|---|
| Supabase Auth settings | HTTP 200; email provider enabled |
| Login page | Enabled; invalid email validation verified locally |
| Successful login/logout with operator | Blocked: no Auth account/approved operator UUID |
| Unsigned dashboard/books/ingestion/chunks/settings access | Redirects to login |
| Unsigned Next.js book API | HTTP 401 |
| Cross-origin logout request | HTTP 403 |
| Backend health through frontend | backend=ok, HTTP 200 |
| Actual FastAPI GraphQL liveness | Correct health response |
| Authenticated frontend inventory/monitor/chunks/GraphQL proxy | Awaiting operator session; no bypass used |
| Direct read-only inventory and stored source verification | Passed as described above |
| Live semantic retrieval | Not run; provider stop and approval gate preserved |

Phase 3.1 reruns: **18 frontend tests passed**, **5 targeted backend auth/monitor
tests passed**, targeted Ruff passed; rebuilt production application and build
TypeScript checks passed. The previous Phase 3 full backend suite passed 67 tests.
Current frontend/backend tests use explicit fixtures for unavailable sessions;
fixture success is not claimed as authenticated production connectivity.

## 7. Remaining blockers and next phase

1. Owner creates/identifies the intended test Auth user and supplies its UUID;
   assign operator to that account through authorized Auth administration, then
   complete a real login → dashboard → inventory → monitoring → chunks → logout
   acceptance test. Do not send passwords or session tokens in chat.
2. Owner verifies the actual Atlas rate/usage restriction and available free
   allowance. Keep all embedding operations stopped until explicit approval.

Recommended next implementation phase: **Phase 3.2 — authenticated RAG acceptance
and provider-error observability**. First finish the operator acceptance checks.
Then preserve sanitized future provider error codes, timestamps, request IDs and
Retry-After/rate-limit evidence without credentials. After a separately approved,
budgeted query test, evaluate retrieval source traceability before enabling any
live ingestion HTTP controls. Do not introduce clinical/patient features yet.

## 8. Preservation and evidence

Checkpoint SHA-256 before/after:
`d1ada0b5b881942ff5d6ac95dd5dc013f3d7ee3325c091727c7cb3de3017f9a6`.
Saved manifest SHA-256:
`67de72dcfdaf49ad1029d9026116b7f64043005c335ee17a1f37c7de0f9114b0`.
No ledger, frozen plan, PDF, selection, RLS control, migration or provider-stop
state was modified. No key regeneration, dependency installation, role grant or
embedding call occurred.

Credential-free evidence files in ignored reports/ingestion:
phase31_configuration.json, phase31_storage_audit.json,
phase31_connectivity.json, phase31_reconciliation.json,
phase31_provider_findings.json and phase31_readiness.json.

Account-wide remaining free balance and coding-agent context/token usage remain
unavailable. Retrieval of historical homeopathic text is not evidence of clinical
efficacy.
