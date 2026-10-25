"""Unpack the PyInstaller sidecar (its files and Python modules are zlib-compressed, so a byte scan of
the .exe can't see inside) and run the same privacy check on every entry.

usage: py -I scripts/scan_sidecar.py <XynLevel-core.exe>
Words come from scan_binaries.private_words(): username, computer name, project path, webhook URLs and
XYNLEVEL_PRIVATE_WORDS. Hits are reported by word number only.
"""

import io
import marshal
import os
import sys
import tempfile
import zipfile

from PyInstaller.archive.readers import CArchiveReader, ZlibArchiveReader

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from scan_binaries import private_words, without_benign  # noqa: E402


def entries(exe):
    archive = CArchiveReader(exe)
    for name in archive.toc:
        data = archive.extract(name)
        if not data:
            continue
        yield name, data
        if zipfile.is_zipfile(io.BytesIO(data)):
            with zipfile.ZipFile(io.BytesIO(data)) as archive_zip:
                for inner in archive_zip.namelist():
                    yield f"{name}/{inner}", archive_zip.read(inner)
        if name.lower().endswith(".pyz"):
            with tempfile.TemporaryDirectory() as folder:
                path = os.path.join(folder, "modules.pyz")
                with open(path, "wb") as handle:
                    handle.write(data)
                modules = ZlibArchiveReader(path)
                for module in modules.toc:
                    code = modules.extract(module)
                    yield module, code if isinstance(code, (bytes, bytearray)) else marshal.dumps(code)


def main(exe):
    words = private_words()
    needles = [(index, needle) for index, word in enumerate(words, 1)
               for needle in (word.encode("ascii", "ignore"), word.encode("utf-16-le"))]
    scanned = hits = 0
    for name, data in entries(exe):
        scanned += 1
        lowered = without_benign(bytes(data).lower())
        for index, needle in needles:
            if needle in lowered:
                hits += 1
                print(f"hit on private word #{index} in {name}")
    if hits:
        sys.exit("Something identifying is inside the sidecar; don't distribute this build")
    print(f"Sidecar scan clean: {scanned} entries, {len(words)} words")


if __name__ == "__main__":
    main(sys.argv[1])
