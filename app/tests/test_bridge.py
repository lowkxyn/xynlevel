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
from core_server import Bridge, HEADER, Server, load_core
from privacy import scrub
from settings import CORE_KEYS, DEFAULTS, SettingsStore, validate


class FakeBot:
    def __init__(self, settings, on_status, on_stop):
        self.settings, self.on_status, self.on_stop = settings, on_status, on_stop
        self.time_left = None
        self.stats = {"started": time.time(), "deaths": 0, "senzus": 0}
        self.events = []

    def start(self):
        self.on_status("Training: Health")

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
    def test_legacy_settings_load_without_retaining_removed_keys(self):
        raw = {"attack": "ult", "ult_slot": 8, "blast_interval": 0.4, "scroll_interval": 1,
               "auto_gravity": False, "gravity": 0, "movement": "off", "sprint": False,
               "stop_enabled": True, "stop_at_seconds": 60, "relock": True, "hide_chat": True,
               "blast_jump": True, "ult_jump": False, "auto_buy": True, "replace_slot": True,
               "restore_slot": False, "ceiling_aim": False, "ki_control_spend": True,
               "ki_control_target": 300, "unknown_legacy": "ignored", "theme": "light",
               "accent": "#22d3ee", "notifications": False, "sound": True,
               "reduced_motion": True, "always_on_top": True, "after_run": "close_app",
               "nav_style": "dial", "dial_sounds": True}
        with tempfile.TemporaryDirectory(dir=BUILD) as folder:
            path = Path(folder) / "settings.json"
            path.write_text(json.dumps(raw), encoding="utf-8")
            before = path.read_bytes()
            store = SettingsStore(folder)
            self.assertFalse(store.blocked)
            self.assertIsNone(store.warning)
            self.assertEqual(store.value, {**DEFAULTS, "theme": "light", "accent": "#22d3ee",
                             "notifications": False, "sound": True, "reduced_motion": True,
                             "always_on_top": True, "after_run": "close_app", "nav_style": "dial", "dial_sounds": True})
            self.assertEqual(path.read_bytes(), before)
            store.save(store.value)
            self.assertEqual(SettingsStore(folder).value, store.value)
            self.assertEqual(set(json.loads(path.read_text())), set(DEFAULTS))
            with self.assertRaises(ValueError):
                store.save(raw)

    def test_mixed_legacy_file_keeps_explicit_training_values(self):
        raw = {"auto_gravity": False, "attack": "blasts", "gravity_mode": "custom",
               "gravity": 175, "auto_senzu": False, "senzu_at": 70,
               "stop_after_minutes": 0, "stop_at_level": 500}
        with tempfile.TemporaryDirectory(dir=BUILD) as folder:
            (Path(folder) / "settings.json").write_text(json.dumps(raw), encoding="utf-8")
            store = SettingsStore(folder)
            self.assertFalse(store.blocked)
            self.assertEqual(store.value, {**DEFAULTS, **{key: value for key, value in raw.items() if key in DEFAULTS}})

    def test_boolean_types_and_explicit_false(self):
        for key in ("auto_senzu", "notifications", "sound", "reduced_motion", "always_on_top", "dial_sounds"):
            self.assertFalse(validate({key: False})[key])
            for value in (None, 0, 1, "false", [], {}):
                with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                    validate({key: value})

    def test_bad_saved_training_value_is_preserved(self):
        for raw in ({"auto_senzu": "false"}, {"gravity": 0}, {"senzu_at": 9}, {"stop_after_minutes": 1.5}):
            with self.subTest(raw=raw), tempfile.TemporaryDirectory(dir=BUILD) as folder:
                path = Path(folder) / "settings.json"
                path.write_text(json.dumps(raw), encoding="utf-8")
                before = path.read_bytes()
                store = SettingsStore(folder)
                self.assertTrue(store.blocked)
                self.assertEqual(path.read_bytes(), before)

    def test_old_saved_settings_receive_navigation_defaults(self):
        with tempfile.TemporaryDirectory(dir=BUILD) as folder:
            path = Path(folder) / "settings.json"
            path.write_text(json.dumps({"theme": "aero"}), encoding="utf-8")
            before = path.read_bytes()
            store = SettingsStore(folder)
            self.assertFalse(store.blocked)
            self.assertEqual(store.value["nav_style"], "keycap")
            self.assertFalse(store.value["dial_sounds"])
            self.assertEqual(store.value["theme"], "aero")
            self.assertEqual(path.read_bytes(), before)

    def test_bad_navigation_preferences_recover_on_load_but_writes_are_strict(self):
        for bad in (None, 0, 1, "invalid", [], {}):
            with self.subTest(bad=bad), tempfile.TemporaryDirectory(dir=BUILD) as folder:
                path = Path(folder) / "settings.json"
                path.write_text(json.dumps({"nav_style": bad, "dial_sounds": bad}), encoding="utf-8")
                store = SettingsStore(folder)
                self.assertFalse(store.blocked)
                self.assertEqual(store.value["nav_style"], "keycap")
                self.assertFalse(store.value["dial_sounds"])
                for key in ("nav_style", "dial_sounds"):
                    with self.assertRaises(ValueError):
                        store.save({key: bad})

    def test_core_allowlist_contains_only_training_settings(self):
        self.assertEqual(CORE_KEYS, ("gravity_mode", "gravity", "auto_senzu", "senzu_at", "stop_after_minutes", "stop_at_level"))
        self.assertEqual(set(DEFAULTS) - set(CORE_KEYS), {
            "theme", "accent", "reduced_motion", "notifications", "sound", "after_run",
            "always_on_top", "nav_style", "dial_sounds",
        })

    def test_defaults_and_roundtrip(self):
        self.assertEqual({key: validate({})[key] for key in CORE_KEYS}, {
            "gravity_mode": "max", "gravity": 500, "auto_senzu": True, "senzu_at": 35,
            "stop_after_minutes": 0, "stop_at_level": 0,
        })
        with tempfile.TemporaryDirectory(dir=BUILD) as folder:
            store = SettingsStore(folder)
            self.assertEqual(store.value, DEFAULTS)
            raw = {**DEFAULTS, "gravity_mode": "custom", "gravity": 175, "auto_senzu": False}
            store.save(raw)
            self.assertEqual(SettingsStore(folder).value, raw)

    def test_training_integer_boundaries_and_invalid_values(self):
        for key, minimum, maximum in (("gravity", 1, 500), ("senzu_at", 10, 90),
                                      ("stop_after_minutes", 0, 10080), ("stop_at_level", 0, 100000)):
            for number in (minimum, maximum):
                with self.subTest(key=key, number=number):
                    self.assertEqual(validate({key: number})[key], number)
            for bad in (minimum - 1, maximum + 1, None, True, False, "35", "", [], {}, float("nan"), float("inf"), -float("inf"), 1.5, 35.0):
                with self.subTest(key=key, bad=bad), self.assertRaises(ValueError):
                    validate({key: bad})

    def test_invalid_values_fail_closed(self):
        for raw in ([], None, {"other": 1}, {"attack": "auto"}, {"gravity_mode": "off"},
                    {"theme": "other"}, {"accent": "#fff"}, {"after_run": "shell"}):
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
                store.save({**DEFAULTS, "gravity_mode": "custom"})
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
        self.assertEqual(bot.settings, {key: DEFAULTS[key] for key in CORE_KEYS})
        bridge.command("settings", {**DEFAULTS, "gravity_mode": "custom", "gravity": 175})
        self.assertEqual(bot.settings["gravity_mode"], "max")
        self.assertEqual(bot.settings["gravity"], 500)
        self.assertIsNone(bridge.snapshot()["time_left"])
        self.assertIsNone(bridge.snapshot()["time_formatted"])
        self.assertEqual(bridge.snapshot()["status"], "Training: Health")
        with self.assertRaises(ValueError):
            bridge.command("start", {})
        with self.assertRaises(ValueError):
            bridge.command("set_window", {})
        bridge.command("stop", {})
        self.assertFalse(bridge.snapshot()["running"])

    def test_new_bot_settings_reach_bot_unchanged(self):
        choices = {"gravity_mode": "custom", "gravity": 175, "auto_senzu": False,
                   "senzu_at": 70, "stop_after_minutes": 45, "stop_at_level": 800}
        self.bridge.command("settings", {**DEFAULTS, **choices})
        self.bridge.command("start", {})
        self.assertEqual(self.bridge.bot.settings, choices)
        self.bridge.command("settings", {**DEFAULTS, "gravity": 250})
        self.assertEqual(self.bridge.bot.settings["gravity"], 175)

    def test_duration_limit_uses_run_settings_and_cancel_is_final(self):
        bridge = self.bridge
        bridge.command("settings", {**DEFAULTS, "stop_after_minutes": 30, "after_run": "close_app"})
        bridge.command("start", {})
        bridge.command("settings", {**DEFAULTS, "after_run": "shutdown"})
        bridge.bot.stats["started"] = time.time() - 1801
        bridge.bot.on_stop("Stopped: ran for 30 min")
        self.assertTrue(bridge.last_run["completed"])
        self.assertEqual(bridge.pending_action, "close_app")
        with self.assertRaises(ValueError):
            bridge.command("start", {})
        bridge.command("cancel_after_run", {})
        self.assertIsNone(bridge.tick())
        self.assertIsNone(bridge.pending_action)

    def test_level_limit_completes_without_chamber_time(self):
        bridge = self.bridge
        bridge.command("settings", {**DEFAULTS, "stop_at_level": 800, "after_run": "close_app"})
        bridge.command("start", {})
        bridge.bot.stats["level"] = 801
        bridge.bot.on_stop("Stopped: reached level 801")
        self.assertTrue(bridge.last_run["completed"])
        self.assertEqual(bridge.pending_action, "close_app")
        self.assertIsNone(bridge.last_time)

    def test_errors_manual_stop_and_close_never_trigger_after_run_even_at_goal(self):
        bridge = self.bridge
        bridge.command("settings", {**DEFAULTS, "stop_at_level": 800, "after_run": "shutdown"})
        for reason in ("Stopped: Roblox not found", "Stopped: error: unavailable", "Stopped: disconnected",
                       "Stopped: Senzu inventory empty", "Stopped: training wouldn't start (no training points left?)",
                       "Stopped: not in the Gravity Chamber (the daily training limit may be used up)", "Stopped: unknown failure"):
            bridge.command("start", {})
            bridge.bot.stats["level"] = 800
            bridge.bot.on_stop(reason)
            self.assertFalse(bridge.last_run["completed"])
            self.assertIsNone(bridge.pending_action)
        bridge.command("start", {})
        bridge.bot.stats["level"] = 800
        bridge.command("stop", {})
        self.assertIsNone(bridge.pending_action)
        bridge.command("start", {})
        bridge.bot.stats["level"] = 800
        self.assertTrue(bridge.close())
        self.assertIsNone(bridge.pending_action)

    def test_unreached_or_missing_goals_do_not_complete(self):
        bridge = self.bridge
        bridge.command("settings", {**DEFAULTS, "stop_at_level": 800, "stop_after_minutes": 30, "after_run": "shutdown"})
        for stats in ({}, {"started": time.time(), "level": 799}, {"level": None}, {"level": "800"}):
            bridge.command("start", {})
            bridge.bot.stats = stats
            bridge.bot.on_stop("Stopped")
            self.assertFalse(bridge.last_run["completed"])
            self.assertIsNone(bridge.pending_action)

    def test_training_stats_pass_through_and_elapsed_is_added_without_mutating_core(self):
        reported = {"started": 1000, "level": 500, "senzus": 3, "refills": 1, "pulls": 20,
                    "gravity": 500, "exp_mult": 212.13, "drain": 230, "points_left": 0, "senzu_left": None}
        with patch("core_server.time.time", return_value=1010):
            self.assertEqual(Bridge._stats(types.SimpleNamespace(stats=reported)),
                             {**{key: value for key, value in reported.items() if key != "started"}, "elapsed": 10})
        self.assertEqual(reported["started"], 1000)
        for started in (None, "1000", True, float("nan"), float("inf")):
            self.assertIsNone(Bridge._stats(types.SimpleNamespace(stats={"started": started}))["elapsed"])

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
            self.assertTrue(run.call_args.args[0][0].lower().endswith(r"\system32\shutdown.exe"))  # full path, no search-path lookup
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
            self.bridge.set_status("Training: Health")
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


class CoreImportTests(unittest.TestCase):
    def test_load_core_returns_training_module_in_the_same_position(self):
        training, vision, window = types.ModuleType("gc_train"), types.ModuleType("gc_vision"), types.ModuleType("window")
        legacy = types.ModuleType("gc_bot")
        with patch.dict(sys.modules, {"gc_train": training, "gc_bot": legacy, "gc_vision": vision, "window": window}), patch.object(sys, "path", list(sys.path)):
            self.assertEqual(load_core(), (training, vision, window))


BUILD = Path(tempfile.gettempdir())

if __name__ == "__main__":
    unittest.main()
