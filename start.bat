@echo off
setlocal
cd /d "%~dp0"
if exist .venv\Scripts\activate.bat call .venv\Scripts\activate.bat
where uvicorn >nul 2>nul
if errorlevel 1 (
  echo FastAPI is unavailable. Run setup.bat first.
  exit /b 1
)
start "CADD Discovery API" /D "%~dp0" cmd /k "uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000"
start "CADD Discovery Dashboard" /D "%~dp0" cmd /k "python -m http.server 8080"
timeout /t 2 >nul
start "" http://127.0.0.1:8080
endlocal
