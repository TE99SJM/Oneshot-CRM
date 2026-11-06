@echo off
REM One-time install of backend and frontend dependencies.
cd /d "%~dp0"
if not exist .env copy .env.example .env >nul
cd backend
python -m venv .venv || goto :err
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip
pip install -r requirements-dev.txt || goto :err
cd ..\frontend
call npm install || goto :err
echo.
echo Setup complete. Run dev.bat for development or start.bat for a single-server run.
pause
exit /b 0
:err
echo Setup failed. See the messages above.
pause
exit /b 1
