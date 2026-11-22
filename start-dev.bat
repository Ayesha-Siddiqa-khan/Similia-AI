@echo off
rem Similia AI - start backend (FastAPI :8000) and frontend (Next.js :3000)
rem Each app opens in its own window; close the window (or Ctrl+C) to stop it.
setlocal
set "ROOT=%~dp0"

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

netstat -ano | findstr /r ":3000 .*LISTENING" >nul && echo [WARN] Port 3000 already in use - a previous frontend may still be running.
netstat -ano | findstr /r ":8000 .*LISTENING" >nul && echo [WARN] Port 8000 already in use - a previous backend may still be running.

start "Similia AI - Backend (FastAPI :8000)" cmd /k "cd /d "%ROOT%backend" && uv run uvicorn app.main:app --reload"
start "Similia AI - Frontend (Next.js :3000)" cmd /k "cd /d "%ROOT%frontend" && npm run dev"

echo.
echo Similia AI starting:
echo   Backend  - http://localhost:8000   (Swagger: http://localhost:8000/docs)
echo   Frontend - http://localhost:3000
echo.
echo Close this window any time; the apps keep running in their own windows.
