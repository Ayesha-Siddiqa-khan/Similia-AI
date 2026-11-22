# Phase 3 report: PDF upload, embedding controls, RAG reliability

Date: 2026-11-23. No paid or live provider call was made. The provider stop is still set. `.env`, `mongodb.txt` and any key were not opened.

## 1. What was inspected
- Website upload path versus the command-line pipeline (`python -m app.ai.ingestion`): two separate systems with different state (raw text in the database versus a frozen plan and a local ledger).
- `ingestion_jobs` states, resume model (a chunk with a NULL embedding is the resume point), duplicate protection (unique book hash, unique `(book_id, chunk_index)`, one active job per book).
- Search and case-analysis retrieval (`app/ai/rag`), page metadata, partly indexed books.
- Provider endpoint choice (by key prefix: `al-` goes to `ai.mongodb.com`, otherwise `api.voyageai.com`). Keys were never read or printed.

## 2. Defects confirmed
1. Website Start/Pause/Resume/Retry did not exist; the ingestion screen showed numbers from local report files, not the database.
2. Nothing asked for confirmation before spending tokens; the limit was a single per-run number with no total budget.
3. A failed database update after a paid batch would have left the chunk empty, so the next pass would send (and pay for) the same batch again, forever.
4. The embedding call replaced `token_count` in the database with the provider's value, so estimates drifted.
5. Provider HTTP 429 was recorded without details, and implied a cause the response did not state.
6. A crashed or restarted job stayed "running" for ever and blocked the book.
7. Search returned passages from partly indexed books with no warning and no PDF page numbers; analysis passages had no author, section path or page.
8. Found while testing (fixed): the provider-error event collided on a `message` argument, which turned every provider failure into a generic "error" and lost its details. The default job limit equalled the estimate, so the safety margin always stopped the last batch.

## 3. What was fixed
- One database-based engine (`IngestionService`): register (validate, hash, extract), prepare (free chunking with PDF page numbers), confirmed start, run, pause, resume, recover.
- Start needs `confirmed: true`. The server enforces: per-job token limit (the smaller of the configured limit, the requested limit and the remaining total budget), a total budget across jobs, token-based batches, a requests-per-minute pace, and a stop before sending when the next batch would pass the limit (with a 25% margin).
- Pause finishes the current batch, then stops. Resume starts a new job linked to the old one and sends only chunks with no vector, so nothing is duplicated.
- A missed database update stops the job instead of looping. `token_count` is passed back so it is kept.
- Provider failures are recorded as events with HTTP status, `Retry-After`, error class and a redacted message. A 429 says "nothing was billed for this batch" and names no cause.
- Jobs without a heartbeat for 5 minutes are marked "interrupted" and can be resumed.
- Command-line books are refused by the website engine (no mixing of the two systems). Duplicate uploads are rejected.
- Search and analysis passages now carry PDF page range, author, section path and a "book fully indexed" flag; results from partly indexed books raise a visible notice. Weak matches below `RAG_MIN_SIMILARITY` (default 0.25) are dropped and the answer becomes "insufficient sources". Pages are shown only when the source recorded them.
- Screens: upload form with metadata, real progress from the database, Start/Pause/Resume/Retry, confirmation dialog (estimated tokens, provider and host, limit, remaining budget), history and errors, chunk and page text inspector.

## 4. Files changed
Backend: `app/ai/ingestion/{service,chunking}.py`, `app/ai/rag/{coverage,case_analysis}.py`, `app/api/routes/{knowledge,cases}.py`, `app/core/config.py`, `app/schemas/{ingestion,knowledge,cases}.py`, `app/services/knowledge_db.py`.
Backend tests: `tests/{conftest,test_ingestion_service,test_ingestion_api,test_case_analysis,test_cases_api}.py`.
Frontend: `src/features/ingestion/*` (new), `src/features/workspace/{books,search,workspace-page}.tsx`, `src/features/cases/analysis-view.tsx`, `src/app/api/backend/[...path]/route.ts` and tests; `features/workspace/ingestion.tsx` deleted.
Database (not applied): `supabase/migrations/20261123120000_ingestion_controls.sql`. Docs: `docs/ingestion-api.md`, this file.

## 5. Tests
- Backend: 180 passed, `ruff` clean.
- Frontend: 144 passed (13 files), ESLint clean, TypeScript clean.
- Covered: no start without confirmation; prepare is free and repeatable; limits (per job, total budget, requested limit); pause then resume with each chunk sent exactly once; resume after failure; pacing; provider stop mid-run; 429 recording with key redaction; stale-job recovery; one active job per book; duplicate uploads; fake binary files; authentication on every endpoint; partial-index flags with pages.

## 6. Mocked versus real
All of the above used a mock embedding provider and an in-memory database. **Not verified live:** the new migration, a real PDF through the real extractor, real embeddings, real search ranking, behaviour under real provider limits.

## 7. Provider and Atlas status
The provider stop (`stopped_provider_http_429`) is still set. The code cannot say whether the 429 was a per-minute limit or an exhausted free allowance; a per-minute limit does not mean free allowance remains. The dashboard of the account that owns the key must be checked by you. Defaults are conservative (3,000 tokens per batch, 3 requests per minute, 500,000 tokens total, 200,000 per job).

## 8. Needs your approval or action
1. Run these two migrations, in this order, in your Supabase SQL editor (project `ivlmduwdkwgrxqxjjuyg` only): `20261123100000_lock_patient_tables.sql`, then `20261123120000_ingestion_controls.sql`. Restart the backend afterwards.
2. Check the Voyage/Atlas account (allowance, limits, billing). Tell me when to clear the provider stop; I will not clear it or resume paid ingestion on my own.
3. After that, a small live test with a hard cap (for example 2,000 tokens) on one short book, with your explicit go-ahead.
4. Rotate the key in `mongodb.txt` (it is a plain-text file in the project folder; it is now ignored by git).
5. Decide where original PDFs should be stored if you want to keep the files themselves (today only the extracted text is stored).

## 9. Remaining
Phase 4 (clinical workflows) and Phase 5 (production readiness), as listed in `docs/audit-and-plan.md`. The only matches for "synthetic" in the frontend source are test fixtures and test strings; no screen shows sample data.
