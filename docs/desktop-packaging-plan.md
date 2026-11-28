# Similia AI — Windows Desktop Packaging Plan

Status: **implementation plan** (written before code changes)
Date: 2026-11-26
Scope: package the existing Next.js + FastAPI application as a self-contained x64
Windows desktop app with Electron, without rewriting the application.

---

## 1. Verified findings about the current architecture

| Area | Finding |
| --- | --- |
| Frontend | Next.js 16.4.6 App Router, React 19, TypeScript. Scripts exist for `dev`, `build`, `start`, `lint`, `typecheck`, `test`; no `dist`/desktop script. |
| Backend | FastAPI 0.162 + Uvicorn, Python 3.12 managed by `uv` (`backend/.venv`, `uv.lock`). Entrypoint `app.main:app`. |
| Auth | Supabase SSR cookies. `src/proxy.ts` refreshes sessions. `/api/backend/*` validates the Supabase user and role server-side before proxying to FastAPI with the user's access token. |
| Browser/backend boundary | The browser never calls FastAPI directly. Next server routes proxy to `API_BASE_URL` (default `http://localhost:8000`). |
| Public config | `NEXT_PUBLIC_SUPABASE_URL` / `NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY` are inlined into browser bundles at **build time**; the publishable key is public by design. Server code also reads them at runtime. |
| Backend secrets | `SUPABASE_SECRET_KEY`, `APP_ENCRYPTION_KEY`, `VOYAGE_API_KEY`, optional `ANTHROPIC_API_KEY`. Must never be bundled in the installer. |
| Production guard | `app/core/startup.py` refuses `ENVIRONMENT=production` with missing secrets or `http://` CORS origins. A desktop app runs on loopback HTTP, so a desktop-aware guard is required. |
| CSP | `next.config.ts` adds `upgrade-insecure-requests` and HSTS in production. On `http://127.0.0.1` this would break asset loading / pin localhost, so it must be disabled in desktop mode. |
| Speech | `backend/app/services/speech/*` launches `worker.py` in a **separate Python interpreter**. Defaults point at `E:\github\BOBO…` (outside this repo) and the dev venv. `faster-whisper` is **not** in `pyproject.toml` and not installed in the venv. |
| Speech config | `.speech_settings.json` lives in the repo/backend directory; model weights are multi-GB and external. |
| Local data | Ingestion artifacts use `backend/app/ai/ingestion/local.py` `ROOT/reports/ingestion`; tokenizer/budget paths and Urdu font are repo-relative. In an installed app these must move under the user profile. |
| Existing Electron | None. `frontend/package.json` has no `dist` script and no Electron config. |
| Uncommitted work | The working tree already contains many user changes (backend/frontend/docs). This work must be additive and must not revert them. |

## 2. Target architecture

```
Similia AI.exe (Electron main)
├─ splash window (no app content until services are ready)
├─ main BrowserWindow → http://127.0.0.1:<frontend-port>
├─ child: Similia AI.exe with ELECTRON_RUN_AS_NODE=1
│   └─ resources/frontend/server.js   (Next.js standalone server)
│       └─ server-side proxy → 127.0.0.1:<backend-port>
└─ child: resources/backend/similia-backend.exe  (PyInstaller onedir)
    ├─ FastAPI/Uvicorn on 127.0.0.1:<backend-port>
    └─ speech worker: same exe --speech-worker (Faster-Whisper in a child process)
```

- **No development server, Node.js, Python, uv, or VS Code is required on the target machine.**
- The Next.js production server is bundled using `output: "standalone"` (server + required
  runtime dependencies).
- The FastAPI backend is a PyInstaller **onedir** executable with a frozen speech worker.
- `faster-whisper`/CTranslate2 runtime is bundled; **model weights are not**. Models are
  selected in Settings and stay external.
- Loopback-only binding (`127.0.0.1`), random free ports per launch, per-launch shared token.

## 3. Security model

1. **Renderer isolation**: `contextIsolation: true`, `nodeIntegration: false`,
   `sandbox: true`, `webviewTag: false`. No remote module.
