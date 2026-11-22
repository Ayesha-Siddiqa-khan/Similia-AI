> **Update (Nov 2026):** the `/preview/*` pages and every synthetic fixture described in this
> document were **removed** from the application. The app now shows only real data. Automated tests
> keep their own sample records under `frontend/src/test/fixtures/` (never shipped to users). The text
> below is kept as a historical record of Phase 3 and no longer describes the running app.

# Similia AI — Phase 3 frontend

Later verification and configuration updates are recorded in
[Phase 3.1 readiness](live-readiness-phase31.md). Its authentication/configuration
findings supersede the original missing-configuration status below.

Implemented in the existing Next.js application on 2026-10-30. Nothing was deployed.
No dependency was installed, no database schema/RLS setting was changed, and no
embedding API request was made during frontend implementation or verification.

## Pages and behavior

Live pages are `/workspace/{section}`. The same sections at `/preview/{section}`
use explicitly labeled synthetic fixtures and never call live data or AI APIs.

| Section | Implemented behavior |
|---|---|
| `dashboard` | Registered-book count from the database API; selected-plan chunk/vector counts, extracted text, local job states, requests, token usage and budget from timestamped reports |
| `knowledge` | Library overview and all selected source plans |
| `books` | Registered books, local inventory, selected/excluded status, processing priority, searchable plan table, book details, extraction statistics, PDF upload validation and registration |
| `ingestion` | Per-book measurements, saved status, part/page, progress, requests, errors, checkpoint and cumulative cap; unsupported controls disabled with explanations |
| `chunks` | Book/category selection, server-side text/section filtering, pagination, token/UTF-8 byte counts, page ranges, remedy/rubric/aphorism metadata, saved embedding status and size statistics |
| `search` | Validated query, source, top-K 1–50 and similarity threshold; explicit live API confirmation; returned passages/scores and error/empty states; book selection filters returned results only |
| `case` | Fixed read-only synthetic case, structured summary preview and labeled future-result panels; no real patient input or persistence |
| `patients` | Explicit unavailable state; no patient storage |
| `settings` | Connection/readiness information, GraphQL health and phase limitations |
| `/login` | Password login, validation, safe errors and preview entry |

The reusable shell includes navigation, active state, mobile drawer, backend
health, user menu, logout, skip link and a light/dark theme toggle. Theme selection
lasts for the current document; it is not saved across full reloads. System fonts
avoid build-time Google Fonts downloads. Tables scroll within their own layout
containment on narrow screens. Native confirmation dialogs provide modal focus
handling and Escape cancellation.

Report refresh uses React Query every 15 seconds while the tab is visible.
Retries are bounded, auth/quota errors are not retried, and failed polling backs
off to 30–120 seconds. Existing data is labeled stale when refreshing fails.
Queries are cancelled using AbortSignal when consumers no longer need them.

## Authentication and configuration

Live authentication is **implemented but not verified with a real account**.
`frontend/.env.local` does not exist, and the backend has no publishable key
configured. Missing configuration leaves login disabled and the live workspace
protected; it does not silently switch to fixtures.

Create `frontend/.env.local` locally using `frontend/.env.example`:

```dotenv
NEXT_PUBLIC_SUPABASE_URL=https://ivlmduwdkwgrxqxjjuyg.supabase.co
NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY=<the project's publishable key>
API_BASE_URL=http://127.0.0.1:8000
```

Never place SUPABASE_SECRET_KEY, a service-role key or any AI key in that file.
The existing backend secret remains server-side in its existing configuration.
Restart Next.js after changing public environment values; rebuild for production.

The session refresh proxy follows `@supabase/ssr` getAll/setAll, calls getClaims
early, propagates refreshed cookies and prevents shared caching. Protected layouts
and the Next.js backend proxy independently call getUser. Supabase identity alone
does not authorize access to the shared privileged knowledge library: a project
administrator must assign trusted `app_metadata.similia_role` to `operator` or
`admin` for the intended operator account. User-editable user_metadata is ignored.
No role or account was created or modified by this task.

