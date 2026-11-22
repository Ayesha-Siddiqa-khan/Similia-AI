# Similia AI: audit, plan and Phase 2 report

Written 2026-11-23. Honest status of the whole application: what was inspected, what is confirmed broken,
what was fixed, what is still incomplete, and what needs the owner's approval.

**How to read the labels**

- **VERIFIED** = I read the code or ran it myself and saw the result.
- **AGENT-REPORTED** = found by a read-only audit agent; the evidence is plausible and cited, but I did not
  re-check it myself. Treat as likely, confirm before relying on it.
- **ASSUMED** = cannot be known without a live system (database, provider account, deployment).

## 1. What was inspected

- Frontend (`frontend/src`): every page, the proxy route, case workspace, AI settings, login.
- Backend (`backend/app`): routes, auth, case store, AI analysis, vault, limits, ingestion service, CLI ingestion, RAG retrieval, monitor.
- Database: all 7 migrations in `supabase/migrations` (read; **not** run against a database).
- Security and deployment files: `.gitignore`, `next.config.ts`, dependency files, docs.
- Automated baseline before any change: backend 120 tests, frontend 78 tests, lint and typecheck clean (VERIFIED).

## 2. Current test status (after Phase 2)

| Check | Before | After |
|---|---|---|
| Backend tests (pytest) | 120 pass | **135 pass** |
| Backend lint (ruff) | clean | clean |
| Frontend tests (vitest) | 78 pass | **108 pass** |
| Frontend lint (eslint) | clean | clean |
| Frontend typecheck (tsc, source and tests) | clean | clean (see note) |

Note: `npm run typecheck` also reads generated files in `frontend/.next`. They go stale when routes are deleted
(this happened with `/preview`) and then report false errors until the dev server regenerates them. A typecheck
with those files excluded is clean.

**All of the above are simulated tests** (fake database, fake AI, fake embeddings). No real Supabase, Anthropic or
Voyage request was made by any test or by me. See section 8 for exactly what was verified live.

## 3. Findings

### Fixed in Phase 2

| ID | Severity | Finding | Status |
|---|---|---|---|
| F1 | High | Autosave could run two saves at once, so an older save could overwrite a newer one (VERIFIED in code). | Fixed: one save at a time, always the newest draft (`use-autosave.ts`). |
| F2 | High | A failed save was not retried until the next keystroke; leaving the page or closing the tab lost the last edits; no warning (VERIFIED). | Fixed: automatic retry with back-off and on reconnect, flush on leaving the screen, browser warning when work is unsaved. |
| F3 | High | An entry with notes but an empty title was silently dropped on save while the screen said "All changes saved" (VERIFIED). | Fixed: kept with a fallback title (`case-draft.ts`). |
| F4 | High | A signed-off case could still be edited, re-analysed or signed again (VERIFIED in my own code). | Fixed: locked (HTTP 409), explicit audited "Reopen case", sign-off needs a current analysis. |
| F5 | High | After editing an analysed case the old analysis could still be signed off (VERIFIED). | Fixed: any real edit makes the analysis stale; a new analysis is required. |
| F6 | High | The web ingestion loop ignored how many rows the database updated, so one missed update would re-send and re-bill the same batch forever (VERIFIED in code). | Fixed: stops with a clear error. |
| F7 | High | Web ingestion had no backend spend limit and ignored the provider pause (VERIFIED). | Fixed: per-job token ceiling (`MAX_RUN_EMBEDDING_TOKENS`) and the pause flag now apply to `/ingest`. |
| F8 | Medium | Web embedding wiped every chunk's `token_count` to NULL (VERIFIED: query omitted it, SQL overwrote it). | Fixed. |
| F9 | Medium | Validation errors (HTTP 422) echoed the rejected text back, which for case notes is patient information (VERIFIED in test output). | Fixed: only field name and rule are returned. |
| F10 | Medium | `/docs`, `/redoc`, `/openapi.json` were public (VERIFIED: served). | Fixed: off when `ENVIRONMENT=production`. |
| F11 | Medium | No browser security headers; `X-Powered-By` shown (VERIFIED). | Fixed and checked live: nosniff, frame deny, referrer policy, permissions policy (microphone allowed for the site only); HSTS in production builds. |
| F12 | Medium | Credential-bearing `mongodb.txt` (the audit agent says it holds a password and key; I did not open it) exists in the project root and was not git-ignored (VERIFIED exists and not ignored). | Ignore rule added. **Not rotated or deleted: needs you, see section 6.** |
| F13 | Medium | Renamed non-PDF or binary files reached the PDF parser; a duplicate-upload race returned HTTP 500 (VERIFIED in code). | Fixed: header check, binary-text check, race returns 409. |
| F14 | Medium | Unanswered "Q: ... A:" cards were sent to the AI as findings and counted as recorded entries (VERIFIED). | Fixed. |
| F15 | Low | Duplicate AI questions could be added again, and a deleted card never re-enabled its question (VERIFIED). | Fixed. |
| F16 | Low | No guard for the backend's 80-entry limit; the failure said "boxes too long"; patient Contact/Notes over the limit failed silently (AGENT-REPORTED, then fixed and tested). | Fixed. |
| F17 | Low | Proxy replaced every 409/422 with a generic message that hid the real reason. | Fixed: backend's own safe explanation is shown. |
| F18 | Required | **All synthetic and demo data removed from the app** (owner request): `/preview` pages, sample patient/case/analysis/books, the sign-in "Open synthetic preview" link, "Synthetic" / "Phase 3" labels (VERIFIED by search: none left in application code). | Done. Test-only samples live in `frontend/src/test/fixtures/` and are never imported by the app. |

