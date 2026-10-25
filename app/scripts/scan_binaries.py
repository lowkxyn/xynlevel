"""Fail if anything identifying the builder is inside a shipped file (ASCII or UTF-16, any case).

usage: py -I scripts/scan_binaries.py <file> [<file> ...]
Looks for: the Windows username and computer name (read from the environment at run time and never
written anywhere), the project's own folder, Discord webhook URLs, and any extra words in the
XYNLEVEL_PRIVATE_WORDS environment variable (comma-separated, e.g. Roblox account names) so they
don't have to be stored in the repo.
"""

import os
import re
import sys


# Third-party or code text that can contain a short private word by coincidence: one citation line in
# OpenCV's built-in credits (any name after this first name), and webhook.py's URL pattern and hint.
BENIGN = (re.compile(rb"j&#233;r&#233;mie [a-z]+"), re.compile(rb"/api/webhooks/(?:\[0-9\]|\.\.\.)"))


def without_benign(data):
    for pattern in BENIGN:
        data = pattern.sub(b"", data)
    return data


def configured_words():
    """XYNLEVEL_PRIVATE_WORDS from this process, else from the saved user variable: a build started
    from a shell opened before the variable was saved would otherwise scan without them."""
    value = os.environ.get("XYNLEVEL_PRIVATE_WORDS", "")
    if not value and os.name == "nt":
        import winreg
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as key:
                value = winreg.QueryValueEx(key, "XYNLEVEL_PRIVATE_WORDS")[0]
        except OSError:
            value = ""
    words = [word for word in value.split(",") if word.strip()]
    if not words:
        print("WARNING: XYNLEVEL_PRIVATE_WORDS is empty, so only the username and computer name are checked")
    return words


def private_words():
    # The project's own folder (last two parts of its path), read from where this script lives.
    project = os.path.join(*os.path.abspath(__file__).split(os.sep)[-5:-3])
    words = [os.environ.get("USERNAME", ""), os.environ.get("COMPUTERNAME", ""),
             project, project.replace(os.sep, "/"), "/api/webhooks/"]
    words += configured_words()
    return sorted({w.strip().lower() for w in words if len(w.strip()) >= 3})


def main(paths):
    words = private_words()
    needles = [(w, n) for w in words for n in (w.encode("ascii", "ignore"), w.encode("utf-16-le"))]
    leaks = 0
    for path in paths:
        data = without_benign(open(path, "rb").read().lower())
        hits = {}
        for word, needle in needles:
            count = data.count(needle)
            if count:
                hits[word] = hits.get(word, 0) + count
        # Report which kind of word matched by position only, never the word itself.
        print(f"{os.path.basename(path)}: {sum(hits.values())} hit(s)" +
              (f" on private word #{', #'.join(str(words.index(w) + 1) for w in hits)}" if hits else ""))
        leaks += sum(hits.values())
    if leaks:
        sys.exit("Something identifying is inside a shipped file; don't distribute this build")
    print(f"Privacy scan clean: {len(paths)} files, {len(words)} words")


if __name__ == "__main__":
    main(sys.argv[1:])
