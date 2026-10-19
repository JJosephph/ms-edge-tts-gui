$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
$files = @(
    (Join-Path $root "dist\EdgeTTSGui\EdgeTTSGui.exe"),
    (Join-Path $root "dist\EdgeTTSGui-Portable.exe"),
    (Join-Path $root "dist\EdgeTTSGui-Setup.exe")
)

$lines = foreach ($file in $files) {
    if (-not (Test-Path -LiteralPath $file)) {
        throw "Missing release artifact: $file"
    }

    $hash = (Get-FileHash -LiteralPath $file -Algorithm SHA256).Hash.ToLowerInvariant()
    $name = [System.IO.Path]::GetFileName($file)
    "$hash  $name"
}

$output = Join-Path $root "dist\SHA256SUMS.txt"
[System.IO.File]::WriteAllLines(
    $output,
    $lines,
    [System.Text.UTF8Encoding]::new($false)
)

Write-Host "Checksums written to $output"
