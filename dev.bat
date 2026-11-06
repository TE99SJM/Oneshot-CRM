@echo off
REM Development mode: API with auto-reload on :8000 and Vite hot-reload UI on :5173.
cd /d "%~dp0"
start "FunnelHub API" cmd /k "cd backend && call .venv\Scripts\activate.bat && uvicorn app.main:app --reload --port 8000"
start "FunnelHub UI" cmd /k "cd frontend && npm run dev"
timeout /t 4 >nul
start http://localhost:5173
