"""XynLevel's loopback bridge. The parent folder remains the only automation source."""
import sys

# Importing the live core must not write bytecode into its folder.
sys.dont_write_bytecode = True

import argparse
import ctypes
import hmac
import json
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import re
import threading
import time
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from zipfile import ZIP_DEFLATED, ZipFile

from privacy import scrub
from settings import CORE_KEYS, SettingsStore
from webhook import Webhook, classify

VERSION = "1.0.0"
HEADER = "X-XynLevel-Token"


def load_core():
    if not getattr(sys, "frozen", False):
        sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    import gc_bot
    import gc_vision
    import window
    return gc_bot, gc_vision, window



def bridge_pid():
    """The pid the Tauri host launched. A PyInstaller onefile build runs Python in a child of its
    bootloader, so the launched process is our parent."""
    return os.getppid() if getattr(sys, "frozen", False) else os.getpid()

class Bridge:
    def __init__(self, directory, core=None, hotkeys=True):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.store = SettingsStore(self.directory)
        # Encrypted on its own; never part of settings.json, snapshots or reports.
        self.webhook = Webhook(self.directory / "webhook.bin")
        self.core, self.vision, self.window = core or load_core()
        self.lock = threading.RLock()
        self.events = deque(maxlen=300)
        self.sequence = 0
        self.bot = None
        self.stopped = threading.Event()
        self.stopped.set()
        self.status = "Stand in the GC bot room (alive or dead), then Start."
        self.last_time = None
        self.run_id = 0
        self.last_run = None
        self.run_settings = None
        self.manual_stop = False
        self.closing = False
        self.pending_action = None
        self.action_deadline = None
        self.action_status = "idle"
        self.preview = None
        self.hotkey = None
        self.hotkey_available = False
        self.hotkey_down = False
        self.disk_log = logging.getLogger(f"xynlevel.{id(self)}")
        self.disk_log.setLevel(logging.INFO)
        self.disk_log.propagate = False
        handler = RotatingFileHandler(self.directory / "session.log", maxBytes=262144, backupCount=2, encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(asctime)s %(message)s"))
        self.disk_log.addHandler(handler)
        if self.store.warning:
            self.set_status(self.store.warning)
        if hotkeys:
            from pynput import keyboard

            def press(key):
                if key == keyboard.Key.f6:
                    with self.lock:
                        if self.hotkey_down:
                            return
                        self.hotkey_down = True
                    # Never block the keyboard hook with lifecycle work.
                    threading.Thread(target=self.hotkey_toggle, daemon=True).start()

            def release(key):
                if key == keyboard.Key.f6:
                    with self.lock:
                        self.hotkey_down = False

            try:
                self.hotkey = keyboard.Listener(on_press=press, on_release=release)
                self.hotkey.start()
                self.hotkey.wait()
                self.hotkey_available = self.hotkey.is_alive()
            except RuntimeError:
                self.set_status("F6 is unavailable; use Start and Stop in the app.")

    def roblox_in_front(self):
        hwnd = self.window.find_roblox_window()
        return bool(hwnd) and ctypes.windll.user32.GetForegroundWindow() == hwnd

    def hotkey_toggle(self):
        try:
            with self.lock:
                action = "stop" if self.bot else "start"
                # F6 is global: pressed in OBS or a browser it mustn't start a run. Stop works anywhere.
                if action == "start" and not self.roblox_in_front():
                    self.set_status("F6 starts a run only while Roblox is the active window")
                    return
                self.command(action, {})
        except Exception as error:
            self.set_status(error)

    def set_status(self, message):
        with self.lock:
            message = scrub(message)
            if message == self.status and self.events:
                return
            self.status = message
            self.sequence += 1
            self.events.append({"seq": self.sequence, "time": time.strftime("%H:%M:%S"), "message": message})
            self.disk_log.info(message)

    def bot_stopped(self, reason):
        with self.lock:
            if self.bot:
                self.last_time = self.bot.time_left
                self.last_stats = self._stats(self.bot)
            self.bot = None
            self.stopped.set()
            self.set_status(reason)
            completed = bool(re.fullmatch(r"Stopped: \d+s \(.+\) left", reason)) and bool(self.run_settings["stop_enabled"]) and not self.manual_stop and not self.closing
            kind, label = classify(reason, self.manual_stop or self.closing)
            self.webhook.send(kind, label, getattr(self, "last_stats", None), self.last_time)
            self.last_run = {"id": self.run_id, "reason": self.status, "completed": completed}
            if completed:
                self.pending_action = self.run_settings["after_run"] if self.run_settings["after_run"] != "none" else None
                self.action_deadline = time.monotonic() + 30 if self.pending_action else None
                if self.run_settings["sound"]:
                    import winsound
                    winsound.MessageBeep(winsound.MB_OK)

    @staticmethod
    def _stats(bot):
        """Run counters for the UI: elapsed seconds, deaths, ults fired, ki blasts."""
        stats = dict(getattr(bot, "stats", {}) or {})
        started = stats.pop("started", None)
        stats["elapsed"] = int(time.time() - started) if started else 0
        return stats

    def window_state(self):
        hwnd = self.window.find_roblox_window()
        size = list(self.window.game_area_size(hwnd)) if hwnd else None
        return {"found": bool(hwnd), "size": size, "correct": size == [self.window.GAME_WIDTH, self.window.GAME_HEIGHT]}

    def snapshot(self):
        with self.lock:
            remaining = self.bot.time_left if self.bot else self.last_time
            return {
                "ok": True, "version": VERSION, "running": self.bot is not None,
                "stopping": self.manual_stop and self.bot is not None,
                "status": self.status, "time_left": remaining,
                "stats": self._stats(self.bot) if self.bot else getattr(self, "last_stats", None),
                "webhook": self.webhook.snapshot(),
                "time_formatted": self.vision.format_seconds(remaining) if remaining is not None else None,
                "settings": dict(self.store.value), "settings_warning": self.store.warning,
                "hotkey_available": self.hotkey_available and bool(self.hotkey and self.hotkey.is_alive()),
                "window": self.window_state(), "last_run": self.last_run,
                "after_run": {"action": self.pending_action, "status": self.action_status, "seconds": max(0, int(self.action_deadline - time.monotonic()) + 1) if self.action_deadline else 0},
            }

    def report(self):
        state = self.snapshot()
        # Allowlist only. Never collect environment, paths, screenshots or input recordings.
        return {"product": "XynLevel", "version": VERSION, "packaged": bool(getattr(sys, "frozen", False)),
                "settings": state["settings"], "status": state["status"], "window": state["window"],
                "time_left": state["time_left"], "last_run": state["last_run"], "events": list(self.events)}

    def command(self, action, payload):
        with self.lock:
            if not isinstance(payload, dict):
                raise ValueError("Command payload must be an object")
            if self.closing and action != "shutdown":
                raise ValueError("The app is closing")
            if action == "start":
                if self.store.blocked:
                    raise ValueError(self.store.warning)
                if self.bot:
                    raise ValueError("Already running or stopping")
                if self.pending_action:
                    raise ValueError("Cancel the after-run action before starting")
                if self.action_status in ("requesting", "requested", "unknown"):
                    raise ValueError("Windows shutdown was requested. Resolve it in Windows before restarting XynLevel.")
                self.run_settings = dict(self.store.value)
                self.run_id += 1
                self.manual_stop = False
                self.last_time = None
                self.stopped.clear()
                self.set_status("Starting...")
                bot = self.core.Bot({key: self.run_settings[key] for key in CORE_KEYS}, self.set_status, self.bot_stopped)
                self.bot = bot
                self.webhook.begin_run()
                try:
                    bot.start()
                except Exception:
                    self.bot = None
                    self.stopped.set()
                    self.set_status("Stopped: core could not start")
                    raise
            elif action == "stop":
                if self.bot:
                    self.manual_stop = True
                    self.set_status("Stopping...")
                    self.bot.stop()
            elif action == "settings":
                self.store.save(payload)
            elif action == "reset_settings":
                if self.bot:
                    raise ValueError("Stop the macro before restoring defaults")
                self.store.reset()
            elif action == "set_window":
                if self.bot:
                    raise ValueError("Stop the macro before setting the window")
                hwnd = self.window.find_roblox_window()
                if not hwnd:
                    self.set_status("Open Roblox first.")
                    return {"ok": False, "error": "Roblox not found"}
                ok, message = self.window.auto_window(hwnd)
                self.set_status(message)
                if not ok:
                    return {"ok": False, "error": scrub(message)}
            elif action == "report_preview":
                self.preview = self.report()
                return {"ok": True, "report": self.preview}
            elif action == "report_save":
                if self.preview is None:
                    raise ValueError("Preview the report before saving")
                folder = self.directory / "reports"
                folder.mkdir(exist_ok=True)
                name = f"XynLevel-report-{time.time_ns()}.zip"
                with ZipFile(folder / name, "x", ZIP_DEFLATED) as bundle:
                    bundle.writestr("report.json", json.dumps(self.preview, indent=2))
                self.preview = None
                return {"ok": True, "filename": name}
            elif action == "export_logs":
                folder = self.directory / "reports"
                folder.mkdir(exist_ok=True)
                name = f"XynLevel-log-{time.time_ns()}.txt"
                with (folder / name).open("x", encoding="utf-8") as output:
                    output.write("\n".join(f"{event['time']} {event['message']}" for event in self.events))
                return {"ok": True, "filename": name}
            elif action == "webhook_save":
                self.webhook.configure(payload)
                return {"ok": True, "webhook": self.webhook.snapshot()}
            elif action == "webhook_clear":
                self.webhook.clear()
                return {"ok": True, "webhook": self.webhook.snapshot()}
            elif action == "webhook_test":
                if not self.webhook.send("test"):
                    raise ValueError("Paste a webhook URL first")
                return {"ok": True, "webhook": self.webhook.snapshot()}
            elif action == "cancel_after_run":
                self.pending_action = self.action_deadline = None
                self.set_status("After-run action cancelled.")
            elif action == "open_data":
                os.startfile(self.directory)
            elif action == "shutdown":
                # Actual cleanup is outside the state lock so on_stop can complete.
                self.closing = True
            else:
                raise ValueError("Unknown command")
            return {"ok": True}

    def tick(self):
        bot = self.bot
        # No "still levelling" while the bot is paused or can't see the game.
        if bot and not str(self.status).startswith(("Paused", "Waiting")):
            self.webhook.maybe_progress(self._stats(bot), bot.time_left)
        with self.lock:
            if not self.pending_action or time.monotonic() < self.action_deadline or self.closing:
                return None
            action = self.pending_action
            self.pending_action = self.action_deadline = None
            if action == "shutdown":
                self.action_status = "requesting"
        if action == "shutdown":
            import subprocess
            # No forced close of other applications. The app countdown is cancellable.
            try:
                result = subprocess.run([str(Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "shutdown.exe"), "/s", "/t", "0"], creationflags=subprocess.CREATE_NO_WINDOW, capture_output=True, timeout=10)
                with self.lock:
                    self.action_status = "requested" if result.returncode == 0 else "failed"
                self.set_status("Shutdown requested; Windows may wait for open apps." if result.returncode == 0 else "Windows did not accept the shutdown request.")
            except subprocess.TimeoutExpired:
                with self.lock:
                    self.action_status = "unknown"
                self.set_status("Shutdown request timed out. Check Windows before restarting XynLevel.")
            except OSError:
                with self.lock:
                    self.action_status = "failed"
                self.set_status("Windows did not accept the shutdown request.")
        return action

    def close(self):
        with self.lock:
            self.closing = True
            self.pending_action = self.action_deadline = None
            bot = self.bot
            if bot:
                self.manual_stop = True
                bot.stop()
        clean = self.stopped.wait(8)
        if not clean and bot:
            # The worker didn't finish: release every key this bot reports holding (charge Shift,
            # movement W/A/D/Space, sprint Shift).
            for key in set(getattr(bot, "_held", ())) | ({"shift"} if getattr(bot, "_charging", False) else set()):
                self.core.pydirectinput.keyUp(key)
        self.webhook.flush(3.0)
        if self.hotkey:
            self.hotkey.stop()
        for handler in list(self.disk_log.handlers):
            handler.close()
            self.disk_log.removeHandler(handler)
        return clean


class Server(ThreadingHTTPServer):
    daemon_threads = True
    block_on_close = False

    def __init__(self, bridge, token):
        self.bridge, self.token = bridge, token
        super().__init__(("127.0.0.1", 0), Handler)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def setup(self):
        super().setup()
        self.connection.settimeout(5)

    def reply(self, status, body):
        encoded = json.dumps(body, allow_nan=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(encoded)

    def allowed(self):
        headers = self.headers
        if headers.get("Host") != f"127.0.0.1:{self.server.server_port}" or headers.get("Origin") is not None:
            self.reply(403, {"ok": False, "error": "Local proxy requests only"})
            return False
        if not hmac.compare_digest(headers.get(HEADER, ""), self.server.token):
            self.reply(401, {"ok": False, "error": "Authentication required"})
            return False
        return True

    def do_GET(self):
        if not self.allowed():
            return
        try:
            if self.path == "/health":
                body = {"ok": True, "pid": bridge_pid(), "version": VERSION}
            elif self.path == "/state":
                body = self.server.bridge.snapshot()
            elif self.path == "/logs":
                with self.server.bridge.lock:
                    body = {"ok": True, "events": list(self.server.bridge.events)}
            else:
                self.reply(404, {"ok": False, "error": "Unknown route"})
                return
            self.reply(200, body)
        except Exception as error:
            self.reply(500, {"ok": False, "error": scrub(error)})

    def do_POST(self):
        if not self.allowed():
            return
        if self.path != "/command":
            self.reply(404, {"ok": False, "error": "Unknown route"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= 16384 or self.headers.get("Transfer-Encoding"):
                raise ValueError("Invalid request size")
            request = json.loads(self.rfile.read(length))
            if not isinstance(request, dict) or not isinstance(request.get("action"), str):
                raise ValueError("Invalid command")
            result = self.server.bridge.command(request["action"], request.get("payload", {}))
            self.reply(200, result)
        except (ValueError, OSError) as error:
            self.reply(400, {"ok": False, "error": scrub(error)})
        except Exception as error:
            self.reply(500, {"ok": False, "error": scrub(error)})


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", type=Path, default=Path(os.environ.get("LOCALAPPDATA", Path.home())) / "XynLevel")
    parser.add_argument("--parent-pid", type=int)
    parser.add_argument("--no-hotkeys", action="store_true", help="For isolated bridge checks")
    args = parser.parse_args()
    token = sys.stdin.readline().strip()
    if len(token) != 64 or any(c not in "0123456789abcdef" for c in token):
        raise SystemExit("A fresh 256-bit authentication token is required on stdin")
    bridge = Bridge(args.data_dir, hotkeys=not args.no_hotkeys)
    server = Server(bridge, token)
    # One readiness line only; no token or local paths on stdout.
    print(json.dumps({"port": server.server_port, "pid": bridge_pid(), "version": VERSION}), flush=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    parent_handle = None
    if args.parent_pid:
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.OpenProcess.restype = ctypes.c_void_p
        kernel.OpenProcess.argtypes = [ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong]
        kernel.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
        kernel.CloseHandle.argtypes = [ctypes.c_void_p]
        parent_handle = kernel.OpenProcess(0x00100000, False, args.parent_pid)
        if not parent_handle:
            bridge.closing = True
    try:
        while not bridge.closing:
            if parent_handle and kernel.WaitForSingleObject(parent_handle, 0) != 0x102:
                break
            if bridge.tick() == "close_app":
                break
            time.sleep(0.1)
    finally:
        bridge.close()
        server.shutdown()
        server.server_close()
        if parent_handle:
            kernel.CloseHandle(parent_handle)


if __name__ == "__main__":
    main()
