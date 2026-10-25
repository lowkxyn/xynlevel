# Build the sidecar and the NSIS installer, with personal paths stripped from the Rust binary,
# then refuse the result if the Windows username still appears in any shipped executable.
#   powershell -NoProfile -ExecutionPolicy Bypass -File scripts\build_release.ps1
param([string]$Python = "py")
$ErrorActionPreference = "Stop"
$appRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$env:PATH = "$env:USERPROFILE\.bun\bin;$env:PATH"

# Rust embeds source paths of every crate (panic locations). Remap them to neutral names.
$cargoHome = if ($env:CARGO_HOME) { $env:CARGO_HOME } else { Join-Path $env:USERPROFILE ".cargo" }
$rustupHome = if ($env:RUSTUP_HOME) { $env:RUSTUP_HOME } else { Join-Path $env:USERPROFILE ".rustup" }
$env:RUSTFLAGS = "--remap-path-prefix=$cargoHome=cargo --remap-path-prefix=$rustupHome=rustup " +
                 "--remap-path-prefix=$appRoot=xynlevel --remap-path-prefix=$env:USERPROFILE=home"

Push-Location $appRoot
try {
    & powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot "build_sidecar.ps1") -Python $Python
    if ($LASTEXITCODE -ne 0) { throw "Sidecar build failed" }
    bun run tauri build -- --locked
    if ($LASTEXITCODE -ne 0) { throw "Tauri build failed" }
} finally {
    Pop-Location
}

# Byte-scan the shipped executables (the installer is compressed, so scan what goes inside it).
$shipped = @(Join-Path $appRoot "src-tauri\target\release\XynLevel.exe") +
           @(Get-ChildItem (Join-Path $appRoot "src-tauri\binaries") -Filter *.exe | ForEach-Object FullName)
& $Python -I (Join-Path $PSScriptRoot "scan_binaries.py") @shipped
if ($LASTEXITCODE -ne 0) { throw "Privacy scan failed" }
# The sidecar compresses its own files and Python modules; unpack and scan those too.
Get-ChildItem (Join-Path $appRoot "src-tauri\binaries") -Filter *.exe | ForEach-Object {
    & $Python -I (Join-Path $PSScriptRoot "scan_sidecar.py") $_.FullName
    if ($LASTEXITCODE -ne 0) { throw "Privacy scan of the sidecar contents failed" }
}

# Also scan what the installer actually unpacks (it compresses, so its own bytes hide the contents).
$sevenZip = Join-Path $env:ProgramFiles "7-Zip\7z.exe"
$installer = Get-ChildItem (Join-Path $appRoot "src-tauri\target\release\bundle\nsis") -Filter *.exe | Select-Object -First 1
if (-not (Test-Path $sevenZip)) { throw "7-Zip is required to scan inside the installer" }
if (-not $installer) { throw "No installer was built" }
& $Python -I (Join-Path $PSScriptRoot "scan_binaries.py") @(Get-ChildItem (Join-Path $appRoot "web-dist") -Recurse -File | ForEach-Object FullName)
if ($LASTEXITCODE -ne 0) { throw "Privacy scan of the app's UI files failed" }
$unpacked = Join-Path $appRoot ".build\installer-scan"
Remove-Item -Recurse -Force $unpacked -ErrorAction SilentlyContinue
& $sevenZip x -y "-o$unpacked" $installer.FullName | Out-Null
if ($LASTEXITCODE -ne 0) { throw "Could not unpack the installer for scanning" }
$inside = @(Get-ChildItem $unpacked -Recurse -File | ForEach-Object FullName)
& $Python -I (Join-Path $PSScriptRoot "scan_binaries.py") @inside
if ($LASTEXITCODE -ne 0) { throw "Privacy scan of the installer contents failed" }
Get-ChildItem (Join-Path $appRoot "src-tauri\target\release\bundle\nsis") -Filter *.exe | ForEach-Object { Write-Output "Installer: $($_.FullName)" }
