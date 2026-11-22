# Phase 5 report: production readiness

Date: 2026-11-24. No deployment, no network install, no live provider call. The provider stop is still set.

## Built and tested (mocks, local)
- **Start-up checks:** in production the API refuses to start on a missing Supabase setting, a missing or invalid encryption key, `CORS_ORIGINS` of `*` or plain http, or a missing search key. Messages name the setting, never the value. Development only warns.
- **Readiness:** new `/ready` (configuration and database; 503 with one-word reasons, no details). `/health` stays the liveness check.
- **Logging:** one safe line per request (id, method, path with record ids replaced, status, time). No query string, headers, bodies or user. `X-Request-ID` returned. The container runs uvicorn with its own access log off because it records query strings.
- **AI budgets:** per-doctor daily and monthly ceilings next to the hourly ones (defaults 150 questions and 40 analyses per day, 600 analyses per month; 0 turns one off), counted from the audit log, with a wait time in the message.
- **Key rotation:** the vault accepts `APP_ENCRYPTION_KEY_PREVIOUS`, and `backend/scripts/rotate_encryption_key.py` re-encrypts doctors' keys (dry run by default, prints counts only).
- **Content-Security-Policy:** same-site scripts, styles, images and fonts; connections only to this site and the Supabase project; no framing, plugins or foreign form targets.
- **CI:** `.github/workflows/ci.yml` runs backend lint and tests and frontend lint, type check, tests and production build on every push. **Dockerfiles** for the API and the web app, with `.dockerignore` files.
- **Docs:** `docs/production-runbook.md` (settings, deploy order, health, backups and a restore drill, key rotation, known risks); `.env.example` updated.
- Tests: backend 205 pass, `ruff` clean (22 new for readiness, rotation, budgets). Frontend: 167 tests pass, ESLint and TypeScript clean, `next build` succeeds. A temporary production server (my own port, since stopped) sent the CSP, frame, and HSTS headers, and the sign-in page rendered with no CSP errors in the browser pane. Signed-in screens were not checked under the CSP.

## Not verified
CI workflow and Dockerfiles have never been run (no Docker or GitHub run here). CSP was checked only as far as the build and headers listed below, not in a browser. No load or failure testing.

## Needs your decision or approval
1. **Provider stop moved to the database** (done in code, 212 backend tests pass). Apply `supabase/migrations/20261124120000_system_flags.sql` (project `ivlmduwdkwgrxqxjjuyg` only). It starts paused, so nothing is cleared; clear it yourself in the SQL editor only after checking the provider account. A provider 429 in a website job now sets it automatically.
2. Declare `cryptography` and `tokenizers` in `pyproject.toml` and run `uv lock` (network).
3. Hosting choice, domain, https and backup settings in Supabase (yours to set).
4. First git commit and pushing to GitHub so CI can run.
5. Legal review (consent wording, retention) and an independent security review before real patients.

## Remaining beyond Phase 5
Urdu for the remaining screens, patient portal, scheduled auto-erasure, real-browser end-to-end tests, live ingestion test (needs your approval and a token cap).
