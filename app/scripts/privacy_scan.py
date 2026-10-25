"""Case-insensitive byte grep. Patterns are supplied at runtime, never stored."""
import argparse
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXCLUDED = (".build", ".git", ".venv", "node_modules", "src-tauri/target", "src-tauri/gen", "src-tauri/binaries", "python/build", "python/dist")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--pattern", action="append", required=True)
    args = parser.parse_args()
    patterns = [value.encode("utf-8").lower() for value in args.pattern]
    if any(not value for value in patterns):
        parser.error("Patterns must not be empty")
    counts = [0] * len(patterns)
    scanned = 0
    matches = []
    for path in ROOT.rglob("*"):
        relative = path.relative_to(ROOT).as_posix()
        if not path.is_file() or path.is_symlink() or "__pycache__" in path.parts:
            continue
        if any(relative == folder or relative.startswith(folder + "/") for folder in EXCLUDED):
            continue
        scanned += 1
        content = path.read_bytes().lower()
        for index, pattern in enumerate(patterns):
            if pattern in content:
                counts[index] += 1
                matches.append((relative, index + 1))
    print(f"Source files scanned: {scanned}")
    for index, count in enumerate(counts):
        print(f"Pattern {index + 1}: {count} matching files")
    for name, index in matches:
        print(f"MATCH: {name} (pattern {index})")
    print("PASS: source tree is clean" if not matches else "FAIL: source matches found")
    return bool(matches)


if __name__ == "__main__":
    raise SystemExit(main())
