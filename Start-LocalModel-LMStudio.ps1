param(
  [string]$Model = "meta-llama-3.1-8b-instruct",
  [switch]$StartServer = $true,
  [switch]$NoPrompt
)

$ErrorActionPreference = "Stop"

function Confirm-Step($message) {
  if ($NoPrompt) { return $true }
  $reply = Read-Host "$message [Y/n]"
  return ([string]::IsNullOrWhiteSpace($reply) -or $reply -match '^(y|yes)$')
}

function Test-Endpoint($url) {
  try {
    return Invoke-RestMethod $url
  } catch {
    return $null
  }
}

$lms = Get-Command lms -ErrorAction SilentlyContinue
if (-not $lms) {
  $fallback = Join-Path $HOME ".lmstudio\bin\lms.exe"
  if (Test-Path $fallback) {
    $env:PATH = "$(Split-Path $fallback);$env:PATH"
  } else {
    throw "LM Studio CLI (lms) not found. Run LM Studio once and make sure lms is installed."
  }
}

if ($StartServer -and (Confirm-Step "Start LM Studio local server now?")) {
  lms server start
  Start-Sleep -Seconds 2
}

$models = Test-Endpoint "http://localhost:1234/v1/models"
if (-not $models) {
  throw "LM Studio API is not responding at http://localhost:1234/v1/models"
}

$body = @{
  model = $Model
  input = "Reply with exactly: LM Studio is alive."
} | ConvertTo-Json

Write-Host "Sending probe to LM Studio..."
Invoke-RestMethod `
  -Uri "http://localhost:1234/v1/responses" `
  -Method Post `
  -ContentType "application/json" `
  -Body $body