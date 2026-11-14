$ErrorActionPreference = "Stop"
Add-Type -AssemblyName System.Net.Http

$root = Split-Path -Parent $PSScriptRoot
$modelId = "kokoro-v1.1-zh"
$modelRoot = "kokoro-int8-multi-lang-v1_1"
$url = "https://github.com/k2-fsa/sherpa-onnx/releases/download/tts-models/kokoro-int8-multi-lang-v1_1.tar.bz2"
$expectedSize = 147052523
$expectedSha256 = "259c9c8bc906d6078e4e0570421885dabb68b539c2f970fcbb890a58eeaf3e9c"
$cacheDir = Join-Path $root "build-assets"
$archive = Join-Path $cacheDir "kokoro-int8-multi-lang-v1_1.tar.bz2"
$modelParent = Join-Path $root "vendor\models"
$target = Join-Path $modelParent $modelId
$required = @(
    "$modelRoot/model.int8.onnx",
    "$modelRoot/voices.bin",
    "$modelRoot/tokens.txt",
    "$modelRoot/lexicon-us-en.txt",
    "$modelRoot/lexicon-zh.txt",
    "$modelRoot/phone-zh.fst",
    "$modelRoot/date-zh.fst",
    "$modelRoot/number-zh.fst",
    "$modelRoot/LICENSE"
)

function Test-ModelFiles([string]$directory) {
    foreach ($relative in $required) {
        if (-not (Test-Path -LiteralPath (Join-Path $directory $relative) -PathType Leaf)) {
            return $false
        }
    }
    return $true
}

function Get-Sha256([string]$path) {
    $stream = [System.IO.File]::OpenRead($path)
    $sha = [System.Security.Cryptography.SHA256]::Create()
    try {
        $bytes = $sha.ComputeHash($stream)
        return [System.BitConverter]::ToString($bytes).Replace("-", "").ToLowerInvariant()
    }
    finally {
        $sha.Dispose()
        $stream.Dispose()
    }
}

if (Test-ModelFiles $target) {
    Write-Host "Bundled voice model is ready: $target"
    exit 0
}

New-Item -ItemType Directory -Force -Path $cacheDir, $modelParent | Out-Null
$validArchive = $false
if (Test-Path -LiteralPath $archive -PathType Leaf) {
    $actualSize = (Get-Item -LiteralPath $archive).Length
    if ($actualSize -eq $expectedSize -and (Get-Sha256 $archive) -eq $expectedSha256) {
        $validArchive = $true
    }
    else {
        Remove-Item -LiteralPath $archive -Force
    }
}

if (-not $validArchive) {
    Write-Host "Downloading Kokoro Chinese voice model (about 140 MB)..."
    $partial = "$archive.partial"
    if (Test-Path -LiteralPath $partial) {
        Remove-Item -LiteralPath $partial -Force
    }

    $client = [System.Net.Http.HttpClient]::new()
    $client.Timeout = [TimeSpan]::FromMinutes(30)
    try {
        $request = [System.Net.Http.HttpRequestMessage]::new(
            [System.Net.Http.HttpMethod]::Get,
            $url
        )
        $request.Headers.UserAgent.ParseAdd("EdgeTTSGui-Build/1.0")
        $response = $client.SendAsync(
            $request,
            [System.Net.Http.HttpCompletionOption]::ResponseHeadersRead
        ).GetAwaiter().GetResult()
        try {
            if (-not $response.IsSuccessStatusCode) {
                throw "Voice model download failed: HTTP $([int]$response.StatusCode)"
            }
            $total = $response.Content.Headers.ContentLength
            if ($total -and $total -ne $expectedSize) {
                throw "Voice model download has an unexpected size: $total bytes"
            }

            $input = $response.Content.ReadAsStreamAsync().GetAwaiter().GetResult()
            $output = [System.IO.File]::Create($partial)
            try {
                $buffer = New-Object byte[] (1024 * 1024)
                $received = 0
                $lastReport = 0
                while (($read = $input.Read($buffer, 0, $buffer.Length)) -gt 0) {
                    $output.Write($buffer, 0, $read)
                    $received += $read
                    $percent = [math]::Floor($received * 100 / $expectedSize)
                    if ($percent -ge $lastReport + 10) {
                        Write-Host "  $percent%"
                        $lastReport = $percent
                    }
                }
            }
            finally {
                $output.Dispose()
                $input.Dispose()
            }
        }
        finally {
            $response.Dispose()
        }
    }
    finally {
        $client.Dispose()
    }

    if ((Get-Item -LiteralPath $partial).Length -ne $expectedSize) {
        throw "Voice model download is incomplete."
    }
    if ((Get-Sha256 $partial) -ne $expectedSha256) {
        throw "Voice model SHA-256 verification failed."
    }
    Move-Item -LiteralPath $partial -Destination $archive -Force
}

