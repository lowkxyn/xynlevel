"""MenuDriver against recorded frames, with input faked.

run: python -I tests/test_menu.py
"""

import pytest
import sys
from pathlib import Path
from unittest.mock import patch

import cv2

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import gc_menu  # noqa: E402

gc_menu.time.sleep = lambda s: None
# test_loop swaps MenuDriver for a fake while it runs; keep the real one.
REAL_DRIVER = gc_menu.MenuDriver


@pytest.fixture(autouse=True)
def _real_driver(monkeypatch):
    monkeypatch.setattr(gc_menu, "MenuDriver", REAL_DRIVER)
FRAMES = ROOT / "analysis" / "buy" / "frames"
OWNED_LIST = cv2.imread(str(ROOT / "live" / "owned_list.png"))            # owned ults, 4x Kame on row 1
PICKER = cv2.imread(str(FRAMES / "B_0018.25_slot_picker_7_old_move_8_empty.png"))
SHOP_LIST = cv2.imread(str(FRAMES / "B_0009.25_ultimate_shop_affordable.png"))
SKILLS = cv2.imread(str(FRAMES / "B_0015.25_skills_ultimate_category.png"))


class Fake:
    def __init__(self, frames, stop_after=None):
        self.frames, self.actions, self.grabs, self.stop_after = frames, [], 0, stop_after
        self.after_click = None

    def grab(self):
        self.grabs += 1
        if self.after_click is not None and any(a[0] == "click" for a in self.actions):
            return self.after_click
        return self.frames[min(self.grabs - 1, len(self.frames) - 1)]

    def driver(self):
        return REAL_DRIVER(
            grab=self.grab,
            click=lambda x, y: self.actions.append(("click", x, y)),
            park=lambda x, y: None,
            scroll=lambda n: self.actions.append(("scroll", n)),
            stopped=lambda: self.stop_after is not None and self.grabs >= self.stop_after,
        )


def test_access_denied_box_seen_and_not_confused_with_leave_prompt():
    denied = cv2.imread(str(ROOT / "live" / "access_denied_full.png"))  # from the 2026-10-23 recording
    assert gc_menu.access_denied(denied)
    assert not gc_menu.access_denied(SHOP_LIST) and not gc_menu.access_denied(PICKER)


def test_shop_search_turns_back_at_first_locked_row():
    # Kame bought, "???" rows below: no scrolling down to the end of the list, one look upwards.
    locked = cv2.imread(str(FRAMES / "B_0011.50_purchased_balance0_transient_warning.png"))
    fake = Fake([locked])
    hit = fake.driver().search("row_kame", end_below=lambda f: gc_menu.find(f, "row_locked", gc_menu.LIST_BOX))
    assert hit is None, hit
    assert fake.actions == [("scroll", 1)], fake.actions


def test_shop_search_finds_move_shown_above_locks():
    fake = Fake([SHOP_LIST])
    hit = fake.driver().search("row_kame", end_below=lambda f: gc_menu.find(f, "row_locked", gc_menu.LIST_BOX))
    assert hit and abs(hit[1] - 486) < 6 and fake.actions == [], (hit, fake.actions)


def test_interrupted_sends_nothing_more():
    fake = Fake([SKILLS], stop_after=3)  # menu "open" frames, then focus is lost
    gc_menu.menu_open = lambda f: True
    result = fake.driver().buy_move("kame")
    assert result == "interrupted", result
    clicks_after = [a for a in fake.actions]
    assert len(clicks_after) <= 1, clicks_after


def test_no_blind_second_click_when_picker_already_open():
    fake = Fake([OWNED_LIST] * 4)
    fake.after_click = PICKER  # the first click already opened the 7)/8) picker
    gc_menu.menu_open = lambda f: True
    driver = fake.driver()
    driver.section_page = lambda icon, pages: "title_ultimate"
    driver.equip_move("kame", 8, replace=False)
    row_clicks = [a for a in fake.actions if a[0] == "click" and abs(a[2] - 486) < 15]
    assert len(row_clicks) == 1, fake.actions  # only the first click on the move row
    assert ("click", 296, 548) in fake.actions, "then picks slot 8 (Empty)"


