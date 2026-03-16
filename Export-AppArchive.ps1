param(
    [switch]$IncludeEnv = $false,
    [switch]$IncludeData = $false,
    [switch]$IncludeVenv = $false
)

$ProgressPreference = 'Continue'
if ($PSVersionTable.PSVersion.Major -ge 7) {
    $PSStyle.Progress.View = 'Classic'
}

Set-StrictMode -Version Latest

$root = Get-Location
$date = Get-Date -Format "yyyyMMdd"

function Get-NextArchiveRev {
    param(
        [string]$Root,
        [string]$Date
    )

    $existing = Get-ChildItem -Path $Root -Filter "WyrmGPT.$Date.*.zip" -File -ErrorAction SilentlyContinue

    # Convert rev like a, b, z, aa, ab ... into an integer (1-indexed base-26)
    function RevToInt([string]$rev) {
        $n = 0
        foreach ($ch in $rev.ToCharArray()) {
            if ($ch -lt 'a' -or $ch -gt 'z') { return -1 }
            $n = ($n * 26) + ([int][char]$ch - [int][char]'a' + 1)
        }
        return $n
    }

    function IntToRev([int]$n) {
        $s = ""
        while ($n -gt 0) {
            $n--
            $s = [char]([int][char]'a' + ($n % 26)) + $s
            $n = [math]::Floor($n / 26)
        }
        return $s
    }

    $max = 0
    foreach ($f in $existing) {
        if ($f.Name -match "^WyrmGPT\.$Date\.([a-z]+)\.zip$") {
            $v = RevToInt $matches[1]
            if ($v -gt $max) { $max = $v }
        }
    }

    return (IntToRev ($max + 1))
}

function Convert-ToArchivePath {
    param([string]$Path)

    $p = $Path -replace '\\', '/'
    $p = $p.TrimStart('/')
    return $p
}

function Get-GitIgnorePatterns {
    $gitignore = Join-Path $root ".gitignore"

    if (!(Test-Path $gitignore)) {
        return @()
    }

    $patterns = @()

    Get-Content $gitignore | ForEach-Object {
        $line = $_.Trim()

        if (-not $line -or $line.StartsWith("#")) {
            return
        }

        $negate = $false
        if ($line.StartsWith("!")) {
            $negate = $true
            $line = $line.Substring(1).Trim()
        }

        $directoryOnly = $line.EndsWith("/")
        if ($directoryOnly) {
            $line = $line.TrimEnd("/")
        }

        $patterns += [pscustomobject]@{
            Pattern       = (Convert-ToArchivePath $line)
            Negate        = $negate
            DirectoryOnly = $directoryOnly
        }
    }

    return $patterns
}

function Test-ArchiveRuleMatch {
    param(
        [string]$Path,
        $Rule
    )

    $path = Convert-ToArchivePath $Path
    $name = Split-Path $path -Leaf
    $parts = $path -split '/'

    $pattern = $Rule.Pattern

    if ($Rule.DirectoryOnly) {
        return ($parts -contains $pattern)
    }

    if ($pattern.Contains("/")) {
        return ($path -eq $pattern) -or ($path -like "$pattern/*")
    }

    if ($pattern.Contains("*") -or $pattern.Contains("?")) {
        return ($name -like $pattern) -or ($path -like $pattern)
    }

    return ($name -eq $pattern)
}

function Get-ShouldExclude {
    param(
        [string]$Path,
        $patterns
    )

    $path = Convert-ToArchivePath $Path
    $exclude = $false

    foreach ($rule in $patterns) {
        if (Test-ArchiveRuleMatch -Path $path -Rule $rule) {
            $exclude = -not $rule.Negate
        }
    }

    return $exclude
}

function Get-ExcludePatterns {
    $patterns = Get-GitIgnorePatterns

    if (!$IncludeEnv) {
        $patterns += [pscustomobject]@{
            Pattern       = ".env"
            Negate        = $false
            DirectoryOnly = $false
        }
    }

    if (!$IncludeData) {
        $patterns += [pscustomobject]@{
            Pattern       = "data"
            Negate        = $false
            DirectoryOnly = $true
        }
    }

    if (!$IncludeVenv) {
        $patterns += [pscustomobject]@{
            Pattern       = ".venv"
            Negate        = $false
            DirectoryOnly = $true
        }
    }

    return $patterns
}

function Get-ProgressBarText {
    param(
        [int]$Percent,
        [int]$Width = 28
    )

    $p = [Math]::Max(0, [Math]::Min(100, $Percent))
    $filled = [Math]::Floor(($p / 100) * $Width)
    $empty = $Width - $filled

    return ("[" + ("#" * $filled) + ("-" * $empty) + "]")
}

function Get-PrunableDirectoryNames {
    param($Patterns)

    $set = [System.Collections.Generic.HashSet[string]]::new([System.StringComparer]::OrdinalIgnoreCase)

    foreach ($rule in $Patterns) {
        if (-not $rule.DirectoryOnly) { continue }
        if ($rule.Negate) { continue }

        $pattern = [string]$rule.Pattern
        if ([string]::IsNullOrWhiteSpace($pattern)) { continue }
        if ($pattern.Contains("*") -or $pattern.Contains("?")) { continue }
        if ($pattern.Contains("/")) { continue }

        [void]$set.Add($pattern)
    }

    foreach ($name in @(
        ".git",
        "_bak",
        "node_modules",
        "__pycache__",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
        "dist",
        "build"
    )) {
        [void]$set.Add($name)
    }

    return $set
}

