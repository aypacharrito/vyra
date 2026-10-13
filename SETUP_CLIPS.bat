@echo off
setlocal
cd /d "%~dp0clips-worker"
where python >nul 2>&1 || (echo Install Python 3.11+ from python.org & pause & exit /b 1)
python -m pip install -r requirements.txt
if errorlevel 1 (echo Dependencies failed. & pause & exit /b 1)
where ffmpeg >nul 2>&1 || echo FFmpeg not on PATH. Install it before generating clips.
echo VYRA Clips dependencies set up. Launch VYRA and open Clips.
pause
