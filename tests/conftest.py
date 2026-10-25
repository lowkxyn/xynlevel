"""Most bot tests replay real game screenshots. Those show the Roblox account, so they stay private
(refs/, live/ and analysis/ aren't published). Without them, those test files are skipped."""

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

collect_ignore = []
if not (ROOT / "refs").is_dir():
    collect_ignore.append("test_loop.py")
if not (ROOT / "live").is_dir():
    collect_ignore += ["test_aim.py", "test_menu.py", "test_stats.py"]
