import copy
import json
from pathlib import Path
import sys
import tempfile
import threading
import time
import types
import unittest
from unittest.mock import patch
from zipfile import ZipFile

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "python"))
from core_server import Bridge, HEADER, Server
from privacy import scrub
from settings import CORE_KEYS, DEFAULTS, SettingsStore, validate


class FakeBot:
    def __init__(self, settings, on_status, on_stop):
        self.settings, self.on_status, self.on_stop = settings, on_status, on_stop
        self.time_left = None

    def start(self):
        self.on_status("Ki blasts")

    def stop(self):
        self.on_stop("Stopped")


def format_seconds(value):
    hours, rest = divmod(max(0, int(value)), 3600)
    minutes, seconds = divmod(rest, 60)
    return f"{hours}h {minutes}m {seconds}s" if hours else f"{minutes}m {seconds}s" if minutes else f"{seconds}s"


def fake_core():
    return (
        types.SimpleNamespace(Bot=FakeBot),
        types.SimpleNamespace(format_seconds=format_seconds),
        types.SimpleNamespace(find_roblox_window=lambda: None, game_area_size=lambda _: (1920, 1080),
                              auto_window=lambda _: (True, "Window set"), GAME_WIDTH=1920, GAME_HEIGHT=1080),
    )


class SettingsTests(unittest.TestCase):
    def test_old_saved_settings_receive_new_core_defaults(self):
        raw = {key: value for key, value in DEFAULTS.items() if key not in ("restore_slot", "ceiling_aim", "blast_jump", "ki_control_spend", "ki_control_target")}
        raw["attack"] = "blasts"
        raw["movement"] = "off"
        raw["sprint"] = False
        with tempfile.TemporaryDirectory(dir=BUILD) as folder:
            path = Path(folder) / "settings.json"
            path.write_text(json.dumps(raw), encoding="utf-8")
            before = path.read_bytes()
            store = SettingsStore(folder)
            self.assertFalse(store.blocked)
            self.assertTrue(store.value["restore_slot"])
            self.assertTrue(store.value["ceiling_aim"])
            self.assertTrue(store.value["blast_jump"])
            self.assertFalse(store.value["ki_control_spend"])
            self.assertEqual(store.value["ki_control_target"], 300)
            self.assertEqual(store.value["movement"], "off")
            self.assertFalse(store.value["sprint"])
            self.assertEqual(store.value["attack"], "blasts")
            self.assertEqual(path.read_bytes(), before)
            store.save(store.value)
            self.assertEqual(SettingsStore(folder).value, store.value)

    def test_new_core_boolean_types_and_explicit_false(self):
        for key in ("restore_slot", "ceiling_aim", "blast_jump", "ki_control_spend"):
            self.assertFalse(validate({key: False})[key])
            for value in (None, 0, 1, "false", [], {}):
                with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                    validate({key: value})

    def test_bad_saved_new_boolean_is_preserved(self):
        for key in ("restore_slot", "ceiling_aim", "blast_jump", "ki_control_spend"):
            with self.subTest(key=key), tempfile.TemporaryDirectory(dir=BUILD) as folder:
                path = Path(folder) / "settings.json"
                path.write_text(json.dumps({key: "false"}), encoding="utf-8")
                before = path.read_bytes()
                store = SettingsStore(folder)
                self.assertTrue(store.blocked)
                self.assertEqual(path.read_bytes(), before)

    def test_old_saved_settings_receive_navigation_defaults(self):
        raw = {key: value for key, value in DEFAULTS.items() if key not in ("nav_style", "dial_sounds")}
        raw["attack"] = "blasts"
        with tempfile.TemporaryDirectory(dir=BUILD) as folder:
            path = Path(folder) / "settings.json"
            path.write_text(json.dumps(raw), encoding="utf-8")
            before = path.read_bytes()
            store = SettingsStore(folder)
            self.assertFalse(store.blocked)
            self.assertEqual(store.value["nav_style"], "keycap")
            self.assertFalse(store.value["dial_sounds"])
            self.assertEqual(store.value["attack"], "blasts")
            self.assertEqual(path.read_bytes(), before)
            store.save({**store.value, "nav_style": "dial", "dial_sounds": True})
            saved = SettingsStore(folder).value
            self.assertEqual(saved["nav_style"], "dial")
            self.assertTrue(saved["dial_sounds"])

    def test_bad_navigation_preferences_fall_back_without_blocking(self):
        for bad in (None, 0, 1, "invalid", [], {}):
            with self.subTest(bad=bad), tempfile.TemporaryDirectory(dir=BUILD) as folder:
                path = Path(folder) / "settings.json"
                path.write_text(json.dumps({"nav_style": bad, "dial_sounds": bad}), encoding="utf-8")
                store = SettingsStore(folder)
                self.assertFalse(store.blocked)
                self.assertEqual(store.value["nav_style"], "keycap")
                self.assertFalse(store.value["dial_sounds"])

    def test_navigation_preferences_stay_out_of_macro_settings(self):
        self.assertEqual({"nav_style", "dial_sounds"} & set(CORE_KEYS), set())
        self.assertEqual(set(DEFAULTS) - set(CORE_KEYS), {
            "theme", "accent", "reduced_motion", "notifications", "sound", "after_run",
            "always_on_top", "nav_style", "dial_sounds",
        })

    def test_defaults_and_roundtrip(self):
        value = validate({})
        self.assertEqual(value["movement"], "circle")
        self.assertTrue(value["sprint"])
        self.assertTrue(value["blast_jump"])
        self.assertFalse(value["ki_control_spend"])
        self.assertEqual(value["ki_control_target"], 300)
        with tempfile.TemporaryDirectory(dir=BUILD) as folder:
            store = SettingsStore(folder)
            self.assertEqual(store.value, DEFAULTS)
            raw = {**DEFAULTS, "attack": "ult", "ult_slot": 8, "stop_at_seconds": 0}
            store.save(raw)
            self.assertEqual(SettingsStore(folder).value, raw)

    def test_ki_control_target_clamps_and_persists(self):
        with tempfile.TemporaryDirectory(dir=BUILD) as folder:
            store = SettingsStore(folder)
            for target, expected in ((-10, 1), (0, 1), (1, 1), (300, 300), (5000, 5000), (5001, 5000)):
                with self.subTest(target=target):
                    self.assertEqual(validate({"ki_control_target": target})["ki_control_target"], expected)
                    store.save({"ki_control_target": target})
                    self.assertEqual(SettingsStore(folder).value["ki_control_target"], expected)

    def test_ki_control_target_rejects_non_numbers_and_fractions(self):
        for target in (None, True, False, "300", "", [], {}, float("nan"), float("inf"), -float("inf"), 1.5, 300.0):
            with self.subTest(target=target), self.assertRaises(ValueError):
                validate({"ki_control_target": target})

    def test_invalid_values_fail_closed(self):
        for raw in ([], None, {"other": 1}, {"stop_enabled": "false"}, {"ult_slot": True},
                    {"ult_slot": 7.0}, {"blast_interval": float("nan")}, {"scroll_interval": 0},
                    {"scroll_interval": True}, {"stop_at_seconds": -1}, {"stop_at_seconds": 1.2},
                    {"stop_at_seconds": 604801}, {"theme": "other"}, {"accent": "#fff"}):
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                validate(raw)

    def test_corrupt_settings_preserved_until_explicit_reset(self):
        with tempfile.TemporaryDirectory(dir=BUILD) as folder:
            path = Path(folder) / "settings.json"
            path.write_text("bad json", encoding="utf-8")
            store = SettingsStore(folder)
            self.assertTrue(store.blocked)
            with self.assertRaises(ValueError):
                store.save(DEFAULTS)
            self.assertEqual(path.read_text(), "bad json")
            store.reset()
            self.assertEqual((path.parent / "settings.backup-1.json").read_text(), "bad json")
            self.assertFalse(SettingsStore(folder).blocked)

    def test_failed_atomic_replace_does_not_change_memory_or_saved_settings(self):
        with tempfile.TemporaryDirectory(dir=BUILD) as folder:
            store = SettingsStore(folder)
            store.save(DEFAULTS)
            with patch("settings.os.replace", side_effect=OSError("Unavailable")), self.assertRaises(OSError):
                store.save({**DEFAULTS, "attack": "ult"})
            self.assertEqual(store.value, DEFAULTS)
            self.assertEqual(SettingsStore(folder).value, DEFAULTS)


class BridgeTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(dir=BUILD)
        self.bridge = Bridge(self.temporary.name, core=fake_core(), hotkeys=False)

    def tearDown(self):
        self.bridge.close()
        self.temporary.cleanup()

    def test_start_snapshot_stop_and_settings_capture(self):
        bridge = self.bridge
        bridge.command("start", {})
        bot = bridge.bot
        self.assertEqual(set(bot.settings), {"attack", "ult_slot", "blast_interval", "scroll_interval", "stop_enabled", "stop_at_seconds",
                                             "movement", "relock", "hide_chat", "auto_gravity", "gravity", "sprint", "blast_jump", "ult_jump", "auto_buy", "replace_slot", "restore_slot", "ceiling_aim", "ki_control_spend", "ki_control_target"})
        bridge.command("settings", {**DEFAULTS, "attack": "ult"})
        self.assertEqual(bot.settings["attack"], "auto")
        bot.time_left = 3725
        self.assertEqual(bridge.snapshot()["time_formatted"], "1h 2m 5s")
        with self.assertRaises(ValueError):
            bridge.command("start", {})
        with self.assertRaises(ValueError):
            bridge.command("set_window", {})
        bridge.command("stop", {})
        self.assertFalse(bridge.snapshot()["running"])

    def test_new_bot_settings_reach_bot_unchanged(self):
        choices = {"movement": "off", "sprint": False, "blast_jump": False, "ki_control_spend": True, "ki_control_target": 725}
        self.bridge.command("settings", {**DEFAULTS, **choices})
        self.bridge.command("start", {})
        for key, value in choices.items():
            self.assertEqual(self.bridge.bot.settings[key], value)
        self.bridge.command("settings", {**DEFAULTS, "ki_control_target": 999})
        self.assertEqual(self.bridge.bot.settings["ki_control_target"], 725)

    def test_threshold_uses_run_settings_and_cancel_is_final(self):
        bridge = self.bridge
        bridge.command("settings", {**DEFAULTS, "stop_enabled": True, "after_run": "close_app"})
        bridge.command("start", {})
        bridge.command("settings", {**DEFAULTS, "after_run": "shutdown"})
        bridge.bot.on_stop("Stopped: 60s (1m 0s) left")
        self.assertEqual(bridge.pending_action, "close_app")
        with self.assertRaises(ValueError):
            bridge.command("start", {})
        bridge.command("cancel_after_run", {})
        self.assertIsNone(bridge.tick())
        self.assertIsNone(bridge.pending_action)

    def test_errors_manual_stop_and_close_never_trigger_after_run(self):
        bridge = self.bridge
        bridge.command("settings", {**DEFAULTS, "after_run": "shutdown"})
        for reason in ("Stopped: Roblox not found", "Stopped: error: unavailable", "Stopped"):
            bridge.command("start", {})
            bridge.bot.on_stop(reason)
            self.assertIsNone(bridge.pending_action)
        bridge.command("start", {})
        bridge.command("stop", {})
        self.assertIsNone(bridge.pending_action)

    def test_countdown_completes_close_action_without_calling_windows(self):
        bridge = self.bridge
        bridge.pending_action = "close_app"
        bridge.action_deadline = time.monotonic() - 1
        self.assertEqual(bridge.tick(), "close_app")
        self.assertIsNone(bridge.tick())

    def test_shutdown_is_not_forced_and_start_waits_for_windows(self):
        import subprocess
        bridge = self.bridge
        bridge.pending_action = "shutdown"
        bridge.action_deadline = time.monotonic() - 1
        with patch("subprocess.run", return_value=types.SimpleNamespace(returncode=0)) as run:
            self.assertEqual(bridge.tick(), "shutdown")
            self.assertTrue(run.call_args.args[0][0].lower().endswith("\system32\shutdown.exe"))  # full path, no search-path lookup
            self.assertEqual(run.call_args.args[0][1:], ["/s", "/t", "0"])
        self.assertEqual(bridge.action_status, "requested")
        with self.assertRaises(ValueError):
            bridge.command("start", {})
        bridge.pending_action = "shutdown"
        bridge.action_deadline = time.monotonic() - 1
        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired("shutdown.exe", 10)):
            bridge.tick()
        self.assertEqual(bridge.action_status, "unknown")

    def test_report_is_exact_preview_and_excludes_input_recordings(self):
        bridge = self.bridge
        bridge.set_status(r"Example error at C:\Profiles\Example\secret.txt from test@example.invalid https://example.invalid/private")
        preview = copy.deepcopy(bridge.command("report_preview", {})["report"])
        bridge.set_status("This later event is not in the approved preview")
        saved = bridge.command("report_save", {})
        with ZipFile(bridge.directory / "reports" / saved["filename"]) as report:
            self.assertEqual(report.namelist(), ["report.json"])
            actual = json.loads(report.read("report.json"))
        self.assertEqual(actual, preview)
        content = json.dumps(actual)
        for private in ("secret.txt", "test@example.invalid", "https://example.invalid/private", "input_logs", "token"):
            self.assertNotIn(private, content)
        with self.assertRaises(ValueError):
            bridge.command("report_save", {})

    def test_repeat_status_does_not_flood_log(self):
        for _ in range(5):
            self.bridge.set_status("Charging")
        self.assertEqual(len(self.bridge.events), 1)

    def test_close_stops_owned_bot(self):
        self.bridge.window.find_roblox_window = lambda: 42
        self.bridge.command("start", {})
        self.assertTrue(self.bridge.close())
        self.assertIsNone(self.bridge.bot)

    def test_unknown_command_and_payload_are_rejected(self):
        for action, payload in (("shell", {}), ("start", [])):
            with self.assertRaises(ValueError):
                self.bridge.command(action, payload)


