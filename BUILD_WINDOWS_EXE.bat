@echo off
setlocal
cd /d "%~dp0"
where go >nul 2>&1 || (echo Install Go from https://go.dev/dl/ & pause & exit /b 1)
set GOOS=windows
set GOARCH=amd64
go build -trimpath -ldflags "-H=windowsgui -s -w" -o "VYRA.exe" .
if errorlevel 1 (echo Build failed. & pause & exit /b 1)
echo Finished: %CD%\VYRA.exe
pause
