# Production runbook

Nothing here has been run against a real server or real Docker. Treat every step as untested until you do it once in a staging copy.

## 1. Settings (environment variables, never in the image)
Backend: `ENVIRONMENT=production`, `SUPABASE_URL`, `SUPABASE_PUBLISHABLE_KEY`, `SUPABASE_SECRET_KEY`, `APP_ENCRYPTION_KEY`, `CORS_ORIGINS` (https only, the real site), `VOYAGE_API_KEY`, `VOYAGE_MODEL`. Optional limits: `AI_QUESTIONS_PER_HOUR/DAY`, `AI_ANALYSES_PER_HOUR/DAY/MONTH` (0 turns a window off), `EMBEDDING_BUDGET_TOKENS`, `MAX_RUN_EMBEDDING_TOKENS`, `RAG_MIN_SIMILARITY`.
Frontend (build time, public): `NEXT_PUBLIC_SUPABASE_URL`, `NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY`. Frontend (run time, server only): `API_BASE_URL` (the API address).
In production the API **refuses to start** if a required setting is missing, the encryption key is invalid, `CORS_ORIGINS` is `*` or plain http. The message names the setting, never its value.

## 2. Deploy order
1. Back up the database (section 4). 2. Apply any new migration (`supabase/migrations`, in file-name order) in the SQL editor of project `ivlmduwdkwgrxqxjjuyg`. 3. Deploy the API, wait for `/ready` = 200. 4. Deploy the web app. 5. Sign in and open one patient.
Images: `docker build -t similia-api backend`; `docker build -t similia-web --build-arg NEXT_PUBLIC_SUPABASE_URL=... --build-arg NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY=... frontend`. The API container runs as a normal user with uvicorn's access log off (it would record query strings).

## 3. Health and logs
- `/health`: process is alive (no outside calls). `/ready`: configuration sound and database answers (503 otherwise, with a one-word reason per part). Point the load balancer at `/ready`, the container health check uses `/health`.
- Log line per request: `id METHOD path status ms`. No query string, no headers, no bodies, no user, record ids replaced by `{id}`. The id is also sent back as `X-Request-ID`; ask users to quote it.
- Never turn on request-body logging, LangSmith tracing or a proxy that logs bodies for the patient endpoints: they carry health information.

## 4. Backups and recovery
- Use Supabase's automatic backups; turn on point-in-time recovery if your plan allows. Backups hold patient data: keep them in the same region and access rules as the database.
- Per patient: the doctor can download a JSON record (Patients, patient page, "Download patient record"). This is not a backup of the system.
- Restore drill (do once per quarter, in a separate project, never over production): restore the latest backup, point a staging API at it, check `/ready`, open a known patient, count rows in `patients`, `cases`, `case_analyses`, `knowledge_chunks`.
- Embeddings are rebuilt from stored text with the ingestion screen (paid): after a restore, check each book's "fully searchable" flag.
- Erasure and backups: erased patients stay in older backups until they expire. Say so in your privacy notice.

## 5. Key rotation
Doctor AI keys are encrypted with `APP_ENCRYPTION_KEY`.
1. Generate a new key (Fernet). 2. Set `APP_ENCRYPTION_KEY_PREVIOUS` = the old key, `APP_ENCRYPTION_KEY` = the new key; restart (both keys now work). 3. `uv run python scripts/rotate_encryption_key.py` (dry run: counts only), then `--apply`. 4. Remove `APP_ENCRYPTION_KEY_PREVIOUS`, restart. Nothing prints a key or a user id.
Other secrets (Supabase secret key, Voyage key): create the new one in the provider, change the environment variable, restart, then revoke the old one. `mongodb.txt` in the project folder must be rotated and deleted by you.

## 6. Limits that protect cost
Per doctor, counted from the audit log (survives restarts): hourly, daily and monthly ceilings (section 1). Embedding: per-job and total token limits enforced by the server, confirmation before every start, provider stop respected (database flag, set automatically after a provider 429, plus the old command-line manifest file).

## 7. Known production risks (not fixed)
1. **Provider stop** now lives in the database (`system_flags`, migration `20261124120000_system_flags.sql`, starts PAUSED to match today's state). Until that migration is applied the API cannot read the flag and holds all embedding (safe). Only you can clear it, in the SQL editor (the statement is in the migration file) after checking the provider account.
2. `uv.lock` does not list `cryptography` and `tokenizers` as direct dependencies of `pyproject.toml` (they arrive through other packages). Declare them and run `uv lock` (needs network access, your approval).
3. Rate counters use the audit log, so two simultaneous requests can both pass by one. Acceptable for cost control, not for security.
4. Content-Security-Policy keeps `'unsafe-inline'` for scripts (needed by Next.js hydration without a nonce setup). It still blocks other sites' scripts, framing and plugins.
5. Earlier migrations are not written to be re-run; run each once. Check `supabase migration list` or the SQL editor history first.
6. Load and failure testing was not done.
