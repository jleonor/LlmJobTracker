<#
.SYNOPSIS
Starts LocalJobTracker: the API and the web app, then opens the browser.

.DESCRIPTION
Checks the prerequisites, installs missing dependencies, then runs scripts\dev.py.
Press Ctrl+C in this window to stop both servers.

Without -Seed the app uses the real data folder (%LOCALAPPDATA%\LocalJobTracker).
With -Seed it uses %LOCALAPPDATA%\LocalJobTracker-dev and loads the synthetic jobs
if that folder is empty. The real database is never touched by -Seed.

.PARAMETER Seed
Use the development data folder with synthetic jobs.

.PARAMETER NoBrowser
Do not open the browser automatically.

.EXAMPLE
.\run.ps1 -Seed

.EXAMPLE
powershell -ExecutionPolicy Bypass -File .\run.ps1 -Seed
#>
[CmdletBinding()]
param(
    [switch]$Seed,
    [switch]$NoBrowser
)

$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot
$apiDir = Join-Path $root 'api'
$webDir = Join-Path $root 'web'
$python = Join-Path $apiDir '.venv\Scripts\python.exe'
$appUrl = 'http://127.0.0.1:5173/'

function Stop-Setup([string]$message) {
    Write-Host "ERROR: $message" -ForegroundColor Red
    exit 1
}

foreach ($tool in 'python', 'uv', 'npm') {
    if (-not (Get-Command $tool -ErrorAction SilentlyContinue)) {
        Stop-Setup "$tool is not on PATH. Install it and open a new PowerShell window."
    }
}

if (-not (Test-Path $python)) {
    Write-Host 'Installing API dependencies (uv sync)...'
    Push-Location $apiDir
    try {
        uv sync
        if ($LASTEXITCODE -ne 0) { Stop-Setup 'uv sync failed.' }
    }
    finally {
        Pop-Location
    }
}

if (-not (Test-Path (Join-Path $webDir 'node_modules'))) {
    Write-Host 'Installing web dependencies (npm install)...'
    Push-Location $webDir
    try {
        npm install
        if ($LASTEXITCODE -ne 0) { Stop-Setup 'npm install failed.' }
    }
    finally {
        Pop-Location
    }
}

foreach ($port in 5173, 8765) {
    if (Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue) {
        Stop-Setup "Port $port is already in use. Close the other LocalJobTracker window first."
    }
}

if ($Seed) {
    $env:LJT_DATA_DIR = Join-Path $env:LOCALAPPDATA 'LocalJobTracker-dev'
    Push-Location $apiDir
    try {
        & $python -m localjobtracker.seed
        if ($LASTEXITCODE -ne 0) { Stop-Setup 'Seeding failed.' }
    }
    finally {
        Pop-Location
    }
    Write-Host "Using the development data folder: $env:LJT_DATA_DIR"
}
else {
    Write-Host "Using the app data folder: $(Join-Path $env:LOCALAPPDATA 'LocalJobTracker')"
}

# Open the browser once the page answers. The job runs in the background and is removed on exit.
$opener = $null
if (-not $NoBrowser) {
    $opener = Start-Job -ArgumentList $appUrl -ScriptBlock {
        param($url)
        for ($i = 0; $i -lt 120; $i++) {
            try {
                Invoke-WebRequest -Uri $url -UseBasicParsing -TimeoutSec 2 | Out-Null
                Start-Process $url
                return
            }
            catch {
                Start-Sleep -Milliseconds 500
            }
        }
    }
}

try {
    Write-Host "Starting LocalJobTracker at $appUrl (Ctrl+C to stop)."
    & $python (Join-Path $root 'scripts\dev.py')
    exit $LASTEXITCODE
}
finally {
    if ($opener) { Remove-Job -Job $opener -Force -ErrorAction SilentlyContinue }
}