FastAPI verifies the bearer token using Supabase Auth get_user and enforces the
same trusted role on all knowledge and monitoring endpoints. Existing callers of
the former unauthenticated admin API now need a verified operator bearer token.
The ingestion CLI is unaffected. Health and GraphQL liveness remain public; they
return no knowledge data. Cookie-authenticated Next.js mutations require same
origin. Proxy responses are private/no-store and upstream error details are
sanitized. Real patient isolation and privacy remain unimplemented; patient
features cannot accept or persist real records.

## API contracts actually connected

The browser uses allowlisted same-origin `/api/backend/*` routes. Those routes
verify session/role, forward the bearer token server-side, and call FastAPI.
Frontend types mirror the Pydantic book/search schemas and monitoring response.

| Backend | Connection |
|---|---|
| `GET /health` | Through existing `/api/health`; live liveness verified |
| `POST /graphql` with `query ServiceHealth { health }` | Fixed GraphQL query through `/api/backend/graphql`; no invented GraphQL data operations |
| `GET /api/books` | Registered-book query with React Query |
| `POST /api/books` | Multipart PDF, title, category; registration only, no embeddings |
| `GET /api/ingestion-jobs/{job_id}` | Allowed by the centralized proxy for existing job lookup; detailed Phase 2B UI reads the saved monitoring snapshot |
| `POST /api/search` | query, k, category, threshold; structured passages and actual cosine similarity |
| **New** `GET /api/monitor/snapshot` | Read-only inventory, per-book report, usage, cap, required action and explicit capabilities |
| **New** `GET /api/monitor/chunks/{file_hash}` | Frozen selected plan; q/section max 200 chars, offset ≥0, limit 1–100; filtered results and summary statistics |

The monitoring service reads existing artifacts only. It removes pending-index
arrays and batch checkpoint lists from snapshots, validates hashes against the
saved selection before reading a plan, and does not touch PDFs, plan files or
the SQLite journal. Counts are last saved checkpoint counts, not a new Supabase
vector audit on every poll. This distinction is displayed by source/timestamp.
Uploaded PDFs are extracted in memory; metadata now retains file/text sizes and
page counts. Original local PDFs are never opened for writing, renamed or deleted.
The backend upload read is bounded to 50 MB plus one byte for rejection.

Live search remains blocked while the manifest says `stopped_provider_http_429`.
The backend enforces this before creating a query embedding. The original quota
stop is not reset by this frontend. A later permitted live search requires
explicit confirmation and records a retrieval evaluation using the existing API;
query embedding usage is outside the Phase 2B ingestion ledger. Do not enter
patient information in search queries.

## Backend support still required

These controls are intentionally unavailable; implementing their HTTP contracts
is future backend work, not an assumption made by the UI:

* Budget-safe Phase 2B start/pause/resume/retry endpoints that own the OS lock,
  frozen selection, cumulative SQLite reservations and provider quota gate.
  The older `POST /api/books/{id}/ingest` endpoint exists, but runs a different
  ingestion path; it is not exposed by the frontend proxy or enabled in the UI.
* Explicit analyze/re-inventory operations without changing frozen plans.
* Validated category review/update for existing books. Upload registration accepts
  materia_medica, repertory and organon only. General is readable for existing
  books; Homeopathic Philosophy/Unknown upload choices are marked unsupported.
  No category is silently mapped to a different database enum.
* Book-scoped vector search. The current API only supports category filtering;
  the book control filters returned hits and cannot claim exhaustive book search.
* Safe extraction/plan preview endpoints for newly uploaded books; the new chunk
  explorer reads existing selected frozen plans only.
* Account-wide provider quota/balance and reliable remaining-work cost estimates.
  Pipeline headroom is shown separately from provider balance.
* Validated case analysis and tenant-isolated patient CRUD.

## Versions and changed files

