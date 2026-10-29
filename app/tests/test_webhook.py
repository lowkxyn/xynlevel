import json
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "python"))
import webhook  # noqa: E402

GOOD = "https://discord.com/api/webhooks/123456789012345678/" + "a" * 68
FAKE_SECRET_PATH = "/api/webhooks/123456789012345678/" + "a" * 68


class Validation(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.hook = webhook.Webhook(Path(self.folder.name) / "webhook.bin", post=lambda path, body: 204)

    def tearDown(self):
        self.folder.cleanup()

    def test_accepts_discord_variants_and_stores_only_the_path(self):
        for url in (GOOD, GOOD.replace("discord.com", "ptb.discord.com"), GOOD.replace("discord.com", "discordapp.com"),
                    "  " + GOOD + "  "):
            self.hook.configure({"url": url})
            self.assertEqual(self.hook._settings["url"], "https://discord.com" + FAKE_SECRET_PATH)

    def test_rejects_other_hosts_schemes_and_shapes(self):
        for url in ("http://discord.com/api/webhooks/123456789012345678/" + "a" * 68,
                    "https://discord.com.evil.example/api/webhooks/123456789012345678/" + "a" * 68,
                    "https://evil.example/https://discord.com/api/webhooks/1/2",
                    GOOD + "?thread_id=1", GOOD + "/extra", GOOD + "#x",
                    "https://user:pw@discord.com/api/webhooks/123456789012345678/" + "a" * 68,
                    "https://discord.com/api/webhooks/abc/" + "a" * 68, 123, None):
            with self.assertRaises(ValueError, msg=str(url)):
                self.hook.configure({"url": url})

    def test_cant_enable_without_url_or_with_bad_types(self):
        with self.assertRaises(ValueError):
            self.hook.configure({"enabled": True})
        with self.assertRaises(ValueError):
            self.hook.configure({"url": GOOD, "enabled": "yes"})
        with self.assertRaises(ValueError):
            self.hook.configure({"url": GOOD, "progress_minutes": 7})

    def test_file_is_encrypted_and_round_trips(self):
        self.hook.configure({"url": GOOD, "enabled": True, "progress_minutes": 10})
        raw = self.hook.path.read_bytes()
        self.assertNotIn(b"discord", raw)
        self.assertNotIn(b"aaaaaaaa", raw)
        again = webhook.Webhook(self.hook.path)
        self.assertEqual(again.snapshot(), {"configured": True, "enabled": True, "progress_minutes": 10, "status": "Ready"})

    def test_snapshot_never_contains_the_url(self):
        self.hook.configure({"url": GOOD, "enabled": True})
        self.assertNotIn("webhooks", json.dumps(self.hook.snapshot()))

    def test_corrupt_file_is_reported_not_crashing(self):
        self.hook.path.write_bytes(b"not dpapi")
        self.assertIn("couldn't be read", webhook.Webhook(self.hook.path).status)

    def test_clear_removes_the_file(self):
        self.hook.configure({"url": GOOD, "enabled": True})
        self.hook.clear()
        self.assertFalse(self.hook.path.exists())
        self.assertFalse(self.hook.snapshot()["configured"])


class Payload(unittest.TestCase):
    def test_embed_fields_and_no_mentions(self):
        body = webhook.payload("completed", "Reached the stop time", {"elapsed": 3725, "deaths": 41, "ults": 37, "blasts": 2}, 60)
        self.assertEqual(body["allowed_mentions"], {"parse": []})
        embed = body["embeds"][0]
        self.assertEqual(embed["title"], "Session finished")
        fields = {f["name"]: f["value"] for f in embed["fields"]}
        self.assertEqual(fields, {"Run time": "1h 2m", "Deaths": "41", "Ults fired": "37", "Ki blasts": "2", "GC time left": "1m 0s"})

    def test_level_field_when_levels_were_read(self):
        body = webhook.payload("completed", "Reached the stop time", {"elapsed": 60, "level": 203, "start_level": 178})
        fields = {f["name"]: f["value"] for f in body["embeds"][0]["fields"]}
        self.assertEqual(fields["Level"], "178 → 203 (+25)")
        body = webhook.payload("completed", "Reached the stop time", {"elapsed": 60})
        self.assertNotIn("Level", {f["name"] for f in body["embeds"][0]["fields"]})

    def test_bad_numbers_dont_break_the_embed(self):
        body = webhook.payload("stopped", "Stopped", {"elapsed": float("nan"), "deaths": "x", "ults": -5, "blasts": 1e30})
        values = [f["value"] for f in body["embeds"][0]["fields"]]
        self.assertEqual(values[:4], ["0m 0s", "0", "0", "10000000"])

    def test_unknown_kind_rejected(self):
        with self.assertRaises(ValueError):
            webhook.payload("@everyone")


class Classify(unittest.TestCase):
    def test_raw_error_text_never_becomes_the_label(self):
        kind, label = webhook.classify(r"Stopped: error: [Errno 2] C:\Users\someone\secret.txt", False)
        self.assertEqual((kind, label), ("attention", "Macro error"))

    def test_known_reasons(self):
        cases = {"Stopped: 59s (59s) left": ("completed", "Reached the stop time"),
                 "Stopped: Roblox disconnected you (idle kick, lost connection or server kick)": ("attention", "Roblox disconnected"),
                 "Stopped: slot 7 is empty. Put an ult there or pick Auto": ("attention", "Ult slot empty"),
                 "Stopped": ("stopped", "Stopped")}
        for reason, expected in cases.items():
            self.assertEqual(webhook.classify(reason, False), expected, reason)
        self.assertEqual(webhook.classify("Stopped: error: x", True), ("stopped", "Stopped by you"))


class Delivery(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.sent = []
        self.status = 204
        self.hook = webhook.Webhook(Path(self.folder.name) / "webhook.bin", post=self.post)

    def tearDown(self):
        self.folder.cleanup()

    def post(self, path, body):
        self.sent.append((path, body))
        return self.status

    def drain(self):
        self.hook._queue.join()

    def test_off_sends_nothing_but_test_still_works(self):
        self.hook.configure({"url": GOOD, "enabled": False})
        self.assertFalse(self.hook.send("completed", "x"))
        self.assertTrue(self.hook.send("test"))
        self.drain()
        self.assertEqual(len(self.sent), 1)
        self.assertEqual(self.sent[0][0], FAKE_SECRET_PATH)

    def test_rate_limit_pauses_and_deleted_hook_is_explained(self):
        self.hook.configure({"url": GOOD, "enabled": True})
        self.status = 429
        self.hook.send("stopped", "Stopped")
        self.drain()
        self.assertFalse(self.hook.send("stopped", "Stopped"))
        self.assertIn("rate limit", self.hook.status)
        self.hook.configure({"url": GOOD.replace("a" * 68, "b" * 68)})  # new hook clears the pause
        self.status = 404
        self.hook.send("stopped", "Stopped")
        self.drain()
        self.assertIn("deleted", self.hook.status)

    def test_progress_interval(self):
        self.hook.configure({"url": GOOD, "enabled": True, "progress_minutes": 5})
        self.hook.begin_run()
        self.hook.maybe_progress({}, None)
        self.drain()
        self.assertEqual(self.sent, [])
        self.hook._next_progress = time.monotonic() - 1
        self.hook.maybe_progress({"elapsed": 300}, 6900)
        self.drain()
        self.assertEqual(self.sent[0][1]["embeds"][0]["title"], "Levelling in progress")


class Review2(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.sent = []
        self.hook = webhook.Webhook(Path(self.folder.name) / "webhook.bin", post=lambda p, b: (time.sleep(0.2), self.sent.append(b), 204)[2])

    def tearDown(self):
        self.folder.cleanup()

    def test_turning_progress_on_mid_run_waits_a_full_interval(self):
        self.hook.configure({"url": GOOD, "enabled": True, "progress_minutes": 0})
        self.hook.begin_run()
        self.hook.configure({"progress_minutes": 5})
        self.hook.maybe_progress({}, None)
        self.assertTrue(self.hook.flush(1))
        self.assertEqual(self.sent, [])

    def test_flush_waits_for_queued_report(self):
        self.hook.configure({"url": GOOD, "enabled": True})
        self.hook.send("completed", "Reached the stop time")
        self.assertTrue(self.hook.flush(2))
        self.assertEqual(len(self.sent), 1)


if __name__ == "__main__":
    unittest.main()
