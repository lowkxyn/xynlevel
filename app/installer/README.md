# XynLevel installer

A small Rust window (Tao + WebView) that wraps the Tauri NSIS installer in XynLevel's own setup screens:
welcome, options, progress, done and error. The page is `index.html`, `style.css` and `ui.js`; names and
registry keys come from `app.json`.

## What it does

When you click Install it unpacks the NSIS installer into a private temp folder and runs it silently:

```text
xyn-payload.exe /S [/NS] /D=<install folder>
```

`/NS` skips the Desktop and Start menu shortcuts. It installs for the current Windows user only (no admin),
defaulting to `%LOCALAPPDATA%\XynLevel`. An update keeps the existing install folder. It reports success
only once `XynLevel.exe`, `uninstall.exe` and the app's registry entries are in place. It never runs an
uninstaller, and it needs the WebView2 runtime that Windows 10 and 11 already have.

## Build

Build the app first, then wrap it (from the `app` folder):

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\build_release.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\build_custom_installer.ps1
```

The result is `dist/XynLevel_<version>_setup.exe`. It's only written after the privacy scans of the
wrapper, its embedded files, the unpacked NSIS installer and the bot pass. Build files go in
`installer/work/`.

## Preview

`py -I installer/prepare.py installer/work/preview --source <nsis setup.exe> --version <version>` writes
`preview.html`, which runs the screens in a browser without installing anything. Add `#update` or
`#error` to the address to see those screens. `test_prepare.py` checks the preparation step.
