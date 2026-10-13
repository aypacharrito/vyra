# PUBLISH_SOURCE_TO_GITHUB.ps1 — deploy source; DOES NOT run the app.
$ErrorActionPreference = 'Stop'
$source = Split-Path -Parent $MyInvocation.MyCommand.Path
$destination = Join-Path $env:TEMP ('vyra-publish-' + (Get-Date -Format 'yyyyMMddHHmmss'))
if (-not (Get-Command git -ErrorAction SilentlyContinue)) { throw 'Install Git for Windows first (https://git-scm.com/download/win)' }
Write-Host 'Cloning the existing GitHub repository...' -ForegroundColor Cyan
& git clone https://github.com/aypacharrito/vyra.git $destination
if ($LASTEXITCODE -ne 0) { throw 'Git clone failed. Check GitHub access.' }
Write-Host 'Copying VYRA source and website files...' -ForegroundColor Cyan
Get-ChildItem -LiteralPath $source -Force | Where-Object { $_.Name -notin @('.git','PUBLISH_SOURCE_TO_GITHUB.ps1') } | ForEach-Object {
  Copy-Item -LiteralPath $_.FullName -Destination $destination -Recurse -Force
}
Set-Location $destination
& git add -A
& git diff --cached --quiet
if ($LASTEXITCODE -eq 0) { Write-Host 'Nothing to update.'; exit 0 }
& git commit -m 'Publish VYRA open beta desktop, website and Windows release pipeline'
if ($LASTEXITCODE -ne 0) { throw 'Git commit failed. Configure your Git name/email and retry.' }
Write-Host 'Pushing VYRA to GitHub...' -ForegroundColor Cyan
& git push origin main
if ($LASTEXITCODE -ne 0) { throw 'GitHub refused the push. Verify your own GitHub write access or branch rules.' }
Write-Host 'Code uploaded. Visit GitHub Actions to verify the release and Pages workflows.' -ForegroundColor Green
