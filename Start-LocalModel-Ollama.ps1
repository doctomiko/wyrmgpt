param(
  [string]$Model = "llama3.1:8b-instruct-q4_K_M",
  [switch]$InstallOrUpdate,
  [switch]$PullIfMissing = $true,
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

if (-not (Get-Command ollama -ErrorAction SilentlyContinue)) {
  if ($InstallOrUpdate -and (Confirm-Step "Ollama not found. Install or update it now?")) {
    irm https://ollama.com/install.ps1 | iex
  } else {
    throw "Ollama is not installed or not on PATH."
  }
}

if ($InstallOrUpdate -and (Confirm-Step "Run Ollama install/update now?")) {
  irm https://ollama.com/install.ps1 | iex
}

Write-Host "Checking Ollama model list..."
ollama list

$models = Test-Endpoint "http://localhost:11434/v1/models"
if (-not $models) {
  throw "Ollama API is not responding at http://localhost:11434/v1/models"
}

$haveModel = $false
foreach ($m in $models.data) {
  if ($m.id -eq $Model) { $haveModel = $true; break }
}

if (-not $haveModel -and $PullIfMissing -and (Confirm-Step "Model '$Model' is missing. Pull it now?")) {
  ollama pull $Model
}

$body = @{
  model = $Model
  input = "Reply with exactly: Ollama is alive."
} | ConvertTo-Json

Write-Host "Sending probe to Ollama..."
Invoke-RestMethod `
  -Uri "http://localhost:11434/v1/responses" `
  -Method Post `
  -ContentType "application/json" `
  -Body $body