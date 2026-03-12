param(
    [string]$Port = "8000"
)

$ErrorActionPreference = "Stop"

# Go to the project root (the folder where this script lives)
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

# Resolve venv Python
$venvPath = Join-Path $root ".venv"
$pythonExe = Join-Path $venvPath "Scripts\python.exe"
$activate = Join-Path $venvPath "Scripts\Activate.ps1"

if (-not (Test-Path $pythonExe)) {
    Write-Error "Could not find venv Python at $pythonExe. Did you create the .venv?"
    exit 1
}
if (-not (Test-Path $activate)) {
    Write-Error "Could not find venv activate script at $activate. Did you create the .venv?"
    exit 1
}

Write-Host "Using Python: $pythonExe"
Write-Host "Starting WyrmGPT on port $Port..."

Write-Host "Activating venv at '$activate'..."
. $activate
Write-Host "Launching web server..."
# Launch uvicorn with your FastAPI app
& $pythonExe -m uvicorn server.main:app --reload --port $Port