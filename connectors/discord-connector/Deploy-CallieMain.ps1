<#
Deploy-CallieMain.ps1

Workflow:
1) Look in Downloads for main*.py
2) If found: stage newest to connector as main.incoming.<guid>.py
3) Move other download candidates to Backups
4) If not found: look in connector for main.incoming.*.py and use newest
5) Determine next backup suffix for today's EST date (letters a-z preferred, else 00-99)
6) Move current main.py -> Backups as main.backup.YYYY-MM-DD.<next>.py
7) Promote staged file -> main.py

Notes:
- Uses America/New_York date via Windows tz id "Eastern Standard Time"
- Fails loud and safe: never overwrites main.py without backing it up first
#>

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$Downloads = "M:\Tom\OneDrive - LiquidHg\Downloads"
$Connector = "M:\RunPortable\callie-connector"
$Backups   = Join-Path $Connector "Backups"

function Get-EstDateString {
    $tz = [System.TimeZoneInfo]::FindSystemTimeZoneById("Eastern Standard Time")
    $nowLocal = [System.TimeZoneInfo]::ConvertTime([DateTime]::UtcNow, $tz)
    return $nowLocal.ToString("yyyy-MM-dd")
}

function Get-NextBackupSuffix {
    param(
        [Parameter(Mandatory=$true)][string]$BackupDir,
        [Parameter(Mandatory=$true)][string]$DateString
    )

    $pattern  = "main.backup.$DateString.*.py"
    $existing = @(Get-ChildItem -LiteralPath $BackupDir -File -Filter $pattern -ErrorAction SilentlyContinue)

    # Prefer letter suffixes a-z if any exist today
    $letterRe = "^main\.backup\.$([regex]::Escape($DateString))\.([a-z])\.py$"
    $letters = @()

    foreach ($f in $existing) {
        $m = [regex]::Match($f.Name, $letterRe)
        if ($m.Success) { $letters += $m.Groups[1].Value }
    }

    if ($letters.Count -gt 0) {
        $maxLetter = ($letters | Sort-Object)[-1]
        if ($maxLetter -eq "z") { throw "Backup suffix overflow: already have 'z' for $DateString." }

        $next = [char]([byte][char]$maxLetter + 1)
        return [string]$next
    }

    # If no letter backups exist, use numeric 00-99
    $numRe = "^main\.backup\.$([regex]::Escape($DateString))\.(\d{2})\.py$"
    $nums = @()

    foreach ($f in $existing) {
        $m = [regex]::Match($f.Name, $numRe)
        if ($m.Success) { $nums += [int]$m.Groups[1].Value }
    }

    if ($nums.Count -eq 0) { return "00" }

    $maxNum = ($nums | Sort-Object)[-1]
    if ($maxNum -ge 99) { throw "Backup suffix overflow: already have 99 for $DateString." }

    return ("{0:D2}" -f ($maxNum + 1))
}

# --- Preconditions ---
if (-not (Test-Path -LiteralPath $Connector)) { throw "Connector folder not found: $Connector" }
if (-not (Test-Path -LiteralPath $Backups))   { New-Item -ItemType Directory -Path $Backups | Out-Null }

$incomingIsAlreadyStaged = $false
$stagedPath = $null
$sourceLabel = $null

# 1) Look for main*.py in Downloads
$downloadCandidates = @()
if (Test-Path -LiteralPath $Downloads) {
    $downloadCandidates = @(
        Get-ChildItem -LiteralPath $Downloads -File -ErrorAction SilentlyContinue |
            Where-Object { $_.Name -match '^main.*\.py$' } |
            Where-Object { $_.Name -notmatch '\.backup\.' } |
            #Where-Object { $_.Name -notmatch '\.incoming\.' } |
            Where-Object { $_.Name -notmatch '\.old\.' } |
            Where-Object { $_.Name -notmatch '\.bak(\.|$)' } |
            Sort-Object LastWriteTimeUtc -Descending
    )
}

if ($downloadCandidates.Length -gt 0) {
    Write-Host "Found $($downloadCandidates.Length) candidate file(s) in Downloads:" -ForegroundColor Cyan
    $downloadCandidates | ForEach-Object { Write-Host ("  {0}  ({1})" -f $_.Name, $_.LastWriteTime) }

    # 2) Stage newest from Downloads into Connector (unique staging name)
    $newest = $downloadCandidates[0]
    $stagedName = ("main.incoming.{0}.py" -f ([Guid]::NewGuid().ToString("N")))
    $stagedPath = Join-Path $Connector $stagedName

    Write-Host "`nStaging newest file: $($newest.Name) -> $stagedPath" -ForegroundColor Yellow
    Move-Item -LiteralPath $newest.FullName -Destination $stagedPath
    $sourceLabel = $newest.Name

    # 3) Move other download candidates to Backups
    if ($downloadCandidates.Length -gt 1) {
        $others = $downloadCandidates[1..($downloadCandidates.Length-1)]
        foreach ($f in $others) {
            $dest = Join-Path $Backups $f.Name
            if (Test-Path -LiteralPath $dest) {
                $stamp = (Get-Date).ToString("yyyyMMdd-HHmmss")
                $dest = Join-Path $Backups ("{0}.{1}" -f $f.Name, $stamp)
            }
            Write-Host "Moving extra candidate -> Backups: $($f.Name) -> $dest" -ForegroundColor DarkYellow
            Move-Item -LiteralPath $f.FullName -Destination $dest
        }
    }
} else {
    # 4) Fallback: use newest already-staged incoming file in Connector
    $stagedCandidates = @(
        Get-ChildItem -LiteralPath $Connector -File -ErrorAction SilentlyContinue |
            Where-Object { $_.Name -match '^main\.incoming\..*\.py$' } |
            Sort-Object LastWriteTimeUtc -Descending
    )

    if ($stagedCandidates.Length -lt 1) {
        throw "No files matching 'main*.py' found in Downloads AND no staged 'main.incoming.*.py' found in: $Connector"
    }

    $incomingIsAlreadyStaged = $true
    $newest = $stagedCandidates[0]
    $stagedPath = $newest.FullName
    $sourceLabel = $newest.Name

    Write-Host "No 'main*.py' found in Downloads. Using newest staged incoming file in connector:" -ForegroundColor Yellow
    Write-Host ("  {0}  ({1})" -f $newest.Name, $newest.LastWriteTime)
}

# 5) Determine today's date string (NY) and next suffix
$dateStr = Get-EstDateString
$suffix  = Get-NextBackupSuffix -BackupDir $Backups -DateString $dateStr

# 6) Backup current main.py
$mainPath = Join-Path $Connector "main.py"
if (-not (Test-Path -LiteralPath $mainPath)) {
    throw "Expected main.py not found at: $mainPath"
}

$backupName = "main.backup.$dateStr.$suffix.py"
$backupPath = Join-Path $Backups $backupName

Write-Host "`nBacking up current main.py -> $backupPath" -ForegroundColor Green
Move-Item -LiteralPath $mainPath -Destination $backupPath

# 7) Promote staged file to main.py
Write-Host "Promoting staged file -> main.py: $stagedPath -> $mainPath" -ForegroundColor Green
Move-Item -LiteralPath $stagedPath -Destination $mainPath

Write-Host "`nDeployment complete." -ForegroundColor Cyan
Write-Host "  Backup created: $backupName"
Write-Host "  New main.py from: $sourceLabel"
