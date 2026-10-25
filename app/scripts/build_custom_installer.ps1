# Compile the themed host around an existing Tauri NSIS backend. Never install or launch.
[CmdletBinding()]
param([string]$Source, [string]$Python)
$ErrorActionPreference = 'Stop'
$AppRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$HostRoot = Join-Path $AppRoot 'installer'
$Config = Get-Content -Raw -LiteralPath (Join-Path $AppRoot 'src-tauri\tauri.conf.json') | ConvertFrom-Json
$Version = $Config.version
if ($Version -notmatch '^\d+\.\d+\.\d+$') { throw 'Version must have three numeric components.' }
if ($Config.bundle.windows.nsis.installMode -ne 'currentUser') { throw 'NSIS must use currentUser.' }
if ($Config.productName -ne 'XynLevel' -or $Config.bundle.publisher -ne 'Xyn') { throw 'Unexpected product metadata.' }
if (-not $Source) { $Source = Join-Path $AppRoot "src-tauri\target\release\bundle\nsis\XynLevel_${Version}_x64-setup.exe" }
$Source = (Resolve-Path -LiteralPath $Source).Path
if (-not $Source.StartsWith($AppRoot + '\', [StringComparison]::OrdinalIgnoreCase)) { throw 'Backend must be inside the app directory.' }
if (-not $Python) {
    $Python = if (Get-Command py -ErrorAction SilentlyContinue) { 'py' } else { 'python' }
}
$Work = Join-Path $HostRoot 'work'
$Bundle = Join-Path $Work 'bundle'
$Target = Join-Path $Work 'target'
$Dist = Join-Path $AppRoot 'dist'
$Previous = @{}
foreach ($Name in @('CARGO_HOME', 'CARGO_TARGET_DIR', 'CARGO_ENCODED_RUSTFLAGS', 'XYN_INSTALLER_BUNDLE', 'TEMP', 'TMP')) {
    $Previous[$Name] = [Environment]::GetEnvironmentVariable($Name, 'Process')
}
$OriginalCargoHome = if ($env:CARGO_HOME) { $env:CARGO_HOME } else { Join-Path $env:USERPROFILE '.cargo' }
$RustupHome = if ($env:RUSTUP_HOME) { $env:RUSTUP_HOME } else { Join-Path $env:USERPROFILE '.rustup' }
try {
    # Keep Cargo's writable cache, WebView/build temp files and all outputs in this app.
    $env:CARGO_HOME = Join-Path $Work 'cargo-home'
    $env:CARGO_TARGET_DIR = $Target
    $env:XYN_INSTALLER_BUNDLE = $Bundle
    $env:TEMP = Join-Path $Work 'tmp'
    $env:TMP = $env:TEMP
    New-Item -ItemType Directory -Force -Path $env:CARGO_HOME, $env:TEMP, $Bundle | Out-Null
    $Flags = @(
        "--remap-path-prefix=$env:USERPROFILE=/.build-user"
        "--remap-path-prefix=$OriginalCargoHome=/cargo"
        "--remap-path-prefix=$env:CARGO_HOME=/cargo"
        "--remap-path-prefix=$RustupHome=/rustup"
        "--remap-path-prefix=$AppRoot=/xynlevel"
    )
    # Encoded flags preserve paths containing spaces. Do not inherit flags with private literals.
    $env:CARGO_ENCODED_RUSTFLAGS = $Flags -join [char]31
    & $Python -I (Join-Path $HostRoot 'prepare.py') $Bundle --source $Source --version $Version
    if ($LASTEXITCODE -ne 0) { throw 'Embedded resource preparation failed.' }
    & cargo build --locked --release --target x86_64-pc-windows-msvc --manifest-path (Join-Path $HostRoot 'Cargo.toml')
    if ($LASTEXITCODE -ne 0) { throw 'Cargo build failed. Crates may require network access; check the preceding error.' }
    $Built = Join-Path $Target 'x86_64-pc-windows-msvc\release\xyn-installer.exe'
    # Scan before creating the release file, preserving any previous output on a hit.
    & $Python -I (Join-Path $PSScriptRoot 'scan_binaries.py') $Built
    if ($LASTEXITCODE -ne 0) { throw 'Host privacy scan failed; output was not copied to dist.' }
    # It embeds the prepared UI and the NSIS installer compressed, so scan those before packing.
    & $Python -I (Join-Path $PSScriptRoot 'scan_binaries.py') @(Get-ChildItem -LiteralPath $Bundle -Recurse -File | ForEach-Object FullName)
    if ($LASTEXITCODE -ne 0) { throw 'Privacy scan of the embedded installer files failed.' }
    $SevenZip = Join-Path $env:ProgramFiles '7-Zip\7z.exe'
    if (-not (Test-Path $SevenZip)) { throw '7-Zip is required to scan inside the NSIS installer.' }
    $Unpacked = Join-Path $Work 'nsis-scan'
    Remove-Item -Recurse -Force -LiteralPath $Unpacked -ErrorAction SilentlyContinue
    & $SevenZip x -y "-o$Unpacked" $Source | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'Could not unpack the NSIS installer for scanning.' }
    & $Python -I (Join-Path $PSScriptRoot 'scan_binaries.py') @(Get-ChildItem -LiteralPath $Unpacked -Recurse -File | ForEach-Object FullName)
    if ($LASTEXITCODE -ne 0) { throw 'Privacy scan of the NSIS installer contents failed.' }
    foreach ($Sidecar in Get-ChildItem -LiteralPath $Unpacked -Recurse -Filter 'XynLevel-core*.exe') {
        & $Python -I (Join-Path $PSScriptRoot 'scan_sidecar.py') $Sidecar.FullName
        if ($LASTEXITCODE -ne 0) { throw 'Privacy scan of the sidecar contents failed.' }
    }
    New-Item -ItemType Directory -Force -Path $Dist | Out-Null
    $Output = Join-Path $Dist "XynLevel_${Version}_setup.exe"
    Copy-Item -LiteralPath $Built -Destination $Output
    if ((Get-FileHash -LiteralPath $Output).Hash -ne (Get-FileHash -LiteralPath $Built).Hash) { throw 'Output copy verification failed.' }
    Write-Host "Built and privacy-scanned: XynLevel_${Version}_setup.exe"
} finally {
    foreach ($Name in $Previous.Keys) { [Environment]::SetEnvironmentVariable($Name, $Previous[$Name], 'Process') }
}
