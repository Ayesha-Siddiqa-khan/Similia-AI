# Similia AI Windows desktop packaging

The x64 NSIS installer contains Electron, the existing Next.js standalone server,
and the FastAPI and Faster-Whisper libraries in a PyInstaller executable.
The installed app supplies its own Node.js and Python runtimes.
[Implementation plan](./desktop-packaging-plan.md)

## Build on Windows x64

Use x64 Node.js and npm, `uv`, and Python 3.12. Run the following from the repository root.

```powershell
npm.cmd --prefix frontend ci
npm.cmd --prefix desktop ci
Push-Location backend
uv sync --locked --group speech --group packaging
Pop-Location

npm.cmd run dist:win
Get-Item -LiteralPath '.\release\Similia AI Setup.exe'
```

The default build reads `NEXT_PUBLIC_SUPABASE_URL` and
`NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY` from `frontend/.env.local` and fails if
they do not describe a real HTTPS project. The shell's environment does not
override this file. The installer is **`release\Similia AI Setup.exe`**. The unpacked app is
`release\win-unpacked\Similia AI.exe`. The unsigned installer may trigger
Windows SmartScreen.

| Command | Purpose |
| --- | --- |
| `npm.cmd run desktop:dev` | Start Electron, Next dev and the source backend with the existing development configuration. |
| `npm.cmd run desktop:build` | Build and stage the standalone frontend, frozen backend and report font. |
| `npm.cmd run dist:win` | Build and package the x64 NSIS installer. |
| `npm.cmd run dist:win -- --staged` | Package existing staged resources. |
| `npm.cmd run desktop:test` | Run the desktop configuration and lifecycle tests. |
| `node desktop/tests/credential-store.cjs` | Verify Windows DPAPI persistence across two Electron launches with synthetic secrets. |
| `npm.cmd run desktop:smoke` | Verify the offline test build with a synthetic case. |

The frontend is built from a clean copy of the sources without dotenv files.
Use `npm.cmd run desktop:build -- --reuse-dependencies` to reuse the staged
dependency copy if the frontend lockfile matches. Use the normal build after
updating frontend dependencies.

## Configure and launch

On the first launch of the personal installer, choose **Import existing backend .env**,
select `E:\github\Similia AI\backend\.env`, and confirm **Import and start**
in the Windows dialog. The Electron main process reads the selected file after
confirmation. It checks the Supabase URL and publishable key against the build,
then saves the service-role key, Voyage key, and existing Fernet key. If present,
it also preserves previous Fernet keys, the Voyage model, the embedding budget,
and the clinical workflow flag. The source file remains in place.

If you prefer the one-time command, close Similia AI first and run this from
the repository root. It checks the installed project's public metadata and
uses the same DPAPI store as the setup screen.

```powershell
node desktop/scripts/import-config.cjs --confirm-import
```

For a custom installation directory, add `"--installed-dir=C:\your\Similia AI"`.
After importing, launch from the desktop shortcut.

The service-role key is required by the current backend. It verifies sessions
before enforcing trusted practitioner and operator roles and performs privileged
case and knowledge-base operations. Importing the existing Fernet key keeps
previously encrypted provider keys readable. Use **AI Settings** after signing
in to configure your Anthropic key and model. Manual desktop setup remains
available. The desktop launcher disables automatic ingestion resumption at startup.

Change or re-import the desktop configuration via **File → Settings**. Windows
DPAPI encrypts imported secrets at rest for your Windows account. An already
compromised account or malware running as that account can still access them.
The importer writes no plaintext temporary file, and the setup renderer receives
only public settings and credential-presence flags. The frontend child receives
the public project values and local service tokens. Existing Supabase sign-in
and role checks apply to clinical operations.