def test_does_not_buy_if_row_moved():
    moved = SHOP_LIST.copy()
    moved[460:520] = 0  # after clicking, the row is gone (list re-sorted / animating)
    fake = Fake([SHOP_LIST] * 3)
    fake.after_click = moved
    gc_menu.menu_open = lambda f: True
    driver = fake.driver()
    driver.section_page = lambda icon, pages: "title_ultimate"
    driver.wait = lambda check, timeout=3.0: True  # pretend Preview opened
    result = driver.buy_move("kame")
    assert "not buying" in result, result
    assert not any(a == ("click", *gc_menu.BUY_BUTTON) for a in fake.actions), fake.actions


def test_slow_menu_open_stretches_timeouts():
    REAL_DRIVER.lag = 1.0
    REAL_DRIVER._learn_lag(1.4)  # 4x the normal open time
    slow = REAL_DRIVER.lag
    for _ in range(10):
        REAL_DRIVER._learn_lag(0.1)  # fast again: drifts back to normal, never below 1
    fast = REAL_DRIVER.lag
    REAL_DRIVER.lag = 1.0
    assert slow > 2 and 1.0 <= fast < 1.01, (slow, fast)


def test_lag_ignores_invalid_samples():
    with patch.object(REAL_DRIVER, "lag", 2.0):
        for seconds in (0, -1, float("nan"), float("inf"), -float("inf")):
            REAL_DRIVER._learn_lag(seconds)
            assert REAL_DRIVER.lag == 2.0, (seconds, REAL_DRIVER.lag)


def test_lag_huge_finite_sample_stays_capped():
    with patch.object(REAL_DRIVER, "lag", 1.0):
        for _ in range(20):
            REAL_DRIVER._learn_lag(1e300)
        assert 1 <= REAL_DRIVER.lag <= gc_menu.LAG_CAP


def test_move_name_normalisation():
    assert gc_menu._plain("  Final  Explosion! ") == "finalexplosion"
    assert gc_menu.same_move(" Kame  hameha ", "Kamehameha")
    assert not gc_menu.same_move("Kamehameba", "Kamehameha"), "unconfirmed OCR typos must not match another move"
    assert not gc_menu.same_move("7) Kamehameha", "Kamehameha"), "only picker parsing strips slot numbers"
    for read in (None, "", " ", "???"):
        assert not gc_menu.same_move(read, "!!!"), read


def test_picker_names_and_empty_whitespace():
    for text, expected in (("7) Kamehameha", "Kamehameha"), (" 8 ) Empty ", ""),
                           (" 7) Final\n  Explosion ", "Final Explosion"), ("", ""), ("8) eMpTy", "")):
        with patch.object(gc_menu.gc_read, "ocr", return_value=text):
            assert gc_menu.picker_slot_name(None, 7) == expected, text


if __name__ == "__main__":
    failed = 0
    original = gc_menu.menu_open
    for name, test in [(n, f) for n, f in globals().items() if n.startswith("test_")]:
        gc_menu.menu_open = original
        try:
            test()
            print("PASS", name)
        except AssertionError as error:
            failed += 1
            print("FAIL", name, error)
    sys.exit(1 if failed else 0)



def test_price_colour_by_hue_not_brightness():
    """Red = can't pay, white = can, the death-dimmed grey white still counts as white, and an
    empty/dark price is 'can't tell yet', not 'too poor' (a slow PC read the dimmed price as too poor)."""
    import numpy as np
    def price(bgr):
        frame = np.zeros((1080, 1920, 3), np.uint8)
        frame[478:490, gc_menu.PRICE_X[0] + 10:gc_menu.PRICE_X[0] + 60] = bgr
        return gc_menu.price_affordable(frame, 484)
    assert price((40, 40, 220)) is False
    assert price((235, 235, 235)) is True
    assert price((150, 150, 150)) is True
    assert price((0, 0, 0)) is None
