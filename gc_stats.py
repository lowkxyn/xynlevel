"""Skill points into one stat (Ki Control) through Customize > Stats. Menus only stay open while
dead, so this runs on the death screen, like shopping.

The Stats list: a header (Level, Skill Points), a "Spend Amount" box, then one row per stat:
"Ki Control 0.95x   3 -> 2.9  [+]". Input is what points bought, output = input x race multiplier.
The [+] on a row spends Spend Amount points into it. Spent points are permanent, so every step is
read back before the next one, and anything unreadable stops without clicking.
"""

import math
import re
import time

import cv2
import numpy as np

import gc_menu
import gc_read

CUSTOMIZE_PAGES = ("title_customize", "title_stats")
POINTS_BOX = (150, 520, 360, 45)     # "Skill Points 1260", list scrolled to the top
SPEND_ROW = (90, 590, 360, 30)       # "Spend Amount [ 1 ]", list scrolled to the top
SPEND_CLICK = (388, 605)
PLUS_X = 484                         # the [+] button on every row
NUMBERS_X = (320, 470)               # "3 -> 2.9" on a row
NAMES_BOX = (80, 450, 250, 340)
MAX_ROUNDS = 3                       # spend, read back, top up the rounding shortfall


def numbers(text):
    # The game font draws 1 like a capital I; OCR reads the arrow as "+" or a space.
    return [float(n) for n in re.findall(r"\d+(?:\.\d+)?", text.replace("I", "1").replace("l", "1").replace("O", "0"))]


