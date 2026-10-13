@echo off
setlocal
cd /d "%~dp0"
title VYRA Clips
where python >nul 2>nul
if errorlevel 1 (echo Python 3.11+ required. See README.md. & pause & exit /b 1)
where ffmpeg >nul 2>nul
if errorlevel 1 (echo Install FFmpeg and add it to PATH. See README.md. & pause & exit /b 1)
where ffprobe >nul 2>nul
if errorlevel 1 (echo FFprobe required with FFmpeg. & pause & exit /b 1)
if not exist ".venv\Scripts\python.exe" (python -m venv .venv)
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 (pause & exit /b 1)
if not exist ".env" (copy /Y .env.example .env >nul & echo Created .env; paste your OpenAI API key into the file and rerun. & start notepad .env & pause & exit /b 0)
start "" "http://127.0.0.1:8765"
".venv\Scripts\python.exe" -m uvicorn server:app --host 127.0.0.1 --port 8765
pause
