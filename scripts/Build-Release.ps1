param(
    [string]$GoExecutable = 'go',
    [string]$OutputDirectory = '',
    [switch]$PublishWebsite,
    [switch]$SkipTests
)
$ErrorActionPreference = 'Stop'
$vyraRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
if (-not $OutputDirectory) { $OutputDirectory = Join-Path $vyraRoot '.build\release' }
$vyraOutput = [IO.Path]::GetFullPath($OutputDirectory)
$vyraVersion = (Get-Content -LiteralPath (Join-Path $vyraRoot 'VERSION') -Raw).Trim()
if ($vyraVersion -notmatch '^\d+\.\d+\.\d+$') { throw 'VERSION must contain a numeric release version' }
$vyraStage = Join-Path $vyraRoot ('.build\stage-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $vyraStage,$vyraOutput -Force | Out-Null
Push-Location $vyraRoot
try {
	$vyraTools = Join-Path $vyraRoot '.build\tools'
	New-Item -ItemType Directory -Path $vyraTools -Force | Out-Null
	$vyraOldGOBIN = $env:GOBIN
	try {
		$env:GOBIN = $vyraTools
		& $GoExecutable install github.com/tc-hib/go-winres@v0.3.3
		if ($LASTEXITCODE -ne 0) { throw 'Windows resource tool setup failed' }
	} finally { $env:GOBIN = $vyraOldGOBIN }
	$vyraResourceTool = Join-Path $vyraTools 'go-winres.exe'
	& $vyraResourceTool make --arch amd64 --file-version "$vyraVersion.0" --product-version "$vyraVersion.0"
	if ($LASTEXITCODE -ne 0) { throw 'Desktop icon and manifest generation failed' }
    if (-not $SkipTests) {
        & $GoExecutable test ./...
        if ($LASTEXITCODE -ne 0) { throw 'Desktop tests failed' }
        node --check web/app.js
        if ($LASTEXITCODE -ne 0) { throw 'Interface validation failed' }
        node --check clips-worker/static/intelligence.js
        if ($LASTEXITCODE -ne 0) { throw 'Intelligence workspace validation failed' }
        node --check clips-worker/static/connections.js
        if ($LASTEXITCODE -ne 0) { throw 'Connection wizard validation failed' }
        $vyraClipsUI = Get-Content -LiteralPath (Join-Path $vyraRoot 'clips-worker\static\index.html') -Raw
        $vyraClipsScript = [regex]::Match($vyraClipsUI, '<script>([\s\S]*?)</script>').Groups[1].Value
        $vyraClipsCheck = Join-Path $vyraRoot '.build\clips-ui-check.js'
        [IO.File]::WriteAllText($vyraClipsCheck, $vyraClipsScript, [Text.UTF8Encoding]::new($false))
        node --check $vyraClipsCheck
        if ($LASTEXITCODE -ne 0) { throw 'Clips interface validation failed' }
        node --test tests/oauth-relay.test.mjs
        if ($LASTEXITCODE -ne 0) { throw 'OAuth callback validation failed' }
    }
    $env:GOOS = 'windows'
    $env:GOARCH = 'amd64'
    & $GoExecutable build -trimpath -ldflags "-H=windowsgui -s -w -X main.version=$vyraVersion" -o (Join-Path $vyraStage 'VYRA.exe') .
    if ($LASTEXITCODE -ne 0) { throw 'Desktop build failed' }
    Copy-Item -LiteralPath (Join-Path $vyraRoot 'README.md'),(Join-Path $vyraRoot 'THIRD_PARTY_NOTICES.txt'),(Join-Path $vyraRoot 'SETUP_CLIPS.bat') -Destination $vyraStage
    # Only tracked worker source is packaged. Credentials and generated data
    # never enter the installer, even if they exist in the developer's folder.
    $vyraFiles = & git ls-files clips-worker
    if ($LASTEXITCODE -ne 0) { throw 'Cannot inventory tracked Clips source' }
    foreach ($vyraRelative in $vyraFiles) {
        if ($vyraRelative -match '(^|/)(\.env[^/]*|\.local|work|output|\.venv|__pycache__)(/|$)' -or $vyraRelative -match '\.(exe|zip|pyc)$') { continue }
        $vyraTarget = Join-Path $vyraStage $vyraRelative
        New-Item -ItemType Directory -Path (Split-Path $vyraTarget) -Force | Out-Null
        Copy-Item -LiteralPath (Join-Path $vyraRoot $vyraRelative) -Destination $vyraTarget
    }
    Compress-Archive -Path (Join-Path $vyraStage '*') -DestinationPath (Join-Path $vyraRoot 'installer\payload.zip') -Force
    Push-Location (Join-Path $vyraRoot 'installer')
    try {
		& $vyraResourceTool make --arch amd64 --file-version "$vyraVersion.0" --product-version "$vyraVersion.0"
		if ($LASTEXITCODE -ne 0) { throw 'Setup icon and manifest generation failed' }
		if (-not $SkipTests) {
			& $GoExecutable test ./...
			if ($LASTEXITCODE -ne 0) { throw 'Setup tests failed' }
			& $GoExecutable vet ./...
			if ($LASTEXITCODE -ne 0) { throw 'Setup validation failed' }
		}
        & $GoExecutable build -trimpath -ldflags "-H=windowsgui -s -w -X main.version=$vyraVersion" -o (Join-Path $vyraOutput 'VYRA-Setup.exe') .
        if ($LASTEXITCODE -ne 0) { throw 'Windows setup build failed' }
    } finally { Pop-Location }
    Copy-Item -LiteralPath (Join-Path $vyraStage 'VYRA.exe') -Destination $vyraOutput -Force
    Compress-Archive -Path (Join-Path $vyraStage '*') -DestinationPath (Join-Path $vyraOutput 'VYRA-Windows-Beta.zip') -Force
    $vyraChecksum = (Get-FileHash -LiteralPath (Join-Path $vyraOutput 'VYRA-Setup.exe') -Algorithm SHA256).Hash.ToLowerInvariant()
    $vyraManifest = [ordered]@{
        version = $vyraVersion
        url = "https://vyra-five-lac.vercel.app/downloads/$vyraVersion/VYRA-Setup.exe"
        sha256 = $vyraChecksum
        notes = 'Public defaults for new YouTube posts, verified publishing results, and Instagram reconnection compatibility.'
    }
    $vyraJSON = $vyraManifest | ConvertTo-Json
    [IO.File]::WriteAllText((Join-Path $vyraOutput 'latest.json'), $vyraJSON, [Text.UTF8Encoding]::new($false))
    if ($PublishWebsite) {
        $vyraWebsite = Join-Path $vyraRoot 'website'
        $vyraVersionFolder = Join-Path $vyraWebsite "downloads\$vyraVersion"
        New-Item -ItemType Directory -Path $vyraVersionFolder,(Join-Path $vyraWebsite 'updates') -Force | Out-Null
        Copy-Item -LiteralPath (Join-Path $vyraOutput 'VYRA-Setup.exe') -Destination $vyraVersionFolder -Force
        foreach ($vyraName in @('VYRA-Setup.exe','VYRA.exe','VYRA-Windows-Beta.zip')) {
            Copy-Item -LiteralPath (Join-Path $vyraOutput $vyraName) -Destination (Join-Path $vyraWebsite 'downloads') -Force
        }
        [IO.File]::WriteAllText((Join-Path $vyraWebsite 'updates\latest.json'), $vyraJSON, [Text.UTF8Encoding]::new($false))
    }
    Write-Output "VYRA $vyraVersion installer built and verified. SHA-256: $vyraChecksum"
} finally { Pop-Location }
