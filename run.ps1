# Starts the API and the web app, then opens the browser. Press Ctrl+C here to stop both.
# -Seed: use %LOCALAPPDATA%\LlmJobTracker-dev and load the synthetic jobs (real data untouched).
# -Electron: open the app in its own Electron window instead (Phase 13, D-17) — the Electron
# shell starts and stops the API and web dev server itself, so scripts\dev.py is not used in
# this mode. -NoBrowser has no effect together with -Electron.
param([switch]$Seed, [switch]$NoBrowser, [switch]$Electron)
$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot

if ($Seed) { $env:LJT_DATA_DIR = Join-Path $env:LOCALAPPDATA 'LlmJobTracker-dev' }
else { Remove-Item Env:\LJT_DATA_DIR -ErrorAction SilentlyContinue }
if (-not (Test-Path api\.venv)) { Push-Location api; uv sync; Pop-Location }
if (-not (Test-Path web\node_modules)) { Push-Location web; npm install; Pop-Location }
if ($Electron -and -not (Test-Path electron\node_modules)) { Push-Location electron; npm install; Pop-Location }
if ($Seed) { Push-Location api; uv run python -m llmjobtracker.seed; Pop-Location }

if ($Electron) {
    Push-Location electron
    try { npm start }
    finally { Pop-Location }
    exit $LASTEXITCODE
}

if (-not $NoBrowser) {
    Start-Job -ScriptBlock {
        1..60 | ForEach-Object {
            try { Invoke-WebRequest 'http://127.0.0.1:5173/' -UseBasicParsing -TimeoutSec 1 | Out-Null; Start-Process 'http://127.0.0.1:5173/'; break }
            catch { Start-Sleep -Seconds 1 }
        }
    } | Out-Null
}

python scripts\dev.py