### Found, not fixed yet (planned)

| ID | Severity | Finding | Evidence | Plan |
|---|---|---|---|---|
| P1 | High | Patient tables allow any signed-in Supabase user to read and write their own rows directly with the public key, skipping role, consent and audit rules. | Policy text VERIFIED; the default Supabase grants that make it exploitable are ASSUMED. | Migration written: `20261123100000_lock_patient_tables.sql`. **Needs your approval to apply.** |
| P2 | High | The website cannot ingest books: `/books/{id}/ingest` is not exposed; Start, Pause, Resume and Retry buttons are permanently disabled. | VERIFIED (proxy allow-list and `ingestion.tsx`). | Phase 3. |
| P3 | High | Two ingestion systems that cannot share books: the website path (raw text in the database, no budget) and the command-line pipeline (frozen plan, token ledger). A book uploaded on the web is refused by the CLI and vice versa. | AGENT-REPORTED, detailed. | Phase 3: one engine. |
| P4 | High | Search and case analysis query books that are only partly embedded, with no warning and no relevance threshold, so weak matches look grounded. | AGENT-REPORTED; thin coverage in `docs/live-readiness-phase31.md`. | Phase 3: completeness flags, threshold, "insufficient evidence" path. |
| P5 | High (compliance) | No way to delete, export or anonymise a patient, case or analysis; consent can never be withdrawn; deleting a user cascades and erases their audit log. | VERIFIED: there is no DELETE endpoint (I wrote the routes); cascade AGENT-REPORTED. | Phase 4, after a decision on retention rules. |
| P6 | Medium | Citations have no page numbers for web-ingested books; CLI page numbers are physical PDF pages, not printed page numbers. Analysis passages omit page and section path. | AGENT-REPORTED. | Phase 3. |
| P7 | Medium | A crashed web ingestion job stays "running" and blocks that book forever; no recovery. | AGENT-REPORTED. | Phase 3. |
| P8 | Medium | The CLI treats any 429 whose message mentions billing/credit as "quota exhausted" and pauses; Retry-After and error bodies are not saved. | AGENT-REPORTED. | Phase 3. |
| P9 | Medium | Dashboard, Books, Ingestion and Chunks numbers come from local report files, not the database; a hosted backend would show nothing or stale figures. | AGENT-REPORTED. | Phase 3. |
| P10 | Medium | Audit log does not record reads, patient/case edits or symptom saves, and also serves as the rate-limit counter (racy). | AGENT-REPORTED. | Phase 4/5. |
| P11 | Medium | No content-security-policy, no rate limit except the hourly AI limit, no daily or monthly budget. | VERIFIED (limits); AGENT-REPORTED (CSP). | Phase 5. |
| P12 | Medium | A single encryption key with no rotation: losing `APP_ENCRYPTION_KEY` loses every saved doctor key. | VERIFIED (`vault.py`). | Phase 5 (multi-key rotation + backup guidance). |
| P13 | Medium | `cryptography`, `anthropic`, `tokenizers` are imported but not declared in `pyproject.toml`; `pyjwt` is declared but unused. | AGENT-REPORTED; undeclared `cryptography` VERIFIED earlier. | Needs `uv lock` (network): **approval needed**. |
| P14 | Medium | No CI, Dockerfile, production run command, logging config, readiness check or backup/recovery guide; migrations are not re-runnable. | AGENT-REPORTED. | Phase 5. |
| P15 | Low | Patient edit/archive and case language have no screen; mobile sidebar items stay keyboard-focusable; some very small fonts; large parts of the app (results, review form, patients, AI settings) have no Urdu. | AGENT-REPORTED. | Phase 4/5. |
| P16 | Low | No git commit exists (nothing is backed up in version control); the repo holds a 70 MB copyrighted-PDF folder and a 10 MB font. | VERIFIED. | Your decision when to make the first commit. |

## 4. What works (evidence in brackets)