class HttpTests(unittest.TestCase):
    def test_loopback_auth_host_origin_and_routes(self):
        import http.client
        with tempfile.TemporaryDirectory(dir=BUILD) as folder:
            bridge = Bridge(folder, core=fake_core(), hotkeys=False)
            token = "a" * 64
            server = Server(bridge, token)
            worker = threading.Thread(target=server.serve_forever, daemon=True)
            worker.start()
            try:
                def request(route="/state", headers=None, method="GET", body=None):
                    connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=2)
                    connection.request(method, route, body=body, headers=headers or {})
                    response = connection.getresponse()
                    result = response.status, json.loads(response.read())
                    connection.close()
                    return result
                self.assertEqual(request()[0], 401)
                auth = {HEADER: token}
                self.assertEqual(request(headers=auth)[0], 200)
                self.assertEqual(request(headers={**auth, "Origin": "https://example.invalid"})[0], 403)
                self.assertEqual(request(headers={**auth, "Host": "example.invalid"})[0], 403)
                self.assertEqual(request(route="//example.invalid", headers=auth)[0], 404)
                self.assertEqual(request(headers=auth, route="/command", method="POST", body='{"action":"shell"}')[0], 400)
                self.assertEqual(request(headers=auth, route="/command", method="POST", body="bad")[0], 400)
            finally:
                server.shutdown()
                server.server_close()
                bridge.close()


