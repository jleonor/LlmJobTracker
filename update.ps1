# Rebuilds the backend executable and the frontend bundle that `run.ps1 -Electron` runs from.
# That mode runs frozen builds (api\dist\llmjobtracker-api\llmjobtracker-api.exe and web\dist),
# not your source files directly, so a code change needs a rebuild here before -Electron sees it.
# -Backend / -Web: rebuild only that side. With neither switch, both are rebuilt.
param([switch]$Backend, [switch]$Web)
$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot

$buildBackend = $Backend -or -not $Web
$buildWeb = $Web -or -not $Backend

if ($buildBackend) {
    if (-not (Test-Path api\.venv)) { Push-Location api; uv sync; Pop-Location }
    Write-Host "Rebuilding the backend executable..."
    Push-Location api
    try { uv run pyinstaller llmjobtracker-api.spec --noconfirm }
    finally { Pop-Location }
}

if ($buildWeb) {
    if (-not (Test-Path web\node_modules)) { Push-Location web; npm install; Pop-Location }
    Write-Host "Rebuilding the frontend bundle..."
    Push-Location web
    try { npm run build }
    finally { Pop-Location }
}

Write-Host "Done. Restart run.ps1 -Electron to pick up the rebuilt build(s)."
