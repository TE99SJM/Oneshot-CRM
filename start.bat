@echo off
REM Production-style local run: build the UI once, then serve everything from http://localhost:8000
cd /d "%~dp0"
cd frontend && call npm run build || goto :err
cd ..\backend && call .venv\Scripts\activate.bat
start http://localhost:8000
uvicorn app.main:app --host 127.0.0.1 --port 8000
exit /b 0
:err
echo Frontend build failed.
pause
