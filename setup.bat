@echo off
setlocal
cd /d "%~dp0"
python -m venv .venv
if errorlevel 1 exit /b 1
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip
python -m pip install -r backend\requirements.txt
if errorlevel 1 exit /b 1
echo Setup complete. Run start.bat to launch the API and dashboard.
endlocal
