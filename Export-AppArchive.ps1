param(
    [switch]$IncludeEnv = $false,
    [switch]$IncludeData = $false,
    [switch]$IncludeVenv = $false
)

Set-StrictMode -Version Latest

$root = Get-Location
$date = Get-Date -Format "yyyyMMdd"
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

<#
function Get-GitIgnorePatterns {
    $gitignore = Join-Path $root ".gitignore"

    if (!(Test-Path $gitignore)) {
        return @()
    }

    $patterns = @()

    Get-Content $gitignore | ForEach-Object {
        $line = $_.Trim()

        if ($line -and !$line.StartsWith("#")) {
            $patterns += $line
        }
    }

    return $patterns
}
#>

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

<#
function Get-ShouldExclude {
    param(
        $path,
        $patterns
    )

    foreach ($pattern in $patterns) {

        if ($path -like "*$pattern*") {
            return $true
        }
    }

    return $false
}
#>

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

<#
function Get-ExcludePatterns {

    $patterns = Get-GitIgnorePatterns

    if (!$IncludeEnv) {
        $patterns += ".env"
    }

    if (!$IncludeData) {
        $patterns += "data"
    }

    if (!$IncludeVenv) {
        $patterns += ".venv"
    }

    return $patterns
}
#>

$rev = Get-NextArchiveRev -Root $root -Date $date
$zipName = "WyrmGPT.$date.$rev.zip"
$zipPath = Join-Path $root $zipName

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

$files = Get-ChildItem -Path $root -Recurse -File

$filtered = @()

foreach ($file in $files) {

    $relative = Convert-ToArchivePath ($file.FullName.Substring($root.Path.Length))
    #$relative = $file.FullName.Substring($root.Path.Length)

    if (-not (Get-ShouldExclude $relative $excludePatterns)) {
        $filtered += $file
    }
}

$total = $filtered.Count

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

    $percent = [int](($i / $total) * 100)

    Write-Progress `
        -Activity "Creating ZIP archive" `
        -Status "$i of $total files" `
        -PercentComplete $percent

    $relativePath = Convert-ToArchivePath ($file.FullName.Substring($root.Path.Length + 1))        
    #$relativePath = $file.FullName.Substring($root.Path.Length + 1)

    if ($VerbosePreference -eq "Continue") {
        Write-Verbose "Adding $relativePath"
    }

    $entry = $zip.CreateEntry($relativePath)

    $entryStream = $entry.Open()
    $fileStream = [System.IO.File]::OpenRead($file.FullName)

    $fileStream.CopyTo($entryStream)

    $fileStream.Dispose()
    $entryStream.Dispose()
}

$zip.Dispose()

Write-Progress -Activity "Creating ZIP archive" -Completed

Write-Host ""
Write-Host "Archive created:"
Write-Host " $zipPath"
Write-Host ""