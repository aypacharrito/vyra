@echo off
setlocal
cd /d "%~dp0"
where go >nul 2>&1 || (echo Install Go from https://go.dev/dl/ & pause & exit /b 1)
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "scripts\Build-Release.ps1"
if errorlevel 1 (echo Build failed. & pause & exit /b 1)
echo Finished: %CD%\.build\release
pause
