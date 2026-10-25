"""Discord run reports, combining XynMacro's safety with XynClaim's embed presentation.

The webhook URL is DPAPI-encrypted for the current Windows account and never enters settings,
snapshots, logs or bug reports. Only fixed, structured values leave the app: a result label from a
known list and run counters. Raw stop reasons (which can carry error text) are never sent.
"""
import ctypes
import http.client
import json
import math
import os
import queue
import re
import threading
import time
from ctypes import wintypes
from datetime import datetime, timezone
from pathlib import Path

VERSION = "1.0.0"
PROGRESS_CHOICES = (0, 5, 10, 15, 30, 60)
# PTB, Canary and discordapp.com links work on discord.com, which is the only host ever contacted.
_WEBHOOK = re.compile(r"https://(?:(?:ptb|canary)\.)?discord(?:app)?\.com(/api/webhooks/[0-9]{5,24}/[A-Za-z0-9_-]{20,200})")

COLOURS = {"completed": 0x7EB39A, "progress": 0x939AFF, "stopped": 0x8A93A0, "attention": 0xE0A458, "test": 0x939AFF}
TITLES = {"completed": "Session finished", "progress": "Levelling in progress", "stopped": "Run stopped",
          "attention": "Run needs attention", "test": "Test message"}

# Bot stop reasons -> (kind, label). First matching prefix/substring wins; anything else is generic.
_RESULTS = (
    ("left", "completed", "Reached the stop time"),
    ("disconnected", "attention", "Roblox disconnected"),
    ("Roblox not found", "attention", "Roblox wasn't open"),
    ("window closed", "attention", "Roblox closed"),
    ("game area is", "attention", "Window size changed"),
    ("GC timer", "attention", "Left the Gravity Chamber"),
    ("GC screen", "attention", "Left the Gravity Chamber"),
    ("is empty", "attention", "Ult slot empty"),
    ("Respawn didn't respond", "attention", "Respawn stuck"),
    ("error", "attention", "Macro error"),
)


def classify(reason, manual_stop):
    if manual_stop:
        return "stopped", "Stopped by you"
    text = str(reason)
    for needle, kind, label in _RESULTS:
        if needle in text:
            return kind, label
    return "stopped", "Stopped"


# ---------------- DPAPI ----------------

class _Blob(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_byte))]


def _crypt(data, protect):
    buffer = ctypes.create_string_buffer(data, len(data))
    source = _Blob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_byte)))
    output = _Blob()
    crypt32 = ctypes.windll.crypt32
    ok = (crypt32.CryptProtectData(ctypes.byref(source), "XynLevel webhook", None, None, None, 0, ctypes.byref(output))
          if protect else
          crypt32.CryptUnprotectData(ctypes.byref(source), None, None, None, None, 0, ctypes.byref(output)))
    if not ok:
        raise OSError("Windows couldn't protect or unlock the webhook for this account")
    try:
        return ctypes.string_at(output.pbData, output.cbData)
    finally:
        kernel32 = ctypes.windll.kernel32
        kernel32.LocalFree.argtypes = [ctypes.c_void_p]
        kernel32.LocalFree(ctypes.cast(output.pbData, ctypes.c_void_p))


# ---------------- payload ----------------

def _int(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0
    return int(max(0, min(number, 10 ** 7))) if math.isfinite(number) else 0


def _duration(seconds):
    seconds = _int(seconds)
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)
    return f"{hours}h {minutes}m" if hours else f"{minutes}m {secs}s"