No packages added or upgraded. Verified installed versions:
Next.js 16.4.3; React/React DOM 19.3.0; TypeScript 5.9.3; Tailwind 4.3.3;
@supabase/ssr 0.12.7; @supabase/supabase-js 2.118.0;
@tanstack/react-query 5.105.0; graphql-request 7.4.0; GraphQL 16.14.2;
React Hook Form 7.91.0; @hookform/resolvers 6.0.2; Zod 4.6.7;
Lucide React 1.65.0; Vitest 5.0.5; ESLint 9.39.5.

New frontend sources: `components/app-shell.tsx`, `components/ui.tsx`;
`features/workspace/{api,types,fixtures,dashboard,books,ingestion,chunks,search,workspace-page,index}`;
`features/auth/{login-form,index}`; `features/case-workspace/{case-workspace,index}`;
`app/login/page.tsx`; `app/workspace/layout.tsx`, `app/workspace/[section]/page.tsx`;
`app/preview/layout.tsx`, `app/preview/[section]/page.tsx`;
`app/api/backend/[...path]/route.ts`, `app/api/auth/logout/route.ts`;
`app/error.tsx`, `app/not-found.tsx`; auth and workspace tests.

Updated frontend sources: root page/layout/providers/globals.css; src/proxy.ts;
lib/api.ts, lib/graphql/client.ts, lib/supabase/server.ts;
hooks/use-backend-health.ts; .env.example and README.

Backend: new app/api/auth.py, app/api/routes/monitor.py and
tests/test_monitor_api.py; updated app/main.py, app/api/routes/knowledge.py and
app/ai/ingestion/service.py. No chunking/embedding algorithm, schema or ledger
change. Root .gitignore ignores generated Playwright diagnostics.

## Verification

Executed successfully:

* 18 frontend tests (fixture dashboard/chunks/progress/search, explicit API
  confirmation, errors/quota stop, upload validation, login states and origin/role
  boundaries); TypeScript; ESLint without errors/warnings; production build.
* 67 backend tests, including new operator access, user_metadata rejection,
  unavailable reports, filtering/pagination validation and read-only artifact
  behavior; Ruff passed. Pytest's default system temporary directory was denied
  by Windows; the successful run used a repository-local `--basetemp`.
* Browser: nine desktop pages, mobile navigation and narrow layouts, invalid PDF
  selection, chunk filtering, fixture retrieval and theme toggle.
* Local production server (`next start`, port 3001): all nine preview pages returned HTTP 200; no browser errors or horizontal overflow, and protected navigation redirected to login.
* Protected live route redirected to `/login`; missing frontend auth config
  returned 503; unauthenticated FastAPI monitor returned 401; backend health
  through the Next.js proxy returned backend=ok.
* Real local artifact check: 8 PDFs, 7 selected books, 2,676 saved vectors,
  637,443 provider tokens; sampled five actual frozen chunks; SQLite checksum
  unchanged before/after. This was not a live authenticated database API test.

Not executed against production: real account login/logout, authenticated upload,
live retrieval or paid ingestion. Public auth configuration/operator credentials
are unavailable, and provider quota verification remains required. No tests use
real patient data. Fixture success is not reported as production connectivity.

The existing Vitest configuration emits a future Vite native-loader advisory;
tests pass. Generated screenshots are ignored artifacts in reports/ingestion:
phase3-dashboard-desktop.png and phase3-dashboard-mobile.png. Machine-readable verification is in reports/ingestion/phase3-verification.json.

## Run on Windows

From `E:\github\Similia AI\backend`:

```powershell
uv run --offline --no-sync python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

From `E:\github\Similia AI\frontend`:

```powershell
npm run dev -- --hostname 127.0.0.1
```

Open http://127.0.0.1:3000/preview/dashboard for the synthetic interface or
http://127.0.0.1:3000/login for live sign-in after configuring public credentials.
For a local production run use `npm run build`, then `npm start`.

Documentation consulted: installed Next.js 16.4.3 guides and Context7 official
Next.js, Supabase SSR and TanStack Query references. The Supabase changelog
markdown fetch was unsupported by the browsing tool; implementation used the
current SSR documentation. Historical homeopathic retrieval is not evidence of
clinical efficacy.
