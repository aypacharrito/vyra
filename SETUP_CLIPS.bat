@echo off
setlocal
cd /d "%~dp0clips-worker"
where python >nul 2>&1 || (echo Install Python 3.11 or newer, then run this setup again. & pause & exit /b 1)
if not exist ".venv\Scripts\python.exe" python -m venv .venv
if errorlevel 1 (echo Could not create the Clips environment. & pause & exit /b 1)
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 (echo Dependency setup failed. Check your internet connection. & pause & exit /b 1)
where ffmpeg >nul 2>&1 || echo FFmpeg is still required. Install FFmpeg and FFprobe on your Windows PATH.
echo VYRA Clips setup complete. Return to VYRA and launch Clips Studio.
pause