2. **Narrow preload API** (no generic IPC):
   - `pickModelFolder()` → native `dialog.showOpenDialog({ properties: ["openDirectory"] })`
   - `getInfo()`, `openDataFolder()`, `openLogsFolder()`
   - setup window gets a separate preload with only `getBootstrap`, `saveConfig`, `close`.
3. **IPC sender validation**: every handler verifies the sender frame origin is the exact
   local app origin; otherwise the call is rejected.
4. **Service isolation**: both servers bind `127.0.0.1` only. FastAPI requires a
   per-launch `X-Similia-Desktop-Token` on `/api/*` and `/graphql` when desktop mode is
   active (constant-time compare); `/health` and `/ready` stay available to readiness probes.
   The Next proxy adds the header server-side.
5. **Credentials at rest**: `%APPDATA%\Similia AI\config.json`; secret values encrypted with
   Electron `safeStorage` (Windows DPAPI, per-user). `APP_ENCRYPTION_KEY` is generated locally.
   Secrets are passed to children via environment variables, never argv or logs.
6. **No secrets in the installer**: service-role key, encryption key and provider keys are
   collected on first run (or via Settings) and stored under the user profile.
7. **Clinical data**: existing Supabase/RLS and server-side role checks remain unchanged.
   No production schema, patient data, billing or API credentials are modified.
8. **Logs**: `%APPDATA%\Similia AI\logs\*.log`; existing backend logging already avoids
   query strings, bodies, tokens and patient identity.

## 4. Data locations

