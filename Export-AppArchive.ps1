param(
    [switch]$IncludeEnv = $false,
    [switch]$IncludeData = $false,
    [switch]$IncludeVenv = $false
)

Set-StrictMode -Version Latest

$root = Get-Location
$date = Get-Date -Format "yyyyMMdd"
$zipName = "WyrmGPT.$date.d.zip"
$zipPath = Join-Path $root $zipName

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

    $relative = $file.FullName.Substring($root.Path.Length)

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

    $relativePath = $file.FullName.Substring($root.Path.Length + 1)

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