class HotkeyTests(unittest.TestCase):
    def test_f6_repeat_is_ignored_until_release(self):
        class Listener:
            def __init__(self, on_press, on_release):
                self.press, self.release = on_press, on_release
                self.alive = False

            def start(self):
                self.alive = True

            def wait(self):
                pass

            def is_alive(self):
                return self.alive

            def stop(self):
                self.alive = False

        keyboard = types.SimpleNamespace(Key=types.SimpleNamespace(f6="f6"), Listener=Listener)
        with tempfile.TemporaryDirectory(dir=BUILD) as folder, patch.dict(sys.modules, {"pynput": types.SimpleNamespace(keyboard=keyboard)}):
            bridge = Bridge(folder, core=fake_core())
            try:
                event = threading.Event()
                with patch.object(bridge, "hotkey_toggle", side_effect=event.set) as toggle:
                    bridge.hotkey.press("other")
                    bridge.hotkey.press("f6")
                    self.assertTrue(event.wait(2))
                    event.clear()
                    bridge.hotkey.press("f6")
                    self.assertEqual(toggle.call_count, 1)
                    bridge.hotkey.release("f6")
                    bridge.hotkey.press("f6")
                    self.assertTrue(event.wait(2))
                    self.assertEqual(toggle.call_count, 2)
            finally:
                bridge.close()


class HotkeyStartTests(unittest.TestCase):
    def test_f6_starts_only_with_roblox_in_front_but_always_stops(self):
        with tempfile.TemporaryDirectory(dir=BUILD) as folder:
            bridge = Bridge(folder, core=fake_core(), hotkeys=False)
            try:
                with patch.object(bridge, "command") as command, patch.object(bridge, "roblox_in_front", return_value=False):
                    bridge.hotkey_toggle()
                    command.assert_not_called()
                    bridge.bot = object()
                    bridge.hotkey_toggle()
                    command.assert_called_once_with("stop", {})
                    bridge.bot = None
                with patch.object(bridge, "command") as command, patch.object(bridge, "roblox_in_front", return_value=True):
                    bridge.hotkey_toggle()
                    command.assert_called_once_with("start", {})
            finally:
                bridge.close()


class RealCoreContractTests(unittest.TestCase):
    def test_real_bot_no_window_stops_without_input(self):
        from core_server import load_core
        core = load_core()
        with tempfile.TemporaryDirectory(dir=BUILD) as folder:
            bridge = Bridge(folder, core=core, hotkeys=False)
            try:
                # Only replace discovery in memory. The real Bot runs its no-window path.
                with patch.object(core[0], "find_roblox_window", return_value=None), patch.object(core[0], "tap") as tap, patch.object(core[0], "scroll_down") as scroll:
                    bridge.command("start", {})
                    self.assertTrue(bridge.stopped.wait(3))
                    self.assertEqual(bridge.status, "Stopped: Roblox not found")
                    tap.assert_not_called()
                    scroll.assert_not_called()
            finally:
                bridge.close()


BUILD = Path(__file__).resolve().parents[1] / ".build" / "tests"
BUILD.mkdir(parents=True, exist_ok=True)

if __name__ == "__main__":
    unittest.main()
