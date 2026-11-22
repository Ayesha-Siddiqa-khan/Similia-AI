# Similia AI

AI-powered homeopathic knowledge & case-analysis platform. **Phase 1 complete:**
a clean, running, testable development foundation (Next.js frontend + FastAPI
backend + Supabase/LangChain/RAG scaffolding). Next phase: RAG data ingestion
and knowledge base design.

## Project structure

```text
Similia AI/
├── AGENTS.md                    # Central rules for ALL AI agents (single source of truth)
├── CLAUDE.md                    # Pointer to AGENTS.md
├── README.md                    # This file
├── opencode.jsonc               # OpenCode native security permissions
├── .cursor/                     # Cursor rules + security hooks
├── .hooks/                      # Shared guard script + self-tests (Cursor hooks)
├── .opencode/skills/graphify/   # graphify knowledge-graph skill (project level)
├── frontend/                    # Next.js 16 (App Router, TypeScript, Tailwind 4)
│   └── src/
│       ├── app/                 # Routes, layout, providers, /api/health proxy route
│       ├── components/          # Shared UI (StatusBadge)
│       ├── features/            # One folder per feature (feature-based convention)
│       ├── hooks/               # Shared React hooks (useBackendHealth)
│       ├── lib/                 # supabase/ (ssr clients), graphql/ (client), api, health
│       ├── middleware.ts→proxy  # src/proxy.ts = Supabase SSR session refresh (Next 16)
│       └── types/               # Shared TypeScript types
├── backend/                     # FastAPI + Python 3.12 (uv-managed, uv.lock committed)
│   ├── app/
│   │   ├── api/routes/          # GET /health
│   │   ├── core/                # pydantic-settings config (all env vars)
│   │   ├── services/            # supabase, llm (LLMProvider), embeddings
│   │   │                        # (EmbeddingProvider), vector_store, rag
│   │   ├── graphql/             # Strawberry schema ({ health })
│   │   ├── ai/                  # graphs/ (LangGraph workflow) + Phase-2 modules
│   │   ├── models/              # Domain models (Phase 2)
│   │   └── schemas/             # Pydantic response schemas
│   └── tests/                   # Pytest smoke tests (4)
├── supabase/migrations/         # Future DB migrations (Phase 2)
└── docs/                        # Future documentation
```

## Technology stack & installed versions

| Layer      | Tech (actual installed version)                                                                                                                                 |
| ---------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Frontend   | Next.js 16.4.3, React 19.3.0, TypeScript 5, Tailwind CSS 4, ESLint 9                                                                        |
| FE libs    | @supabase/supabase-js 2.118, @supabase/ssr 0.12.7, TanStack React Query 5.105, Zod 4, react-hook-form 7.91, @hookform/resolvers 6, lucide-react 1.65, graphql-request 7.4 |
| FE testing | Vitest 5.0.5, @testing-library/react 16.3, jsdom 29                                                                                                              |
| Backend    | Python 3.12.12 (uv 0.10.4), FastAPI 0.162.0, Uvicorn 0.54.0, Pydantic 2.14.2 / pydantic-settings 2.16.2, HTTPX 0.28.1                                            |
| Database   | Supabase SDK 2.33.0 (PostgreSQL, Auth, Storage, pgvector — schema in Phase 2)                                                                                   |
| AI / RAG   | LangChain 1.4.7 (+ anthropic 1.7.7, voyageai 0.4.1, text-splitters 1.1.3, community 0.4.2), LangGraph 1.2.18, LangSmith 0.14.16, Voyage SDK 0.5.0, PyMuPDF 2.0    |
| GraphQL    | Strawberry GraphQL 0.339.0 (FastAPI integration)                                                                                                                |
| Quality    | Pytest 9.2.0, pytest-asyncio 1.4.1, Ruff 0.17.3                                                                                                                  |

All packages were verified against current official docs via Context7 before
installing (`voyage-4-lite` confirmed current, 1024-dim default; `ChatAnthropic`
/ `VoyageAIEmbeddings` import paths confirmed; Next 16 `proxy.ts` convention
confirmed).

## Requirements