| Data | Location |
| --- | --- |
| Desktop config (encrypted secrets) | `%APPDATA%\Similia AI\config.json` |
| Speech settings | `%APPDATA%\Similia AI\speech-settings.json` |
| Ingestion artifacts / tokenizer / budget DB | `%APPDATA%\Similia AI\data\…` via `SIMILIA_DATA_DIR` |
| Logs | `%APPDATA%\Similia AI\logs\` |
| Bundled app files | `%LOCALAPPDATA%\Programs\Similia AI\resources\` |
| Speech models | Any user-selected folder (external, never installed) |

## 5. Files to add / change

### New desktop layer (`desktop/`)

```
desktop/
  package.json                 # electron + electron-builder devDeps
  electron-builder.yml         # x64 NSIS installer
  electron/
    main.js                    # lifecycle, windows, menu, IPC, hardening
    preload.js                 # narrow window.similiaDesktop API
    setup-preload.js           # first-run config API
    setup.html                 # local-only configuration form
    splash.html                # startup progress
    lib/config.js              # paths, safeStorage, validation, env builders
    lib/services.js            # spawn, readiness, logs, shutdown tree
    lib/security.js            # sender validation, permissions, navigation
  scripts/
    dev.mjs                    # desktop:dev
    build.mjs                  # frontend + backend staging
    dist-win.mjs               # build + electron-builder
    smoke.mjs                  # automated launch/readiness/render check
    build-config.mjs           # writes public build metadata
  tests/*.test.mjs             # node --test checks for config/env/readiness
  build/icon.ico               # generated app icon
```

### Root

- `package.json` with documented scripts: `desktop:dev`, `desktop:build`, `dist:win`,
  `desktop:test`, `desktop:smoke`.
- `.gitignore` additions: `desktop/resources/`, `release/`, `desktop/node_modules/`,
  `desktop/.build/`.

### Backend

- `pyproject.toml`: declare `psutil`, `cryptography`; add `faster-whisper` to a `speech`
  dependency group and `pyinstaller` to a `packaging` group.
- `desktop_entry.py`: frozen entrypoint; `--speech-worker` dispatches to the worker,
  otherwise starts Uvicorn with host/port from argv/env.
- `similia-backend.spec`: PyInstaller onedir spec with hidden imports/data for
  Uvicorn, faster-whisper, CTranslate2, av, onnxruntime, tokenizers, PyMuPDF.
- `app/core/config.py`: `desktop_token`, `data_dir` settings.
- `app/core/startup.py`: accept `ENVIRONMENT=desktop`; allow loopback HTTP CORS only.
- `app/core/desktop_guard.py`: constant-time desktop token middleware + tests.
- `app/main.py`: install the guard when a desktop token is set; hide docs in desktop mode.
- `app/services/speech/config.py`: env-driven config/model paths, no hard-coded BOBO path,
  no dev-venv dependency.
- `app/services/speech/faster_whisper_engine.py`: in a frozen build launch
  `sys.executable --speech-worker`; keep dev interpreter support.
- `app/ai/ingestion/local.py`, `app/services/embeddings.py`: use `SIMILIA_DATA_DIR` for
  artifacts, tokenizer and budget DB.
- `app/services/report_files.py`: already supports `URDU_FONT_DIR`; set it from Electron.
- Tests for desktop guard, env-driven speech defaults, frozen command selection.

### Frontend

- `next.config.ts`: `output: "standalone"`; omit HSTS and
  `upgrade-insecure-requests` when `SIMILIA_DESKTOP=1`.
- `src/app/api/backend/[...path]/route.ts`: add `X-Similia-Desktop-Token` server-side.
- `src/features/speech/components/speech-settings.tsx`: “Browse…” button using the
  desktop preload folder picker; hidden in a normal browser.
- `src/types/desktop.d.ts`: typed `window.similiaDesktop`.
- Test for the picker button (present in desktop, absent in browser).

### Documentation

- `docs/desktop-packaging.md`: build prerequisites, exact commands, artifact location,
  first-run setup, model installation, clean-machine checklist, troubleshooting.
- Link from `README.md`.

## 6. Startup / readiness / shutdown sequence

1. Single-instance lock; set AppUserModelId; load config.
2. First run (or incomplete config): show local setup window; save encrypted config.
3. Pick free loopback ports; generate per-launch desktop token.
4. Start backend exe with env (config + data paths + token).
5. Poll `GET /health` until 200 `status=ok` (timeout 90 s). Capture logs.
6. Start Next standalone server with `ELECTRON_RUN_AS_NODE=1` (or bundled node if present).
7. Poll `GET /api/health` until it returns 200 and reports `backend: ok` (proves both
   processes and the proxy path).
8. Show the main window (`ready-to-show`), close the splash.
9. On failure: show an error dialog naming the failing service and the log path.
10. On quit: graceful `SIGTERM`/`taskkill` of each child tree; verify the speech worker is
    gone; close logs. `window-all-closed` quits on Windows.

## 7. Build pipeline

```
npm --prefix desktop install            # electron, electron-builder
cd backend; uv sync --group speech --group packaging
npm run desktop:build                   # frontend build + PyInstaller + staging
npm run dist:win                        # electron-builder → release/Similia AI Setup <ver>.exe
```

- Frontend build env: `NEXT_PUBLIC_SUPABASE_URL`, `NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY`
  (required for a usable installer), `API_BASE_URL` placeholder (runtime overrides it).
- Staging:
  - `frontend/.next/standalone` → `desktop/resources/frontend`
  - `frontend/.next/static` → `…/frontend/.next/static`
  - `frontend/public` → `…/frontend/public`
  - PyInstaller output → `desktop/resources/backend`
  - Urdu font → `desktop/resources/assets/JameelNooriNastaleeq.ttf`
  - public build metadata → `desktop/resources/desktop-build.json`
- electron-builder: `asar: true`, `extraResources` for the staged runtime, NSIS x64,
  per-user install, changeable install directory, desktop + start-menu shortcuts,
  artifact name `Similia AI Setup <version>.exe`.
- No code signing certificate is assumed; SmartScreen warning is documented.

## 8. Test plan

| # | Check | Method |
| --- | --- | --- |
| 1 | Config/env builder validation | `node --test desktop/tests` |
| 2 | Desktop token guard | Pytest (`test_desktop_guard.py`) |
| 3 | Speech defaults / frozen command | Pytest (updated `test_speech.py`) |
| 4 | Existing backend suite | `cd backend; uv run pytest` |
| 5 | Frontend unit tests / types / lint | `npm test`, `npm run typecheck`, `npm run lint` |
| 6 | Next production build | `npm run build` with standalone output |
| 7 | Backend exe starts | Run exe on a free port; `/health` 200; token guard 401/200 |
| 8 | Frontend standalone serves | Run with Electron-as-Node; `/login` and `/api/health` 200 |
| 9 | Electron launch | `npm run desktop:dev` and packaged smoke mode; verify window loads |
| 10 | Installer | Build NSIS, silent install to a temp dir, launch installed app with a PATH that contains no Python/Node |
| 11 | Speech runtime | Worker ping + model validation in the packaged exe; real transcription only if a local model is available |
| 12 | Clean Windows | **Limitation:** no clean Windows VM/CI runner is available here. Simulate with sanitized PATH and report the remaining manual VM check. |
| 13 | Case workflow | **Limitation:** requires real Supabase credentials and would create patient data. Do not run against production. Verify via existing backend/frontend tests and live `/health`/login rendering; document the manual authenticated check. |

## 9. Explicit non-goals / constraints

- Do not bundle multi-GB speech models.
- Do not modify patient records, Supabase production schema, cloud billing, or API keys.
- Do not deploy or publish.
- Do not revert the existing uncommitted working-tree changes.
- Do not claim a clean-machine or authenticated case-workflow test that was not actually run.

## 10. Dependencies requiring approval (repository policy)

The repo rules require explicit approval before downloads. This work needs:

1. `npm` packages in `desktop/`: `electron`, `electron-builder` (plus the Electron binary
   and NSIS tooling that electron-builder downloads during the build).
2. Python packages: `faster-whisper` (speech runtime) and `pyinstaller` (backend build),
   and a `uv lock` refresh to declare `psutil`/`cryptography`.
3. No internet access at runtime; all provider calls remain user-initiated app behavior.

## 11. Rollback

- All application changes are additive and isolated: delete `desktop/`, `release/`, the
  root `package.json`, and revert the small backend/frontend edits if needed.
- The existing development workflow (`start-dev.bat`, `uv run`, `npm run dev`) remains
  valid; desktop mode is opt-in through environment variables.

## 12. Continuation plan for the desktop implementation already in the working tree

1. Preserve the existing desktop files and unrelated in-progress clinical changes. Inventory the installed build tools, staged runtime, and usable test fixtures. The code map predates the new desktop files, so verify the desktop integration against source.
2. Review the local trust boundary end to end. Require a separate renderer-to-Next launch token, authenticate the Next-to-FastAPI readiness probe, restrict IPC to the intended top-level windows, and keep backend secrets out of the frontend child environment and staged resources. Preserve Supabase login and authorization.
3. Make startup and exit deterministic. Start FastAPI before Next, confirm the protected backend path through Next, await the initial document load, and use a graceful backend shutdown with a bounded Windows process-tree fallback. Verify that failures and early closing use the same cleanup path.
4. Verify the frozen speech command and native imports with the staged executable. Exercise worker timeout and teardown behavior and keep model selection external through the existing Settings control. Use a real model and synthetic audio only if the model is available and authorized.
5. Rebuild from repository-local dependencies and placeholder public values for offline testing. Verify staging excludes dotenv files and speech weights, then build the exact `release/Similia AI Setup.exe` artifact if the packaging tools are available. Run source tests, frozen-runtime tests, and the packaged smoke test with a stripped PATH.
6. Exercise authenticated case flows using synthetic fixtures without connecting to production. Record the difference between unit/integration tests, an actual installed smoke run, and a clean Windows VM run. Report any missing tools, model, fixture, or VM individually. Update the build runbook with verified commands and results.

## 13. Personal installer for the existing project

1. Use the public Supabase settings from `frontend/.env.local` to build the personal installer. Keep fixture builds behind an explicit flag and give them separate output. Reject stale staged resources from another project.
2. Add a setup action that opens a native file picker and asks for confirmation before reading the selected backend `.env`. Check that both public project settings match the installer, then save only the supported fields using DPAPI for secrets. Preserve optional AI Settings and existing launch and speech behavior.
3. Test config selection, mismatched imports and build guards with synthetic values. Build and install the personal x64 package, verify shortcuts and local readiness, and leave live account sign-in and record viewing to the user's authenticated session. Keep billable requests and production writes out of verification.
