@echo off
rem Similia AI - start backend (FastAPI :8011) and frontend (Next.js :3000)
rem Each app opens in its own window; close the window (or Ctrl+C) to stop it.
setlocal
set "ROOT=%~dp0"
set "BACKEND_PORT=8011"
set "API_BASE_URL=http://127.0.0.1:%BACKEND_PORT%"

if not exist "%ROOT%backend\.venv" (
  echo [ERROR] Backend venv missing. Run first: cd backend ^&^& uv sync
  pause
  exit /b 1
)
if not exist "%ROOT%frontend\node_modules" (
  echo [ERROR] Frontend dependencies missing. Run first: cd frontend ^&^& npm install
  pause
  exit /b 1
)

netstat -ano | findstr /r ":%BACKEND_PORT% .*LISTENING" >nul
if errorlevel 1 (
  start "Similia AI - Backend (FastAPI :%BACKEND_PORT%)" /D "%ROOT%backend" cmd /k "uv run --offline --locked --no-sync uvicorn app.main:app --host 127.0.0.1 --port %BACKEND_PORT% --reload --reload-dir app"
) else (
  echo [INFO] Backend port %BACKEND_PORT% is already in use. Skipping duplicate launch.
)

netstat -ano | findstr /r ":3000 .*LISTENING" >nul
if errorlevel 1 (
  start "Similia AI - Frontend (Next.js :3000)" /D "%ROOT%frontend" cmd /k "npm run dev"
) else (
  echo [INFO] Frontend port 3000 is already in use. Skipping duplicate launch.
)

echo.
echo Similia AI starting:
echo   Backend  - http://127.0.0.1:%BACKEND_PORT%   (Swagger: http://127.0.0.1:%BACKEND_PORT%/docs)
echo   Frontend - http://localhost:3000
echo.
echo Close this window any time; the apps keep running in their own windows.