- Node.js ≥ 20.9 (tested on v24.12.0) and npm 11
- [uv](https://docs.astral.sh/uv/) (tested on 0.10.4) — it provisions Python
  3.12 automatically (`.python-version`)
- No other global dependencies. No Docker.

## Setup

```powershell
# Backend (from repo root)
cd backend
uv sync                      # creates .venv on Python 3.12, installs from uv.lock
copy .env.example .env       # fill in real values later; app boots without it

# Frontend
cd ../frontend
npm install
copy .env.example .env.local # fill in real values later; app boots without it
```

## Development commands

| Task                | Command                                              |
| ------------------- | ---------------------------------------------------- |
| Backend dev server  | `cd backend; uv run uvicorn app.main:app --reload`   |
| Backend tests       | `cd backend; uv run pytest`                          |
| Backend lint        | `cd backend; uv run ruff check .`                    |
| Frontend dev server | `cd frontend; npm run dev`                           |
| Frontend tests      | `cd frontend; npm test`                              |
| Frontend lint       | `cd frontend; npm run lint`                          |
| Frontend typecheck  | `cd frontend; npm run typecheck`                     |
| Frontend build      | `cd frontend; npm run build`                         |
| API docs            | http://localhost:8000/docs (Swagger)                 |

## Environment variables

Placeholders live in `backend/.env.example` and `frontend/.env.example`.
**Never commit real credentials.** `.env*` is git-ignored.

- Frontend: `NEXT_PUBLIC_SUPABASE_URL`, `NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY`,
  `NEXT_PUBLIC_API_BASE_URL`
- Backend: `SUPABASE_URL`, `SUPABASE_PUBLISHABLE_KEY`, `SUPABASE_SECRET_KEY`
  (server-side only — never sent to the browser), `ANTHROPIC_API_KEY`,
  `ANTHROPIC_MODEL`, `VOYAGE_API_KEY`, `VOYAGE_MODEL` (default `voyage-4-lite`),
  `LANGSMITH_API_KEY`, `LANGSMITH_PROJECT`, `LANGSMITH_TRACING` (default
  `false`), `CORS_ORIGINS`

## API surface (Phase 1)

| Endpoint        | Purpose                                      |
| --------------- | -------------------------------------------- |
| `GET /health`   | Health + provider-configured flags (no secrets) |
| `GET /docs`     | Swagger UI                                    |
| `POST /graphql` | GraphQL — `{ health }` query                  |

The frontend proxies the health check through `GET /api/health` (server-side),
so backend URLs/keys never reach the browser. The homepage shows a live backend
connectivity indicator.

## Security & AI-agent policy

All AI agents share one rules file (`AGENTS.md`): strict project boundary, no
internet/dependency access without explicit approval, fail-safe stop-and-ask,
English-only responses, Context7 for docs. Enforcement: Cursor hooks
(`.cursor/hooks.json` → `.hooks/guard.ps1`, `failClosed: true`) and OpenCode
permissions (`opencode.jsonc`). See `AGENTS.md` for the full policy.
`frontend/AGENTS.md` is auto-generated Next.js framework guidance, not project
policy.

## Verification status (Phase 1)

All checks executed and passing:

- ✅ Frontend deps install (467 packages, 0 vulnerabilities)
- ✅ Backend deps resolve/install (118 resolved, `uv.lock` generated)
- ✅ All 20 required Python packages importable on 3.12.12
- ✅ FastAPI starts; `GET /health` → 200 (live-tested)
- ✅ GraphQL `{ health }` → 200 (live-tested)
- ✅ Next.js starts; homepage → 200; `GET /api/health` → `{"backend":"ok"}` (live end-to-end)
- ✅ ESLint, `tsc --noEmit`, Vitest 5/5, Pytest 4/4, Ruff clean
- ✅ `next build` production build succeeds
- ✅ Lockfiles present: `backend/uv.lock`, `frontend/package-lock.json`

## Known issues / notes

- `npm` reported one peer conflict (template's `@types/node@^20` vs vitest 5
  needing ≥22) — fixed properly by upgrading `@types/node` to ^24 (no
  `--force`).
- Next 16 renamed `middleware.ts` → `proxy.ts`; the Supabase SSR session
  refresh uses the new convention.
- The project-guard hooks intentionally block `curl`/`Invoke-WebRequest`; local
  endpoint verification was done with local Python/Node HTTP calls instead.
- `uv` warns about hardlinking on this filesystem (E: drive) — cosmetic only;
  set `UV_LINK_MODE=copy` to silence it.
- Vitest prints a config-loader notice about `vitest.config.ts` ESM syntax —
  harmless; a future Vite major wants `"type": "module"`.

## Next development phase

**Phase 2 — RAG data ingestion & knowledge base design:** Supabase schema with
pgvector + RLS (tenant isolation), Materia Medica / Repertory / Organon
ingestion with structure-aware chunking (traceability metadata is already
modelled in `app/services/rag.py`), Voyage embeddings, retrieval service, and
the first real Claude-backed case-analysis workflow via the existing provider
adapters.