$staging = Join-Path $modelParent ".$modelId.extracting"
if (Test-Path -LiteralPath $staging) {
    Remove-Item -LiteralPath $staging -Recurse -Force
}
New-Item -ItemType Directory -Force -Path $staging | Out-Null
try {
    # Windows' bsdtar delegates bzip2 to an external helper that is not
    # present on every build host.  Python's tarfile already ships with the
    # release toolchain and handles this archive natively.
    $python = Join-Path $root ".venv\Scripts\python.exe"
    if (-not (Test-Path -LiteralPath $python)) {
        $python = (Get-Command python -ErrorAction Stop).Source
    }
    $extractScript = @'
import pathlib
import sys
import tarfile

archive = pathlib.Path(sys.argv[1])
destination = pathlib.Path(sys.argv[2]).resolve()
with tarfile.open(archive, "r:bz2") as handle:
    for entry in handle.getmembers():
        target = (destination / entry.name).resolve()
        if destination != target and destination not in target.parents:
            raise SystemExit("unsafe archive path")
        if entry.issym() or entry.islnk() or entry.isdev():
            raise SystemExit("unsafe archive link")
        if entry.isdir():
            target.mkdir(parents=True, exist_ok=True)
            continue
        if not entry.isfile():
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        source = handle.extractfile(entry)
        if source is None:
            raise SystemExit("unreadable archive member")
        with source, open(target, "wb") as output:
            while True:
                chunk = source.read(1024 * 1024)
                if not chunk:
                    break
                output.write(chunk)
'@
    $extractPath = Join-Path $cacheDir "extract_model.py"
    [System.IO.File]::WriteAllText(
        $extractPath,
        $extractScript,
        [System.Text.UTF8Encoding]::new($false)
    )
    & $python $extractPath $archive $staging
    if ($LASTEXITCODE -ne 0) {
        throw "Voice model archive extraction failed."
    }
    if (-not (Test-ModelFiles $staging)) {
        throw "Voice model archive is missing required files."
    }

    # Match the runtime installer: drop optional dictionaries and development
    # samples that are not used by the Kokoro configuration.
    $extractedRoot = Join-Path $staging $modelRoot
    foreach ($extra in @("espeak-ng-data", "dict", "lexicon-gb-en.txt", "README.md")) {
        $path = Join-Path $extractedRoot $extra
        if (Test-Path -LiteralPath $path) {
            Remove-Item -LiteralPath $path -Recurse -Force
        }
    }

    if (Test-Path -LiteralPath $target) {
        Remove-Item -LiteralPath $target -Recurse -Force
    }
    Move-Item -LiteralPath $staging -Destination $target
}
finally {
    if (Test-Path -LiteralPath $staging) {
        Remove-Item -LiteralPath $staging -Recurse -Force
    }
}

if (-not (Test-ModelFiles $target)) {
    throw "Bundled voice model preparation failed."
}
Write-Host "Bundled voice model prepared: $target"
