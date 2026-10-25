# XynLevel app

The desktop app around the levelling bot in the parent folder: a Tauri v2 window with a plain JavaScript
UI (`src/`), a Python bridge on localhost (`python/`) and a per-user NSIS installer. The bot's code isn't
copied here; the bridge loads it from the parent folder, and the release build packs it into the sidecar.

## Development

Needs Bun, a Windows MSVC Rust toolchain, WebView2 and Python 3.11 or later. From this folder:

```powershell
py -m pip install -r python/requirements.txt
bun install
bun run dev
```

## Tests

```powershell
bun test src/
py -m pytest tests
cargo check --manifest-path src-tauri/Cargo.toml
```

## Release build

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/build_release.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/build_custom_installer.ps1
```

The first builds the sidecar, the app and the NSIS installer, then scans everything shipped (including
inside the installer and the sidecar) and stops if your Windows username, computer name or anything in
`XYNLEVEL_PRIVATE_WORDS` turns up. The second wraps it in the themed installer under `dist/`. Builds are
unsigned.

## Data and privacy

Settings, redacted session logs and saved bug reports live in the app's local data folder (Tools > Open
app data). Bug reports hold a fixed list of settings, the game-area size, the run result and redacted
events; no screenshots, paths, machine names or tokens. Nothing is sent anywhere except the Discord
webhook, if you add one, which gets run counters only and is encrypted for your Windows account.

The bridge only accepts requests from the app: a random token passed over stdin, an exact localhost Host
header and no browser Origin. After-run actions only follow a timed stop, give a cancellable 30-second
countdown, and never force a shutdown.

## Updates

Not enabled. New versions are posted on the GitHub Releases page.

Fonts: see `src-tauri/resources/licenses/`.