def payload(kind, label=None, stats=None, time_left=None):
    if kind not in TITLES:
        raise ValueError("Unknown notification kind")
    stats = stats if isinstance(stats, dict) else {}
    embed = {
        "title": TITLES[kind],
        "color": COLOURS[kind],
        "footer": {"text": f"XynLevel {VERSION} · Gravity Chamber"},
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    if kind == "test":
        embed["description"] = "Webhook works. Run reports will look like this."
    else:
        if label:
            embed["description"] = f"**{label}**"
        fields = [{"name": "Run time", "value": _duration(stats.get("elapsed")), "inline": True},
                  {"name": "Deaths", "value": str(_int(stats.get("deaths"))), "inline": True},
                  {"name": "Ults fired", "value": str(_int(stats.get("ults"))), "inline": True},
                  {"name": "Ki blasts", "value": str(_int(stats.get("blasts"))), "inline": True}]
        if stats.get("level") is not None and stats.get("start_level") is not None:
            level, start = _int(stats.get("level")), _int(stats.get("start_level"))
            fields.insert(1, {"name": "Level", "value": f"{start} → {level} (+{max(0, level - start)})", "inline": True})
        if time_left is not None:
            fields.append({"name": "GC time left", "value": _duration(time_left), "inline": True})
        embed["fields"] = fields
    return {"username": "XynLevel", "allowed_mentions": {"parse": []}, "embeds": [embed]}


def _post(path, body):
    # Fixed host and default TLS checks; no redirects and no proxy credentials.
    connection = http.client.HTTPSConnection("discord.com", timeout=8)
    try:
        connection.request("POST", path + "?wait=true", body=json.dumps(body).encode(),
                           # Discord's Cloudflare front rejects requests without a browser-like agent.
                           headers={"Content-Type": "application/json", "User-Agent": f"Mozilla/5.0 XynLevel/{VERSION}"})
        response = connection.getresponse()
        response.read(2048)
        return response.status
    finally:
        connection.close()


class Webhook:
    def __init__(self, path, post=_post):
        self.path = Path(path)
        self._post = post
        self._lock = threading.RLock()
        self._settings = {"url": "", "enabled": False, "progress_minutes": 0}
        self._generation = 0
        self._queue = queue.Queue(maxsize=4)
        self._worker = None
        self._backoff_until = 0.0
        self._next_progress = 0.0
        self.status = "Not set up"
        try:
            if self.path.stat().st_size > 8192:
                raise ValueError("Webhook file too large")
            self._settings = self._validate(json.loads(_crypt(self.path.read_bytes(), protect=False)))
            self.status = "Ready" if self._settings["enabled"] else ("Off" if self._settings["url"] else "Not set up")
        except FileNotFoundError:
            pass
        except (OSError, ValueError):
            self.status = "Saved webhook couldn't be read. Save it again."

    def _validate(self, value, previous=None):
        if not isinstance(value, dict):
            raise ValueError("Invalid webhook settings")
        settings = dict(previous or self._settings)
        if "url" in value:
            url = value["url"]
            if not isinstance(url, str):
                raise ValueError("Paste a Discord webhook URL (discord.com/api/webhooks/...)")
            url = url.strip()
            if url:
                match = _WEBHOOK.fullmatch(url)
                if not match:
                    raise ValueError("Paste a Discord webhook URL (discord.com/api/webhooks/...)")
                url = "https://discord.com" + match.group(1)  # one canonical host, the only one contacted
            settings["url"] = url
        if "enabled" in value:
            if type(value["enabled"]) is not bool:
                raise ValueError("Webhook must be on or off")
            settings["enabled"] = value["enabled"]
        if "progress_minutes" in value:
            if type(value["progress_minutes"]) is not int or value["progress_minutes"] not in PROGRESS_CHOICES:
                raise ValueError("Pick one of the listed progress intervals")
            settings["progress_minutes"] = value["progress_minutes"]
        if settings["enabled"] and not settings["url"]:
            raise ValueError("Paste a webhook URL before turning reports on")
        return settings

    def snapshot(self):
        with self._lock:
            return {"configured": bool(self._settings["url"]), "enabled": self._settings["enabled"],
                    "progress_minutes": self._settings["progress_minutes"], "status": self.status}

    def configure(self, value):
        with self._lock:
            updated = self._validate(value)
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.path.with_suffix(".tmp")
            temporary.write_bytes(_crypt(json.dumps(updated).encode(), protect=True))
            os.replace(temporary, self.path)
            if updated["url"] != self._settings["url"] or not updated["enabled"]:
                self._generation += 1  # drop anything queued for the old destination
                self._backoff_until = 0.0
            if updated["progress_minutes"] != self._settings["progress_minutes"]:
                self._next_progress = time.monotonic() + updated["progress_minutes"] * 60
            self._settings = updated
            self.status = "Ready" if updated["enabled"] else ("Off" if updated["url"] else "Not set up")
        return self.snapshot()

    def clear(self):
        with self._lock:
            self._generation += 1
            self._settings = {"url": "", "enabled": False, "progress_minutes": 0}
            self.status = "Not set up"
            self.path.unlink(missing_ok=True)
            self.path.with_suffix(".tmp").unlink(missing_ok=True)
        return self.snapshot()

    def begin_run(self):
        with self._lock:
            self._next_progress = time.monotonic() + self._settings["progress_minutes"] * 60

    def maybe_progress(self, stats, time_left):
        """Called often from the bridge loop; never blocks on a busy lock."""
        if not self._lock.acquire(blocking=False):
            return
        try:
            interval = self._settings["progress_minutes"] * 60
            if not self._settings["enabled"] or not interval or time.monotonic() < self._next_progress:
                return
            self._next_progress = time.monotonic() + interval
        finally:
            self._lock.release()
        self.send("progress", "Still levelling", stats, time_left)

    def send(self, kind, label=None, stats=None, time_left=None):
        with self._lock:
            if not self._settings["url"] or (kind != "test" and not self._settings["enabled"]):
                return False
            if time.monotonic() < self._backoff_until:
                self.status = "Discord rate limit: reports paused for up to 5 minutes"
                return False
            try:
                self._queue.put_nowait((self._generation, payload(kind, label, stats, time_left)))
            except queue.Full:
                self.status = "Report queue full; message skipped"
                return False
            self.status = "Sending..."
            if self._worker is None or not self._worker.is_alive():
                self._worker = threading.Thread(target=self._work, daemon=True, name="discord-webhook")
                self._worker.start()
            return True

    def flush(self, timeout=3.0):
        """Give queued reports a few seconds to go out (the worker is a daemon thread)."""
        deadline = time.monotonic() + timeout
        while self._queue.unfinished_tasks and time.monotonic() < deadline:
            time.sleep(0.05)
        return not self._queue.unfinished_tasks

    def _work(self):
        while True:
            generation, body = self._queue.get()
            try:
                with self._lock:
                    if generation != self._generation or not self._settings["url"]:
                        continue
                    path = self._settings["url"].removeprefix("https://discord.com")
                try:
                    status = self._post(path, body)
                    message = "Last report delivered" if status in (200, 204) else f"Discord refused the report (HTTP {status})"
                except (OSError, http.client.HTTPException):
                    status, message = 0, "Couldn't reach Discord; check your connection"
                with self._lock:
                    if generation == self._generation:
                        self.status = message
                        if status == 429:
                            self._backoff_until = time.monotonic() + 300
                        elif status in (401, 404):
                            self.status = "Discord says this webhook was deleted. Paste a new one."
            finally:
                self._queue.task_done()
