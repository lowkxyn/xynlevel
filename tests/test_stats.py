"""gc_stats reading on saved Stats-panel frames (Windows OCR needed).

run: python -I tests/test_stats.py
"""

import sys
from pathlib import Path

import cv2
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import gc_stats  # noqa: E402

TOP = cv2.imread(str(ROOT / "live" / "stats_top_a.png"))            # level 267, 1260 points
KI_ROW = cv2.imread(str(ROOT / "live" / "stats_kicontrol_a.png"))   # scrolled: Ki Control 0.95x 3 -> 2.9
TOP_B = cv2.imread(str(ROOT / "live" / "stats_top_b.png"))          # 767 -> 843.6, 3842 -> 4226.1
if TOP is None or KI_ROW is None or TOP_B is None:
    # The screenshots show the account, so they stay private (live/ isn't published).
    pytest.skip("private stats screenshots not present", allow_module_level=True)


def test_header_points_and_spend_box():
    assert gc_stats.skill_points(TOP) == 1260
    assert gc_stats.skill_points(TOP_B) == 0
    assert gc_stats.spend_amount(TOP) == 1


def test_ki_control_row():
    multiplier, y = gc_stats.find_stat_row(KI_ROW, "Ki Control")
    assert multiplier == 0.95 and abs(y - 630) < 8, (multiplier, y)
    assert gc_stats.row_values(KI_ROW, y) == (3, 2.9)


def test_two_decimal_output_live():
    frame = cv2.imread(str(ROOT / "live" / "stats_kicontrol_lvl301.png"))  # "4 -> 3.85"
    multiplier, y = gc_stats.find_stat_row(frame, "Ki Control")
    assert gc_stats.row_values(frame, y) == (4, 3.85)


def test_rows_with_big_and_decimal_numbers():
    assert gc_stats.row_values(TOP, 671) == (71, 78)
    assert gc_stats.row_values(TOP_B, 668) == (767, 843.6)
    assert gc_stats.row_values(TOP_B, 730) == (3842, 4226.1)


def test_missing_row_and_empty_area():
    assert gc_stats.find_stat_row(TOP, "Ki Control") is None  # not scrolled into view
    assert gc_stats.row_values(TOP, 540) is None              # header, no row numbers


def test_reads_through_the_death_screen_dimming():
    # The menu is opened while dead, under the death fade (~76% brightness). Fixed thresholds
    # failed every read at 60%.
    for k in (0.76, 0.6, 0.5):
        dim = lambda frame: (frame * k).astype("uint8")
        assert gc_stats.skill_points(dim(TOP)) == 1260, k
        assert gc_stats.spend_amount(dim(TOP)) == 1, k
        assert gc_stats.row_values(dim(KI_ROW), 630) == (3, 2.9), k
        assert gc_stats.row_values(dim(TOP_B), 668) == (767, 843.6), k


def test_points_needed():
    assert gc_stats.points_needed(0.95, 3, 300) == 313   # 316 x 0.95 = 300.2
    assert gc_stats.points_needed(1.0, 300, 300) == 0
    assert gc_stats.points_needed(1.1, 400, 300) == 0     # already above: never negative
    assert gc_stats.points_needed(1.5, 0, 300) == 200     # exact division: no extra point


def test_misread_multiplier_is_caught():
    assert gc_stats.consistent(0.95, 4, 3.85) and gc_stats.consistent(0.95, 3, 2.9)
    assert gc_stats.consistent(1.1, 767, 843.6) and gc_stats.consistent(1.1, 3842, 4226.1)
    assert not gc_stats.consistent(0.5, 4, 3.85)       # "0.95x" read as "0.5"
    assert not gc_stats.consistent(0.95, 40, 3.85)     # input misread


def test_numbers_font_quirks():
    assert gc_stats.numbers("I26O") == [1260]
    assert gc_stats.numbers("71+78") == [71, 78]


if __name__ == "__main__":
    failed = 0
    for name, test in [(n, f) for n, f in globals().items() if n.startswith("test_")]:
        try:
            test()
            print("PASS", name)
        except AssertionError as error:
            failed += 1
            print("FAIL", name, error)
    sys.exit(1 if failed else 0)
