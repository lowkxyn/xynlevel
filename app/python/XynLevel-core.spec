"""Freeze only the bridge, external core modules and digit/template assets."""
from pathlib import Path

HERE = Path(SPECPATH)
CORE = HERE.parents[1]
APP = HERE.parent

analysis = Analysis(
    [str(HERE / "core_server.py")],
    pathex=[str(HERE), str(CORE)],
    binaries=[],
    datas=[(str(CORE / "assets"), "assets")],
    hiddenimports=["gc_train", "gc_bot", "gc_vision", "gc_gravity", "gc_menu", "gc_read", "gc_aim", "gc_stats", "window", "pynput.keyboard._win32", "pynput.mouse._win32",
                   # Windows' built-in OCR (gc_read): the winrt projections are separate packages.
                   "winrt.runtime", "winrt.windows.foundation", "winrt.windows.foundation.collections",
                   "winrt.windows.globalization", "winrt.windows.graphics.imaging",
                   "winrt.windows.media.ocr", "winrt.windows.storage.streams"],
    hookspath=[], hooksconfig={}, runtime_hooks=[],
    excludes=["tkinter", "pytest", "IPython", "matplotlib", "pandas", "scipy"],
    noarchive=False,
)
archive = PYZ(analysis.pure)
exe = EXE(
    archive, analysis.scripts, analysis.binaries, analysis.datas, [],
    name="XynLevel-core", debug=False, bootloader_ignore_signals=False,
    strip=False, upx=False, console=True,
    icon=str(APP / "src-tauri" / "icons" / "icon.ico"),
)
