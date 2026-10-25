"""Only sanitised application events enter reports, logs and Discord."""
import os
import re


def scrub(value):
    text = str(value)
    text = re.sub(r"https?://[^\s\"<>]+", "[url]", text, flags=re.I)
    text = re.sub(r"\b[A-Z]:[\\/][^\r\n\"<>]*", "[local path]", text, flags=re.I)
    text = re.sub(r"\\\\[^\s\"<>]+", "[network path]", text)
    text = re.sub(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", "[email]", text)
    text = re.sub(r"\b(?:\d{1,3}\.){3}\d{1,3}\b", "[ip]", text)
    for name in (os.environ.get("USERNAME"), os.environ.get("COMPUTERNAME")):
        if name and len(name) >= 3:
            text = re.sub(re.escape(name), "[private]", text, flags=re.I)
    return text[:2000]
