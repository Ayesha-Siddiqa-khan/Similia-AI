# AGENTS.md — Central Rules for All AI Coding Agents

> **Single source of truth.** Every AI coding agent working in this repository
> (Antigravity, Cursor, Grok, Codex, OpenCode, Claude Code, and others) MUST
> follow these rules. Tool-specific config files only **point here** — they never
> duplicate or override these rules. The user's explicit chat instructions
> always take precedence over these rules.

## 1. Project boundary (STRICT)

- Work **only** inside this repository root. The project root is the directory
  containing this file.
- Never read, write, execute, move, or reference files outside this folder
  without the user's explicit permission — including `~`, `$HOME`, other drives,
  and parent directories.
- Never use paths, environment tricks, or shell commands to reach outside the
  project.

## 2. Privacy & security (STRICT)

- **No internet access.** No network requests, external APIs, web fetches, web
  searches, telemetry, analytics, or crash reporting without the user's explicit
  approval.
- **No dependency downloads.** No `npm install`, `pip install`, `git clone`, or
  any package/tool download without the user's explicit approval.
- **No data transmission.** Never upload, transmit, or share any file, snippet,
  or metadata from this machine.
- Never read or expose secrets (`.env`, keys, tokens). Never commit secrets.

## 3. Fail-safe behaviour

- If an action violates these rules — **or you are unsure whether it does** —
  **STOP immediately** and ask the user for approval. Do not proceed on
  assumption.
- Hooks and permission systems are a safety net, not the source of truth. If
  they are unavailable, misconfigured, or fail, **these rules still apply** and
  unsafe operations must still be blocked or escalated to the user.

## 4. Language

- **Always respond in English.**

## 5. Documentation & libraries

- For questions about any library, framework, SDK, or API, use **Context7**
  (`resolve-library-id` → `query-docs`) to fetch current documentation instead
  of guessing or relying on stale training data.

## 6. Development guidelines

- Minimal, focused changes. No unrequested abstractions, dependencies, or
  boilerplate. Boring over clever. Deletion over addition.
- Reuse existing helpers and patterns before writing new code.
- Fix root causes, not symptoms.
- Non-trivial logic must leave one runnable check behind (a small test or
  assert-based self-check).
- Do not commit generated output, build artifacts, or secrets.

## 7. Project structure (monorepo, feature-based frontend)

```text
frontend/                # Next.js (App Router, TypeScript, Tailwind)
  src/
    app/                 # Routes, layout, providers, API routes
    components/          # Shared UI components
    features/            # One folder per feature: src/features/<feature-name>/
      <feature-name>/    #   components/, logic/, services/, types.ts,
                         #   index.ts = public API (only import surface)
    hooks/               # Shared React hooks
    lib/                 # Client utilities (supabase/, graphql/, api, health)
    types/               # Shared TypeScript types
backend/                 # FastAPI + Python 3.12 (uv-managed)
  app/
    api/routes/          # REST endpoints (health now; uploads/AI later)
    core/                # Centralised pydantic-settings configuration
    services/            # Supabase, LLM, embeddings, vector store, RAG
    graphql/             # Strawberry schema
    ai/                  # Phase 2+ pipeline: llm/, embeddings/, rag/,
                         # graphs/ (LangGraph), ingestion/, evaluation/
    models/              # Domain/DB models (Phase 2)
    schemas/             # Pydantic request/response schemas
  tests/                 # Pytest suite
supabase/migrations/     # Future DB migrations (Phase 2)
docs/                    # Project documentation
```

Frontend rules:

- A feature owns its code. Other features import **only** via the feature's
  `index.ts` public API — never deep-import into another feature's internals.
- Code used by exactly one feature lives in that feature, not in `shared/`
  locations. Move to `components/` or `lib/` only when a second consumer needs
  it.
- New features start as a new folder under `frontend/src/features/`.

Backend rules:

- Services in `app/services` initialise lazily — no network calls at import or
  app startup, and never at module import time.
- LLM/embedding providers are swappable behind the protocols in
  `app/services/llm.py` and `app/services/embeddings.py`; do not hard-code a
  vendor in call sites.

## 8. Project conventions & commands

- Readable code, full type hints (Python and TypeScript), clear naming.
- Python: `uv` only (never pip directly into the venv). Lint with Ruff, test
  with Pytest. TypeScript: check with `tsc --noEmit`, lint with ESLint, test
  with Vitest.

| Task                | Command                                            |
| ------------------- | -------------------------------------------------- |
| Backend deps        | `cd backend && uv sync`                            |
| Backend dev server  | `cd backend && uv run uvicorn app.main:app --reload` |
| Backend tests       | `cd backend && uv run pytest`                      |
| Backend lint        | `cd backend && uv run ruff check .`                |
| Frontend deps       | `cd frontend && npm install`                       |
| Frontend dev server | `cd frontend && npm run dev`                       |
| Frontend tests      | `cd frontend && npm test`                          |
| Frontend lint       | `cd frontend && npm run lint`                      |
| Frontend typecheck  | `cd frontend && npm run typecheck`                 |
| Frontend build      | `cd frontend && npm run build`                     |

## 9. Agent configuration map (no duplicated rules)

| Agent        | Reads automatically                              | Config in this repo                          |
| ------------ | ------------------------------------------------ | -------------------------------------------- |
| Antigravity  | `AGENTS.md` (workspace root)                     | — (rules via this file)                      |
| Cursor       | `AGENTS.md` + `.cursor/rules/*.mdc` + hooks      | `.cursor/rules/security.mdc`, `.cursor/hooks.json` |
| Grok (xAI)   | `AGENTS.md`                                      | — (rules via this file)                      |
| Codex (OpenAI) | `AGENTS.md`                                    | — (rules via this file)                      |
| Claude Code  | `CLAUDE.md` → pointer to `AGENTS.md`             | `CLAUDE.md`                                  |
| OpenCode     | `AGENTS.md` + native permission enforcement      | `opencode.jsonc`                             |

Security enforcement hooks live in `.hooks/guard.ps1` (shared guard logic used
by Cursor) and natively in `opencode.jsonc` (OpenCode permissions).

## 10. Code maps (Graphify)

The canonical Graphify policy is `.agent-policy/graphify.md` — read it before
using the map. In short: for architecture, call-relationship, dependency or
impact questions, query `graphify-out/graph.json` first (`graphify query "…"`),
then verify every symbol, path and line number against the current source.
`graphify-out/` is generated, Git-ignored and never committed. No agent may
install, upgrade or `graphify install` anything; report the need instead. Always
set `GRAPHIFY_NO_AUTO_REFRESH=1` before running graphify — it otherwise rewrites
skill copies outside this repository.

This repository is Git-initialised and carries four local hooks (`post-commit`,
`post-checkout`, `post-merge`, `post-rewrite`) that rebuild the map after history
changes and log to `graphify-out/rebuild.log`. They are hand-patched: **never run
`graphify hook install` again** — it would overwrite the patch and restore an
out-of-repo log path.
