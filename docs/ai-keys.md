# Bring-your-own AI key (each doctor uses their own Anthropic key)

AI follow-up questions and case analysis run on **the signed-in doctor's own key and
account**. There is no shared server AI key. A doctor with no key sees "Add your own AI key"
and a link to **AI Settings**.

What still uses the app's own services: searching the book library (Voyage embeddings) and
the database (Supabase). Only the AI model calls use the doctor's key.

## One-time administrator setup

### 1. Create the encryption secret (the "vault key")

It encrypts every doctor's API key before it is stored. It is never kept in the database.
Run from the project folder (no download, uses the backend's existing environment):

```powershell
cd "E:\github\Similia AI\backend"; .\.venv\Scripts\python.exe -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Copy the printed line and add it to `backend/.env` yourself:

```
APP_ENCRYPTION_KEY=<the printed value>
```

Keep a private backup of it (password manager). **If it is lost, every saved doctor key becomes
unreadable and doctors must enter their keys again.** Never commit it or paste it in chat.

### 2. Create the table (Supabase dashboard, SQL Editor)

Run these two files **in this order**, each in a new query (copy the file, paste, Run):

1. `supabase/migrations/20261122140000_user_ai_settings.sql` (the table)
2. `supabase/migrations/20261122150000_ai_key_active_until.sql` (the active period column)

Check with:

```sql
select tablename, rowsecurity from pg_tables where tablename = 'user_ai_settings';
select column_name from information_schema.columns
where table_name = 'user_ai_settings' and column_name = 'active_until';
```

Expect `rowsecurity = true` and one `active_until` row. The table has no policies, so browsers
can never read it. Only the backend can.

If the first file says "already exists", skip it and run only the second.

### 3. Restart the backend

```powershell
cd "E:\github\Similia AI\backend"; uv run uvicorn app.main:app --reload
```

Then restart the frontend (`npm run dev`).

`ANTHROPIC_API_KEY` / `ANTHROPIC_MODEL` in `backend/.env` are no longer used by the doctor
workspace. They can stay empty.

## What each doctor does

1. Sign in, open **AI Settings** in the sidebar.
2. Create a key at console.anthropic.com (API Keys, Create key) and set a monthly spend limit.
3. Paste it, choose a model and **how long to keep the key active** (1 day by default, 1 week
   or 1 month), then click **Save and verify**.
4. The app checks the key with Anthropic (a free request), stores it encrypted, and shows
   only the last four characters from then on.
5. Back in a case: **Suggest questions** and **Run analysis** now work.

Doctors can change the model without re-entering the key, replace the key, or remove it.

### Active period

- A key works only until its **active until** time. By default that is 1 day after saving.
- After that the key stays saved (encrypted) but is **paused**: AI features show "Your AI key
  is paused" with a link to AI Settings.
- To continue, open **AI Settings** and click **Turn on** (choose 1 day, 1 week or 1 month).
  The key is not pasted again.
- **Pause now** turns the key off immediately. **Restart timer** starts the chosen period over.

### Hourly limits

Each doctor is limited per hour (rolling 60 minutes) so a loop or stuck page cannot run up
their bill. Defaults: 30 question requests and 10 case analyses per hour. When the limit is
reached the app says how many minutes to wait. Change the limits in `backend/.env`:

```
AI_QUESTIONS_PER_HOUR=30
AI_ANALYSES_PER_HOUR=10
```

Requests are counted before the AI call, so failed attempts also count. Usage is shown in
AI Settings under "Your usage this hour".

## Security notes

- Keys are encrypted with `APP_ENCRYPTION_KEY` (Fernet) and never returned by any endpoint.
- The browser never receives a stored key; the API only reports `key_last4`.
- Keys are never written to logs or the audit log (audit rows record only "key saved/removed").
- Each doctor can use only their own key; another doctor's account cannot read or use it.
- Anyone with a doctor's key can spend that doctor's money. Tell doctors to use a dedicated
  key with a spend limit, and to remove it here and in the Anthropic console if it leaks.
- Case text is sent to Anthropic under the doctor's account terms. Only analyse patients who
  have consented.

## Known follow-ups

- `cryptography` is installed (via another package) but not declared in
  `backend/pyproject.toml`. Declaring it needs `uv lock`, which needs network access and your
  approval.
- Limits are per doctor and per hour only. There is no daily or monthly cap and no way for an
  administrator to set different limits for one doctor.
- Two requests sent at the same instant can both pass the limit check, so a doctor may briefly
  exceed the limit by a small amount.
