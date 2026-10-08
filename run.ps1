# Starts the API and the web app, then opens the browser. Press Ctrl+C here to stop both.
# -Seed: use %LOCALAPPDATA%\LocalJobTracker-dev and load the synthetic jobs (real data untouched).
param([switch]$Seed, [switch]$NoBrowser)
$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot

if ($Seed) { $env:LJT_DATA_DIR = Join-Path $env:LOCALAPPDATA 'LocalJobTracker-dev' }
else { Remove-Item Env:\LJT_DATA_DIR -ErrorAction SilentlyContinue }
if (-not (Test-Path api\.venv)) { Push-Location api; uv sync; Pop-Location }
if (-not (Test-Path web\node_modules)) { Push-Location web; npm install; Pop-Location }
if ($Seed) { Push-Location api; uv run python -m localjobtracker.seed; Pop-Location }

if (-not $NoBrowser) {
    Start-Job -ScriptBlock {
        1..60 | ForEach-Object {
            try { Invoke-WebRequest 'http://127.0.0.1:5173/' -UseBasicParsing -TimeoutSec 1 | Out-Null; Start-Process 'http://127.0.0.1:5173/'; break }
            catch { Start-Sleep -Seconds 1 }
        }
    } | Out-Null
}

python scripts\dev.py
