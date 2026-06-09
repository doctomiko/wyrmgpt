<# 
Deploy_Callie.ps1
- Creates a dated zip backup of the current project (excluding .env)
- Deploys the newest downloaded artifacts (by canonical module name) from the Downloads folder
- Archives all other matching "incoming" files to Backups\Incoming

Assumptions:
- You generate/download updated files into $DownloadsDir (default below)
- Canonical filenames live in $ProjectDir (default below)
- Canonical file set is discovered from the project directory (so adding new modules is easy)
#>

[CmdletBinding()]
param(
    [string]$ProjectDir = "M:\RunPortable\callie-connector",
    [string]$DownloadsDir = "M:\Tom\OneDrive - LiquidHg\Downloads",
    [string]$BackupsDir = "M:\RunPortable\callie-connector\Backups"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Write-Info([string]$msg) { Write-Host $msg -ForegroundColor Cyan }
function Write-Warn([string]$msg) { Write-Host $msg -ForegroundColor Yellow }
function Write-Err([string]$msg)  { Write-Host $msg -ForegroundColor Red }

function Ensure-Dir([string]$Path) {
    if (-not (Test-Path -LiteralPath $Path)) {
        New-Item -ItemType Directory -Path $Path | Out-Null
    }
}

function Get-DateString() {
    return (Get-Date).ToString("yyyy-MM-dd")
}

function Get-NextZipSuffix([string]$Dir, [string]$DateString) {
    # callie.backup.YYYY-MM-DD.xx.zip where xx is 00-99
    $pattern = "callie.backup.$DateString.*.zip"
    $existing = @(Get-ChildItem -LiteralPath $Dir -Filter $pattern -ErrorAction SilentlyContinue)
    if ($existing.Count -eq 0) { return "00" }

    $used = New-Object System.Collections.Generic.HashSet[int]
    foreach ($f in $existing) {
        $m = [regex]::Match($f.BaseName, "\.(\d{2})$")
        if ($m.Success) { [void]$used.Add([int]$m.Groups[1].Value) }
    }

    for ($i=0; $i -le 99; $i++) {
        if (-not $used.Contains($i)) { return ("{0:D2}" -f $i) }
    }
    throw "Too many backups for $DateString (00-99 already used). Clean out $Dir."
}

function Get-CanonicalFiles([string]$Dir) {
    # Maintainable: canonical list is "whatever exists" in the project.
    # Include: *.py, *.ps1, *.txt, .env.example (explicit)
    # Exclude: .env and anything under Backups
    $items = @()

    $items += Get-ChildItem -LiteralPath $Dir -File -Filter "*.py"  -ErrorAction SilentlyContinue
    $items += Get-ChildItem -LiteralPath $Dir -File -Filter "*.ps1" -ErrorAction SilentlyContinue
    $items += Get-ChildItem -LiteralPath $Dir -File -Filter "*.txt" -ErrorAction SilentlyContinue

    $envExample = Join-Path $Dir ".env.example"
    if (Test-Path -LiteralPath $envExample) {
        $items += Get-Item -LiteralPath $envExample
    }

    $items = $items | Where-Object { $_.FullName -notmatch "\\Backups\\" }
    $items = $items | Where-Object { $_.Name -ne ".env" }
    return $items | Sort-Object FullName -Unique
}

function Make-BackupZip([string]$ProjectDir, [string]$BackupsDir) {
    Ensure-Dir $BackupsDir
    $dateS  = Get-DateString
    $suffix = Get-NextZipSuffix -Dir $BackupsDir -DateString $dateS
    $zipName = "callie.backup.$dateS.$suffix.zip"
    $zipPath = Join-Path $BackupsDir $zipName

    $files = Get-CanonicalFiles -Dir $ProjectDir
    if ($files.Count -eq 0) { throw "No canonical files found in $ProjectDir" }

    $paths = $files | ForEach-Object { $_.FullName }

    Write-Info "Backup: $zipPath"
    Compress-Archive -LiteralPath $paths -DestinationPath $zipPath -Force
    return $zipPath
}

function Get-DeployPlan([string]$ProjectDir, [string]$DownloadsDir) {
    $canonical = Get-CanonicalFiles -Dir $ProjectDir

    $plan = @()
    foreach ($c in $canonical) {
        $name = $c.Name
        if ($name -ieq ".env") { continue }

        $stem = [System.IO.Path]::GetFileNameWithoutExtension($name)
        $ext  = $c.Extension
        if ($ext -eq ".zip") { continue }

        $pattern = "$stem*${ext}"
        $candidates = @(Get-ChildItem -LiteralPath $DownloadsDir -File -Filter $pattern -ErrorAction SilentlyContinue |
                        Sort-Object LastWriteTime -Descending)

        if ($candidates.Count -gt 0) {
            $plan += [pscustomobject]@{
                CanonicalPath = $c.FullName
                CanonicalName = $name
                Stem          = $stem
                Ext           = $ext
                SourcePath    = $candidates[0].FullName
                SourceName    = $candidates[0].Name
                SourceTime    = $candidates[0].LastWriteTime
            }
        }
    }
    return $plan
}

function Archive-IncomingRemainders([string]$DownloadsDir, [string]$IncomingArchiveDir, [object[]]$DeployPlan) {
    Ensure-Dir $IncomingArchiveDir

    $plannedSources = New-Object System.Collections.Generic.HashSet[string]
    foreach ($p in $DeployPlan) { [void]$plannedSources.Add($p.SourcePath.ToLowerInvariant()) }

    $stems = $DeployPlan | Select-Object -ExpandProperty Stem -Unique
    $exts  = $DeployPlan | Select-Object -ExpandProperty Ext -Unique

    foreach ($stem in $stems) {
        foreach ($ext in $exts) {
            $pattern = "$stem*${ext}"
            $matches = @(Get-ChildItem -LiteralPath $DownloadsDir -File -Filter $pattern -ErrorAction SilentlyContinue)
            foreach ($m in $matches) {
                if ($plannedSources.Contains($m.FullName.ToLowerInvariant())) { continue }
                $dest = Join-Path $IncomingArchiveDir $m.Name
                Write-Info "Archive incoming extra: $($m.Name) -> $dest"
                Move-Item -LiteralPath $m.FullName -Destination $dest -Force
            }
        }
    }
}

function Deploy-Files([object[]]$DeployPlan) {
    foreach ($p in $DeployPlan) {
        $dest = $p.CanonicalPath
        Write-Info "Deploy: $($p.SourceName) -> $($p.CanonicalName)"
        Copy-Item -LiteralPath $p.SourcePath -Destination $dest -Force
    }
}

# -----------------------
# Main
# -----------------------
if (-not (Test-Path -LiteralPath $ProjectDir))  { throw "ProjectDir not found: $ProjectDir" }
if (-not (Test-Path -LiteralPath $DownloadsDir)) { throw "DownloadsDir not found: $DownloadsDir" }

Ensure-Dir $BackupsDir
$incomingDir = Join-Path $BackupsDir ("Incoming\" + (Get-Date).ToString("yyyy-MM-dd_HHmmss"))
Ensure-Dir $incomingDir

$zip = Make-BackupZip -ProjectDir $ProjectDir -BackupsDir $BackupsDir

$plan = Get-DeployPlan -ProjectDir $ProjectDir -DownloadsDir $DownloadsDir
if ($plan.Count -eq 0) {
    Write-Warn "No deployable files found in Downloads matching current canonical module names. Backup still created."
    exit 0
}

Write-Info "`nDeploy plan (latest per canonical stem):"
$plan | Sort-Object CanonicalName | ForEach-Object {
    Write-Host ("  {0} <= {1} ({2})" -f $_.CanonicalName, $_.SourceName, $_.SourceTime)
}

Archive-IncomingRemainders -DownloadsDir $DownloadsDir -IncomingArchiveDir $incomingDir -DeployPlan $plan
Deploy-Files -DeployPlan $plan

Write-Info "`nDone."
Write-Info "Backup zip: $zip"
Write-Info "Archived extra incoming: $incomingDir"