- Practitioner and operator roles, owner-scoped patient and case records, consent check before AI (backend tests, simulated).
- Case taking: six steps, English and optional Urdu, AI follow-up questions, cards, mic dictation, autosave (unit and component tests; **never exercised in a real browser session by me**).
- Per-doctor AI keys: encrypted storage, verify, expiry (1 day/week/month), hourly limits, isolation (backend tests, simulated; the owner saved a key successfully in the real app on 2026-11-22).
- Deterministic emergency check and citation guard in analysis (tests, simulated).

## 5. What is still incomplete (do not assume it works)

- Uploading a real PDF, embedding it and searching it end to end: **not verified with real services**.
- The Ingestion Jobs controls: disabled by design until Phase 3.
- AI analysis on real material: blocked by the Voyage pause and thin book coverage (P4).
- Real Supabase row-level-security behaviour: not tested against the live database.
- Browser-driven end-to-end tests: none run yet (need a signed-in session).

## 6. Actions that need your approval or your hands

1. **`mongodb.txt` (F12):** if it really contains a password or key, rotate those credentials, then delete the file yourself. I did not read or delete it.
2. **Apply** `supabase/migrations/20261123100000_lock_patient_tables.sql` (P1). It only removes privileges; no data is deleted.
3. **Provider pause:** I have not cleared the Voyage/Atlas pause and will not without your explicit go-ahead.
4. **`uv lock`** to declare missing Python dependencies (needs network access).
5. **Test data:** if the earlier test patient and cases should not stay in your database, tell me and I will give you the SQL; deleting is destructive, so you run it.
6. **Retention policy** for patient records (how long, who may erase) before I build deletion/erasure (P5).
7. **First git commit:** when you want one, and whether the PDF folder and fonts should be excluded (they are now ignored).
8. **Stray process:** an older frontend process (PID 1644 at the time) still held port 3000 and did not answer. End it in Task Manager, then start `npm run dev` fresh.

## 7. Plan for the remaining phases

**Phase 3: PDF and RAG** (largest piece)
1. One ingestion engine, based on the CLI's frozen-plan and ledger design; store the uploaded PDF (storage location needs your decision) so the same pipeline and resume rules apply.
2. Real controls: Start, Pause, Resume, Retry failed batches, progress from the database, errors and history, confirmation dialog showing estimated tokens, provider and limit; backend-enforced limit and the provider pause.
3. Reconciliation for interrupted requests; recovery after restart or network failure; stale-job recovery.
4. Search: completeness flag per book, relevance threshold, honest "insufficient evidence", citations with page numbers and the distinction between source text and AI interpretation.
5. Fix the 429 classification and save sanitized provider error details (never keys).
6. Tests with a fake provider; a **live test only after your approval** and with a hard token cap.

**Phase 4: Clinical workflows**
Patient edit/archive/consent withdrawal screens, case history and previous analyses, minors and urgent-symptom safeguards, source-versus-interpretation display, erasure/export once retention is decided, wider audit coverage, Urdu for the remaining screens.

**Phase 5: Production readiness**
CI that runs all tests, Dockerfile and production run guide, startup configuration checks, structured logging, readiness check, backup and recovery guide, content-security-policy, idempotent migrations, key rotation, daily and monthly AI budgets, dependency declarations, load and failure testing.

## 8. Simulated versus live verification

Live (real HTTP against a running server, 2026-11-23): security headers present; `X-Powered-By` hidden; `/preview/*` returns 404;
`/workspace` redirects to sign-in; the sign-in page contains no demo wording.

Everything else in section 2 is simulated. Not yet verified live: database migrations, RLS and the new lock-down, real PDF
upload, embeddings, search, AI analysis, a signed-in browser session, deployment.

## 9. Files changed in Phase 2

**Frontend, new:** `features/cases/{use-autosave.ts, use-autosave.test.ts, case-draft.ts, case-draft.test.ts}`, `app/api/backend/route.test.ts`, `test/fixtures/{cases,workspace}-fixtures.ts`.
**Frontend, changed:** `features/cases/{case-page, patients, api, paths, analysis-view, ai-settings, suggested-questions, symptom-editor, types}`, `features/workspace/*` (preview removed), `features/auth/login-form(.test)`, `components/app-shell.tsx`, `app/api/backend/[...path]/route.ts`, `next.config.ts`, `app/globals.css`.
**Frontend, deleted:** `app/preview/**` (a backup copy was kept outside the project), the two fixture files from `src/features`.
**Backend, changed:** `ai/ingestion/{service,extraction}.py`, `api/routes/{knowledge,cases}.py`, `main.py`, `ai/rag/case_analysis.py`, `services/knowledge_db.py`.
**Backend tests:** `conftest.py`, `test_ingestion_service.py`, new `test_case_integrity.py`.
**Database and config (not applied):** `supabase/migrations/20261123100000_lock_patient_tables.sql`; `.gitignore`.
**Docs:** this file; `case-taking-setup.md`; note added to `frontend-phase3.md`.