function Get-FilesForArchive {
    param(
        $Root,
        $Patterns
    )

    $rootDir = Get-Item -LiteralPath $Root.Path
    $prunableDirNames = Get-PrunableDirectoryNames $Patterns
    $filtered = New-Object System.Collections.Generic.List[System.IO.FileInfo]
    $stack = New-Object System.Collections.Generic.Stack[System.IO.DirectoryInfo]

    $stack.Push($rootDir)

    $dirsScanned = 0
    $dirsQueued = 1

    while ($stack.Count -gt 0) {
        $dir = $stack.Pop()
        $dirsScanned++

        $knownDirs = [Math]::Max(($dirsScanned + $stack.Count), 1)

        Show-ArchiveProgress `
            -Id 1 `
            -Activity "Scanning files" `
            -Current $dirsScanned `
            -Total $knownDirs `
            -Status "$dirsScanned dirs scanned, $($filtered.Count) files kept" `
            -Force:($dirsScanned -eq 1)

        foreach ($subdir in @(Get-ChildItem -LiteralPath $dir.FullName -Directory -Force -ErrorAction SilentlyContinue)) {
            $relativeDir = Convert-ToArchivePath ($subdir.FullName.Substring($Root.Path.Length + 1))

            if ($prunableDirNames.Contains($subdir.Name)) {
                continue
            }

            if (Get-ShouldExclude $relativeDir $Patterns) {
                continue
            }

            $stack.Push($subdir)
            $dirsQueued++
        }

        foreach ($file in @(Get-ChildItem -LiteralPath $dir.FullName -File -Force -ErrorAction SilentlyContinue)) {
            $relativeFile = Convert-ToArchivePath ($file.FullName.Substring($Root.Path.Length + 1))

            if (-not (Get-ShouldExclude $relativeFile $Patterns)) {
                [void]$filtered.Add($file)
            }
        }
    }

    Show-ArchiveProgress -Id 1 -Activity "Scanning files" -Completed
    return $filtered
}

function Show-ArchiveProgress {
    param(
        [int]$Id,
        [string]$Activity,
        [int]$Current,
        [int]$Total,
        [string]$Status,
        [switch]$Completed,
        [switch]$Force
    )

    if ($Completed) {
        Write-Progress -Id $Id -Activity $Activity -Completed
        if ($script:ProgressLineActive) {
            Write-Host ""
            $script:ProgressLineActive = $false
        }
        return
    }

    if ($Total -le 0) {
        $percent = 0
    } else {
        $percent = [int][Math]::Floor(($Current / $Total) * 100)
    }

    $nowMs = $script:ProgressStopwatch.ElapsedMilliseconds
    if (-not $Force -and ($nowMs - $script:LastProgressRenderMs) -lt 80 -and $Current -lt $Total) {
        return
    }
    $script:LastProgressRenderMs = $nowMs
    <#
    $now = [Environment]::TickCount64
    if (-not $Force -and ($now - $script:LastProgressRender) -lt 80 -and $Current -lt $Total) {
        return
    }
    $script:LastProgressRender = $now
    #>

    Write-Progress `
        -Id $Id `
        -Activity $Activity `
        -Status $Status `
        -PercentComplete $percent

    $bar = Get-ProgressBarText -Percent $percent
    $line = "`r$Activity $bar $percent%  $Status"

    Write-Host -NoNewline $line
    $script:ProgressLineActive = $true
}



$rev = Get-NextArchiveRev -Root $root -Date $date
$zipName = "WyrmGPT.$date.$rev.zip"
$zipPath = Join-Path $root $zipName

#$script:LastProgressRender = 0
$script:ProgressStopwatch = [System.Diagnostics.Stopwatch]::StartNew()
$script:LastProgressRenderMs = 0
$script:ProgressLineActive = $false

$excludePatterns = Get-ExcludePatterns

Write-Host ""
Write-Host "Preparing archive..."
Write-Host ""

Write-Host "Root: $root"
Write-Host "Zip : $zipPath"
Write-Host ""

Write-Host "Exclude patterns:"
$excludePatterns | ForEach-Object { Write-Host " - $_" }

Write-Host ""

$filtered = Get-FilesForArchive -Root $root -Patterns $excludePatterns

$total = $filtered.Count
if ($total -le 0) {
    throw "No files matched the archive rules."
}

Write-Host "Files to archive: $total"
Write-Host ""

if (Test-Path $zipPath) {
    Remove-Item $zipPath -Force
}

Add-Type -AssemblyName System.IO.Compression.FileSystem

$zip = [System.IO.Compression.ZipFile]::Open($zipPath, 'Create')

$i = 0

foreach ($file in $filtered) {
    $i++

    $relativePath = Convert-ToArchivePath ($file.FullName.Substring($root.Path.Length + 1))

    Show-ArchiveProgress `
        -Id 2 `
        -Activity "Creating ZIP archive" `
        -Current $i `
        -Total $total `
        -Status "$i of $total files : $relativePath" `
        -Force:($i -eq 1 -or $i -eq $total)

    if ($VerbosePreference -eq "Continue") {
        Write-Verbose "Adding $relativePath"
    }

    $entry = $zip.CreateEntry($relativePath)

    $entryStream = $entry.Open()
    $fileStream = [System.IO.File]::OpenRead($file.FullName)

    try {
        $fileStream.CopyTo($entryStream)
    }
    finally {
        $fileStream.Dispose()
        $entryStream.Dispose()
    }
}

$zip.Dispose()

Show-ArchiveProgress -Id 2 -Activity "Creating ZIP archive" -Completed

Write-Host ""
Write-Host "Archive created:"
Write-Host " $zipPath"
Write-Host ""