| Data | Default location |
| --- | --- |
| Application | `%LOCALAPPDATA%\Programs\Similia AI\` |
| Configuration | `%APPDATA%\Similia AI\config.json` |
| Speech settings | `%APPDATA%\Similia AI\speech-settings.json` |
| Local data and logs | `%APPDATA%\Similia AI\data\` and `%APPDATA%\Similia AI\logs\` |

Electron starts FastAPI and Next.js on separate dynamically assigned loopback
ports. Local health probes verify both services with per-launch tokens before
the main window opens. The tokens also protect frontend and backend requests
from other local clients. Closing Similia AI requests backend shutdown,
including its speech worker, with a bounded process-tree fallback on Windows.
If startup fails, the error dialog gives the local logs directory.

## Local speech

In **Settings → Local Speech Recognition**, select **Browse…** and choose the
external CTranslate2 Faster-Whisper directory. It needs `model.bin`,
`config.json` and `tokenizer.json`, plus any vocabulary file distributed with
the model. Validate and save the path. The model weights stay in that folder.
The installed worker uses CPU by default in Auto mode. Explicit CUDA mode needs
compatible GPU libraries on the target machine.

## Offline packaging test

Build a test installer for the loopback-only Supabase fixture.

```powershell
npm.cmd run dist:win -- --offline-test

# Optional. The recording should contain the English word "desktop".
$env:SIMILIA_SMOKE_MODEL = "C:\Models\faster-whisper-large-v3"
$env:SIMILIA_SMOKE_AUDIO = "C:\TestMedia\desktop-speech.wav"
npm.cmd run desktop:smoke
```

The smoke runner uses a fresh profile and a Windows-only PATH. It checks
service readiness, rejects unauthenticated loopback requests, signs in as a
synthetic practitioner, reads and updates an in-memory case, and opens the
case editor. With both speech options set, it tests real transcription and
checks that the worker exits. Fixture installers and their unpacked apps are
under `release\offline-test`. Personal builds disable smoke overrides.

### Clean Windows installation

Copy the offline test installer and `desktop/scripts/smoke.mjs`,
`desktop/scripts/smoke-fixture.mjs` and `desktop/scripts/util.mjs` to a writable
folder in a disposable x64 VM. Keep the scripts under `desktop/scripts`. Install
per-user using the installer UI. Confirm that the shortcuts start the installed
app and open its first-run configuration. Close the setup window and use
the installed executable's own Node runtime to run the fixture.

```powershell
$similiaExe = Join-Path $env:LOCALAPPDATA 'Programs\Similia AI\Similia AI.exe'
$env:ELECTRON_RUN_AS_NODE = "1"
try {
  & $similiaExe .\desktop\scripts\smoke.mjs --exe $similiaExe | Out-Host
} finally {
  Remove-Item Env:ELECTRON_RUN_AS_NODE
}
```

In the VM, confirm the Settings button opens the native folder picker and test
uninstall from Windows **Settings → Apps**. Uninstall keeps the per-user data
so a reinstall can reuse it. Use a disposable or authorized test project for
live RAG, AI provider and clinical workflow acceptance tests.

## Verification on November 26, 2026

The personal x64 installer was built and installed on the user's Windows
computer. Both Windows shortcuts pointed to the installed personal build, and
launching from the desktop shortcut opened first-run setup. The frontend and
backend public settings matched, and the project accepted a read-only auth
settings request. The staged files passed a check for the backend secret
values, dotenv files and external model weights. All 18 desktop tests and 70
focused backend tests passed. A separate two-launch test confirmed DPAPI
persistence with synthetic credentials. The personal-build frozen speech
worker validated the external model and transcribed synthetic audio.
The confirmed one-time command imported the real backend settings into the
current Windows account. Launching the installed shortcut restored those
settings and started both loopback services without reopening setup.

Earlier offline fixture verification:

- The x64 NSIS build produced `release\Similia AI Setup.exe` using the
  loopback fixture configuration.
- The unpacked Electron app passed the Windows-only PATH smoke test, including
  frontend rendering, authenticated local service probes, synthetic sign-in,
  case editing, and a separate report window.
- The bundled speech worker transcribed a synthetic WAV with the external
  Faster-Whisper large-v3 model. The app shut down both services and the worker.
- Backend, frontend, and desktop tests passed. The packaged resources were
  checked for dotenv files, model weights, and development symlinks.
- Clean-machine installation, the physical microphone and native picker, and
  a live Supabase and AI provider workflow remain to be verified.
