"""HUD parsing with synthetic frames and fake OCR. Run: python -I tests/test_read.py."""

import math
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import gc_read


class ReadTests(unittest.TestCase):
    def setUp(self):
        self.frame = np.zeros((1080, 1920, 3), np.uint8)
        self.engine = patch.object(gc_read, "_ocr_engine", side_effect=AssertionError("OCR must be faked"))
        self.engine.start()
        self.addCleanup(self.engine.stop)

    def test_amount_valid_forms(self):
        for text, expected in (("1,250", 1250), ("43.7M", 43700000), ("O.5K", 500),
                               (" 2.5m ", 2500000), ("1b", 1e9), ("2T", 2e12), ("0", 0)):
            with self.subTest(text=text):
                self.assertEqual(gc_read.parse_amount(text), expected)

    def test_amount_rejects_junk_and_malformed_decimals(self):
        for text in ("", " ", "1.2.3M", "43.7M junk", "nan", "inf", "-1", "."):
            with self.subTest(text=text):
                self.assertIsNone(gc_read.parse_amount(text))

    def test_amount_rejects_overflow(self):
        for text in ("9" * 400, "9" * 305 + "T"):
            with self.subTest(length=len(text)):
                self.assertIsNone(gc_read.parse_amount(text))
        self.assertTrue(math.isfinite(gc_read.parse_amount("9" * 100 + "T")))

    def test_level_label_and_ocr_digits(self):
        for text, expected in (("Lvl: 1,250", 1250), ("Lvl 203", 203), ("Lvl: I2l", 121),
                               ("203", 203), ("", None), ("Lvl:", None)):
            with self.subTest(text=text), patch.object(gc_read, "ocr", return_value=text):
                self.assertEqual(gc_read.level(self.frame), expected)

    def test_xp_slash_and_no_slash(self):
        for text in ("25 / 100", "25 100"):
            with self.subTest(text=text), patch.object(gc_read, "ocr", return_value=text), \
                    patch.object(gc_read, "xp_bar_fraction", return_value=0.25):
                self.assertEqual(gc_read.xp(self.frame), (25, 100, text))

    def test_xp_misread_slash_uses_bar(self):
        for separator in ("1", "l", "I"):
            text = "43.7M " + separator + "88.1M"
            with self.subTest(separator=separator), patch.object(gc_read, "ocr", return_value=text), \
                    patch.object(gc_read, "xp_bar_fraction", return_value=43.7 / 88.1):
                self.assertEqual(gc_read.xp(self.frame), (43700000, 88100000, text))

    def test_xp_invalid_or_impossible_readings(self):
        for text in ("", "25", "25 100 extra", "25 / 0", "101 / 100", "x / 100", "9" * 400 + " / 100"):
            with self.subTest(text=text[:30]), patch.object(gc_read, "ocr", return_value=text):
                self.assertEqual(gc_read.xp(self.frame), (None, None, text))

    def test_xp_empty_and_full_bars(self):
        for text, bar, expected in (("0 / 100", 0, (0, 100)), ("100 / 100", 1, (100, 100))):
            with self.subTest(bar=bar), patch.object(gc_read, "ocr", return_value=text), \
                    patch.object(gc_read, "xp_bar_fraction", return_value=bar):
                self.assertEqual(gc_read.xp(self.frame)[:2], expected)

    def test_xp_bar_fraction_endpoints(self):
        self.assertEqual(gc_read.xp_bar_fraction(self.frame), 0)
        self.frame[gc_read.XP_BAR_Y, gc_read.XP_BAR_X0:gc_read.XP_BAR_X1 + 1] = (0, 200, 255)
        self.assertEqual(gc_read.xp_bar_fraction(self.frame), 1)

    def test_hotbar_whitespace(self):
        # ocr() already strips the outside of its result; hotbar collapses internal whitespace.
        with patch.object(gc_read, "ocr", return_value="Kamehameha\t  x4"):
            self.assertEqual(gc_read.hotbar(self.frame), {slot: "Kamehameha x4" for slot in gc_read.HOTBAR_Y})
        with patch.object(gc_read, "ocr", return_value=""):
            self.assertEqual(set(gc_read.hotbar(self.frame).values()), {""})


if __name__ == "__main__":
    unittest.main()
