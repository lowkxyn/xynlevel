param([string]$Python = "python")
$ErrorActionPreference = "Stop"
$appRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$coreRoot = Split-Path -Parent $appRoot
$coreFiles = @("gc_train.py", "gc_bot.py", "gc_vision.py", "gc_gravity.py", "gc_menu.py", "gc_read.py", "gc_aim.py", "window.py", "gc_stats.py") | ForEach-Object { Join-Path $coreRoot $_ }
$assetRoot = Join-Path $coreRoot "assets"
$coreFiles += @(Get-ChildItem -LiteralPath $assetRoot -File -Recurse | ForEach-Object FullName)
function Get-ContentHash([string]$Path) {
    $stream = [System.IO.File]::OpenRead($Path)
    $sha = [System.Security.Cryptography.SHA256]::Create()
    try { return [System.BitConverter]::ToString($sha.ComputeHash($stream)) } finally { $stream.Dispose(); $sha.Dispose() }
}
$before = @{}
foreach ($file in $coreFiles) { $before[$file] = Get-ContentHash $file }
$priorBytecode = $env:PYTHONDONTWRITEBYTECODE
$env:PYTHONDONTWRITEBYTECODE = "1"
try {
    & $Python -B -m PyInstaller --noconfirm --clean --workpath (Join-Path $appRoot ".build\pyinstaller") --distpath (Join-Path $appRoot "python\dist") (Join-Path $appRoot "python\XynLevel-core.spec")
    if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed with exit code $LASTEXITCODE" }
} finally {
    $env:PYTHONDONTWRITEBYTECODE = $priorBytecode
}
foreach ($file in $coreFiles) {
    if ((Get-ContentHash $file) -ne $before[$file]) {
        throw "The external core changed during packaging. Rebuild after its writer finishes."
    }
}
$hostLine = & rustc -vV | Select-String '^host: (.+)$'
if ($LASTEXITCODE -ne 0 -or -not $hostLine) { throw "Cannot identify the Rust host target" }
$triple = $hostLine.Matches[0].Groups[1].Value
if ($triple -notmatch '^[a-z0-9_]+-pc-windows-msvc$') { throw "This sidecar build requires a Windows MSVC Rust host" }
$binDir = Join-Path $appRoot "src-tauri\binaries"
New-Item -ItemType Directory -Force -Path $binDir | Out-Null
$destination = Join-Path $binDir "XynLevel-core-$triple.exe"
Copy-Item -LiteralPath (Join-Path $appRoot "python\dist\XynLevel-core.exe") -Destination $destination -Force
Write-Output "Sidecar built: src-tauri/binaries/XynLevel-core-$triple.exe"