def _ocr_mask(frame, box, mask_fn, scale=3):
    """OCR only the pixels mask_fn picks, cropped tight and padded: Windows OCR misses short
    numbers on the green bar otherwise."""
    x, y, w, h = box
    crop = frame[y:y + h, x:x + w].astype(np.int16)
    text_pixels = mask_fn(crop)
    ys, xs = np.nonzero(text_pixels)
    if len(xs) == 0:
        return ""
    glyphs = np.where(text_pixels[ys.min():ys.max() + 1, xs.min():xs.max() + 1], 0, 255).astype(np.uint8)
    glyphs = cv2.resize(glyphs, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
    glyphs = cv2.cvtColor(cv2.copyMakeBorder(glyphs, 60, 60, 120, 120, cv2.BORDER_CONSTANT, value=255), cv2.COLOR_GRAY2BGR)
    return gc_read.ocr(glyphs, (0, 0, glyphs.shape[1], glyphs.shape[0]), scale=1, binarize=False)


def _dim(values):
    """How much the screen is darkened (1.0 = normal), from the brightest text in the crop. The
    menu opened on the death screen is dimmed (white text at ~194); at 60% every fixed
    threshold below missed the text. Thresholds are scaled by this."""
    return float(np.clip(np.percentile(values, 99.5) / 230, 0.4, 1.0))


def _grey_white(crop):
    # Row numbers: grey input, white output, both unsaturated; the bar behind is saturated green.
    k = _dim(crop.min(axis=2))
    return (crop.min(axis=2) > 110 * k) & (crop.max(axis=2) - crop.min(axis=2) < 60 * k)


def _warm(crop):
    # Gold labels and the pale-yellow box text; red channel bright, the green bar's isn't.
    return crop[:, :, 2] > 150 * _dim(crop[:, :, 2])


def _gold(crop):
    k = _dim(crop[:, :, 2])
    return (crop[:, :, 2] > 150 * k) & (crop[:, :, 0] < 120 * k)


def row_values(frame, y):
    """(input, output) on the stat row centred at y, or None. Two zooms must agree; a third is
    tried because a lone "1 -> 1" often reads as nothing at one zoom (seen at level 31)."""
    box = (NUMBERS_X[0], int(y) - 16, NUMBERS_X[1] - NUMBERS_X[0], 32)
    reads = []
    for scale in (3, 4, 5):
        found = numbers(_ocr_mask(frame, box, _grey_white, scale))
        if len(found) == 2:
            if found in reads:
                return tuple(found)
            reads.append(found)
    return None


def find_stat_row(frame, name):
    """(multiplier, y) of the row called `name`, or None."""
    for text, _, y in gc_read.ocr_lines(frame, NAMES_BOX, scale=3, binarize=False):
        if text.lower().startswith(name.lower()):
            found = numbers(text[len(name):])
            if found and 0.1 <= found[0] <= 10:
                return found[0], y
    return None


def skill_points(frame):
    """Free skill points from the header. The label is read too: a lone number is often missed."""
    text = _ocr_mask(frame, POINTS_BOX, _gold)
    if not text.lower().startswith("skill"):
        return None
    found = numbers(text.split()[-1].replace("o", "0"))  # last word: "Points" itself has an o
    return int(found[0]) if len(found) == 1 else None


def spend_amount(frame):
    """The number in the Spend Amount box, read together with its label for the same reason."""
    text = _ocr_mask(frame, SPEND_ROW, _warm)
    if not text.lower().startswith("spend amount"):
        return None
    found = numbers(text[12:])
    return int(found[0]) if len(found) == 1 else None


def consistent(multiplier, current_input, current_output):
    """The row's own numbers agree with its multiplier. Both are rounded on screen (767 x "1.1"
    shows 843.6), hence the slack."""
    return abs(current_input * multiplier - current_output) <= 0.06 + 0.005 * current_output


def points_needed(multiplier, current_input, target_output):
    """Input points still to buy for output >= target. The panel rounds output to 0.1, so the
    read-back after spending decides whether one more is needed."""
    return max(0, math.ceil(target_output / multiplier - 1e-9) - int(current_input))


class StatSpender:
    """driver: gc_menu.MenuDriver. type_text(str) types into the focused box; press(key) taps a key."""

    def __init__(self, driver, type_text, press, say=lambda text: None):
        self.driver, self.type_text, self.press, self.say = driver, type_text, press, say

    def _to_top(self):
        # Done when the header's Skill Points read, not when the list stops moving: on a slow PC a scroll
        # sometimes didn't register at all, which looked like "already at the top" (level 141).
        d = self.driver
        for _ in range(12):
            if skill_points(d.frame()) is not None:
                return
            d._park(*gc_menu.LIST_SCROLL_POINT)
            d._scroll(5)
            time.sleep(0.25 * gc_menu.MenuDriver.lag)

    def _scroll_to_row(self, name):
        """Scroll down from the top until the row shows; (multiplier, y, frame) or None."""
        d = self.driver
        self._to_top()
        for _ in range(8):
            frame = d.frame()
            row = find_stat_row(frame, name)
            if row:
                time.sleep(0.15)  # let the list stop sliding, then read the row where it settled
                frame = d.frame()
                row = find_stat_row(frame, name)
                if row:
                    return row[0], row[1], frame
            before = d._list_pixels(frame)
            d._park(*gc_menu.LIST_SCROLL_POINT)
            d._scroll(-2)
            time.sleep(0.2 * gc_menu.MenuDriver.lag)
            if np.abs(d._list_pixels(d.frame()) - before).mean() <= 2:
                return None
        return None

    def open_stats(self):
        d = self.driver
        if not d.open_menu():
            return "error: menu didn't open"
        page = d.section_page(gc_menu.CUSTOMIZE_ICON, CUSTOMIZE_PAGES)
        if page is None:
            return "error: Customize didn't open"
        if page == "title_customize":
            # One retry: the first live try clicked while the remembered-scroll list was still sliding.
            if not (d.open_row("row_stats", "title_stats") or d.open_row("row_stats", "title_stats")):
                return "error: Stats didn't open"
        return None

    def read(self, name):
        """{"points", "multiplier", "input", "output"} for stat `name`, or an error string."""
        self._to_top()
        points = skill_points(self.driver.frame())
        row = self._scroll_to_row(name)
        if row is None:
            return f"error: {name} row not found"
        multiplier, y, frame = row
        values = row_values(frame, y)
        if points is None or values is None:
            return f"error: couldn't read {name} ({points}, {values})"
        if not consistent(multiplier, *values):
            # e.g. "0.95x" misread as "0.5": planning with it would spend ~2x the points.
            return f"error: {name} reads {multiplier}x but {values[0]:g} -> {values[1]:g}; not trusting it"
        return {"points": points, "multiplier": multiplier, "input": values[0], "output": values[1], "y": y}

    def _set_spend_amount(self, amount):
        d = self.driver
        self._to_top()
        d.click(*SPEND_CLICK)
        time.sleep(0.3 * gc_menu.MenuDriver.lag)  # 0.15 s was too soon on a slow PC: the number didn't take
        # One key at a time, each behind the driver's focus/stop check: a missed box click would
        # otherwise send the digits and Enter to the game or another window.
        for key in ["end"] + ["backspace"] * 6 + list(str(amount)) + ["enter"]:
            d._guard()
            self.press(key)
            time.sleep(0.03)
        time.sleep(0.2)
        if d.wait(lambda f: spend_amount(f) == amount, timeout=1.5) is not None:
            return True
        self.say(f"Spend Amount box reads {spend_amount(d.frame())}, wanted {amount}")
        return False

    def spend_to(self, name, target_output, confirm=True):
        """Spend points into `name` until its output reaches target_output.

        Returns (result, detail): "done" (already there or reached), "would_spend" (confirm=False),
        "too_few_points", or "error: ...". detail is a short sentence for the status line.
        """
        try:
            error = self.open_stats()
            if error:
                return error, error
            for _ in range(MAX_ROUNDS):
                stat = self.read(name)
                if isinstance(stat, str):
                    return stat, stat
                if stat["output"] >= target_output:
                    return "done", f"{name} {stat['input']:g} -> {stat['output']:g} (target {target_output:g})"
                need = points_needed(stat["multiplier"], stat["input"], target_output)
                need = max(need, 1)  # output still below target after rounding: one more
                plan = (f"{need} points into {name}: input {stat['input']:g} -> {stat['input'] + need:g}, "
                        f"output ~{(stat['input'] + need) * stat['multiplier']:.1f} ({stat['points']} points free)")
                if not confirm:
                    return "would_spend", plan
                if stat["points"] < need:
                    return "too_few_points", plan
                if not self._set_spend_amount(need):
                    return "error: Spend Amount didn't take the number", plan
                row = self._scroll_to_row(name)
                if row is None:
                    return f"error: {name} row lost before spending", plan
                self.say(f"Spending {plan}")
                self.driver.click(PLUS_X, int(row[1]))
                before = stat["input"]
                # Read back: the input must have gone up by exactly `need`.
                deadline = time.monotonic() + 2.0 * gc_menu.MenuDriver.lag
                values = None
                while time.monotonic() < deadline:
                    time.sleep(0.15)
                    values = row_values(self.driver.frame(), row[1])
                    if values and values[0] != before:
                        break
                if not values or values[0] != before + need:
                    return f"error: {name} input read {values} after spending {need} (was {before:g})", plan
            return "error: target not reached after 3 rounds", ""
        except gc_menu.Interrupted:
            return "interrupted", "interrupted"
