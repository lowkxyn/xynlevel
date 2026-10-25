"""Prepare the embedded UI and existing Tauri backend; never execute the backend."""
import argparse
import base64
import hashlib
import html
import json
from pathlib import Path
import re
import shutil

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent


def check_backend(source: Path, version: str) -> dict:
    """Fail closed if the generated template no longer matches this adapter."""
    script = ROOT / "src-tauri/target/release/nsis/x64/installer.nsi"
    text = script.read_text(encoding="utf-8-sig")
    required = {
        "PRODUCTNAME": "XynLevel", "MAINBINARYNAME": "XynLevel",
        "MANUFACTURER": "Xyn", "INSTALLMODE": "currentUser",
        "BUNDLEID": "com.xynlevel.app", "VERSION": version,
    }
    for key, value in required.items():
        if f'!define {key} "{value}"' not in text:
            raise ValueError(f"Unexpected Tauri NSIS definition: {key}")
    for contract in [
        '${GetOptions} $CMDLINE "/NS" $NoShortcutMode',
        'WriteUninstaller "$INSTDIR\\uninstall.exe"',
        'WriteRegStr SHCTX "${MANUPRODUCTKEY}" "" $INSTDIR',
        '!define UNINSTKEY "Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\${PRODUCTNAME}"',
        '!define MANUPRODUCTKEY "${MANUKEY}\\${PRODUCTNAME}"',
        'WriteRegStr SHCTX "${UNINSTKEY}" "InstallLocation" "$\\"$INSTDIR$\\""',
    ]:
        if contract not in text:
            raise ValueError("Tauri NSIS contract changed; review the generated template")
    if "SetRegView 64" not in script.with_name("utils.nsh").read_text(encoding="utf-8-sig"):
        raise ValueError("Expected Tauri x64 registry context")
    if source.name != f"XynLevel_{version}_x64-setup.exe":
        raise ValueError("Backend filename does not match the app version")
    if not source.is_file() or source.read_bytes()[:2] != b"MZ":
        raise ValueError("Expected an existing Windows Tauri setup executable")
    with source.open("rb") as backend:
        digest = hashlib.file_digest(backend, "sha256").hexdigest()
    return {"backend": source.name, "version": version, "sha256": digest}


def render_ui(version: str) -> str:
    app = json.loads((HERE / "app.json").read_text(encoding="utf-8"))
    app["version"] = version
    css = (HERE / "style.css").read_text(encoding="utf-8")
    logo = base64.b64encode((HERE / app["logo"]).read_bytes()).decode("ascii")
    css = css.replace("__LOGO__", "data:image/png;base64," + logo)
    # Just the X and L, so the installing shine sweeps over the letters and not the whole tile.
    letters = base64.b64encode((HERE / app["letters"]).read_bytes()).decode("ascii")
    css = css.replace("__LETTERS__", "data:image/png;base64," + letters)
    fonts = (ROOT / "src/assets/fonts.css").read_text(encoding="utf-8")
    def embed_font(match):
        raw = (ROOT / "src/assets" / match[1]).read_bytes()
        return "url('data:font/woff2;base64," + base64.b64encode(raw).decode("ascii") + "')"
    css = re.sub(r"url\('([^']+)'\)", embed_font, fonts) + "\n" + css
    page = (HERE / "index.html").read_text(encoding="utf-8")
    replacements = {
        "__APP__": html.escape(app["name"]), "__BRAND__": html.escape(app["brand"]),
        "__VERSION__": html.escape(version), "__READY_TEXT__": html.escape(app["readyText"]),
        "__STYLE__": css,
        "__CONFIG__": "const APP = " + json.dumps(app).replace("<", "\\u003c") + ";",
        "__SCRIPT__": (HERE / "ui.js").read_text(encoding="utf-8"),
    }
    for key, value in replacements.items():
        page = page.replace(key, value)
    if re.search(r"__[A-Z_]+__", page):
        raise ValueError("Unresolved UI placeholder")
    return page


# This browser-only adapter cannot extract, install, write registration or launch.
PREVIEW = """<script>
window.ipc = {postMessage(raw) {
  const msg = JSON.parse(raw);
  if (msg.cmd === 'ready') setTimeout(() => window.host({kind:'init',
    folder:'%LOCALAPPDATA%\\\\XynLevel', installed:location.hash === '#update',
    installedVersion:'preview'}), 0);
  if (msg.cmd === 'install') {
    window.host({kind:'progress',step:'Installing XynLevel',detail:'Preview only - no installation'});
    setTimeout(() => window.host(location.hash === '#error'
      ? {kind:'error',message:'Preview: setup exited with code 2. Check permissions and free disk space, then retry.'}
      : {kind:'done'}), 4000);
  }
  if (msg.cmd === 'browse') window.host({kind:'folder',folder:'C:\\\\Apps\\\\XynLevel'});
  if (msg.cmd === 'launch' || msg.cmd === 'close') document.documentElement.dataset.closed = msg.cmd;
}};
</script>"""


def prepare(bundle: Path, source: Path | None, version: str) -> None:
    if not re.fullmatch(r"\d+\.\d+\.\d+", version) or any(int(v) > 65535 for v in version.split('.')):
        raise ValueError("Version must have three numeric components from 0 to 65535")
    bundle = bundle.resolve()
    if not bundle.is_relative_to(HERE / "work"):
        raise ValueError("Generated resources must be inside installer/work")
    receipt = check_backend(source, version) if source else None
    page = render_ui(version)
    bundle.mkdir(parents=True, exist_ok=True)
    (bundle / "ui.html").write_text(page, encoding="utf-8", newline="\n")
    (bundle / "preview.html").write_text(page.replace("<script>const APP", PREVIEW + "<script>const APP"), encoding="utf-8", newline="\n")
    (bundle / "version.txt").write_text(version, encoding="ascii")
    if receipt:
        shutil.copyfile(source, bundle / "xyn-payload.exe")
        (bundle / "backend.json").write_text(json.dumps(receipt, indent=2) + "\n", encoding="ascii")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bundle", type=Path)
    parser.add_argument("--source", type=Path)
    parser.add_argument("--version", required=True)
    args = parser.parse_args()
    prepare(args.bundle, args.source, args.version)
