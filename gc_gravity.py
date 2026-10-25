"""Reading and setting GC gravity through the Tab training panel.

Ported from XynMacro (same label position, templates and click-confirm loop). The control
steps +10 per click and wraps 100 -> 0, so any target is reached by clicking forward.
"""

import time

import cv2
import numpy as np

from gc_vision import ASSETS

LABEL_BOX = (456, 316, 142, 51)   # "Gravity: 100G"
CLICK_POINT = (527, 342)
PARK_POINT = (700, 342)           # just right of the label: the cursor drawn over it breaks the read
MATCH_MIN = 0.80
MATCH_MARGIN_MIN = 0.035
STEPS = range(0, 101, 10)

_TEMPLATES = None


DIGIT_SIZE = (10, 14)


def _templates():
    """Per-digit templates for the bot-room label, captured by tools/calibrate_gravity.py.

    XynMacro's whole-label templates don't fit here: its stat-training control shows a bold "0G",
    the bot-room panel a thin serif "Gravity: 0G".
    """
    global _TEMPLATES
    if _TEMPLATES is None:
        folder = ASSETS / "gravity_digits"
        _TEMPLATES = {d: cv2.imread(str(folder / f"{d}.png"), cv2.IMREAD_GRAYSCALE).astype(np.float32)
                      for d in range(10) if (folder / f"{d}.png").exists()}
    return _TEMPLATES


def _mask(frame):
    x, y, w, h = LABEL_BOX
    bgr = frame[y:y + h, x:x + w, :3].astype(np.int16)
    low = bgr.min(axis=2)
    return ((low > 190) & (bgr.max(axis=2) - low < 55)).astype(np.uint8)


def number_glyphs(frame):
    """The digit glyphs of "Gravity: NG", left to right, or None if the label isn't there.

    The rightmost tall blob is the G; the digits are the blobs packed tight to its left. The
    space after the colon is the first wide gap.
    """
    count, _, stats, _ = cv2.connectedComponentsWithStats(_mask(frame), 8)
    blobs = sorted((x, y, w, h) for x, y, w, h, area in stats[1:count] if h >= 7 and area >= 12)
    if len(blobs) < 4:
        return None
    mask = _mask(frame)
    digits = []
    right_edge = blobs[-1][0]  # left edge of the G
    for x, y, w, h in reversed(blobs[:-1]):
        if right_edge - (x + w) > 4:
            break
        digits.append(cv2.resize(mask[y:y + h, x:x + w] * 255, DIGIT_SIZE, interpolation=cv2.INTER_AREA))
        right_edge = x
    digits.reverse()
    return digits if 1 <= len(digits) <= 3 else None


def read(frame):
    """(value or None, control_visible). value is None when the panel is open but unreadable."""
    glyphs = number_glyphs(frame)
    if glyphs is None:
        return None, False
    templates = _templates()
    if len(templates) < 10:
        return None, True
    text = ""
    for glyph in glyphs:
        scores = {d: float(np.abs(glyph.astype(np.float32) - t).mean()) for d, t in templates.items()}
        best = min(scores, key=scores.get)
        if scores[best] > 60:
            return None, True
        text += str(best)
    value = int(text)
    return (value, True) if value in STEPS else (None, True)


def _wait_read(grab, park, seconds=2.0):
    deadline = time.monotonic() + seconds
    value, visible = None, False
    while time.monotonic() < deadline:
        time.sleep(0.1)
        park(*PARK_POINT)
        value, visible = read(grab())
        if value is not None:
            break
    return value, visible


def set_gravity(target, grab, click, park, tap, stopped):
    """Open the training panel, click the gravity control until it reads `target`, close the panel.

    grab() -> frame, click(x, y) and park(x, y) take game-area coords, tap(key) presses a key,
    stopped() -> True to abort (no further input is sent, not even the closing Tab). Returns (ok, message).
    """
    tap("tab")
    value, visible = _wait_read(grab, park)
    if value is None and not visible:
        # The panel may already have been open, so that Tab closed it. One more try.
        tap("tab")
        value, visible = _wait_read(grab, park)
    if value is None:
        if visible:
            tap("tab")
        return False, "Couldn't read the gravity control (panel didn't open or was covered)"

    start = value
    clicks = 0
    while value != target:
        if stopped():
            return False, "Gravity change interrupted"
        if clicks >= 14:  # a full lap is 11 clicks; extra allows a few that didn't register
            break
        click(*CLICK_POINT)
        clicks += 1
        park(*PARK_POINT)
        deadline = time.monotonic() + 0.8
        while time.monotonic() < deadline:
            time.sleep(0.05)
            observed, visible = read(grab())
            if not visible:
                return False, "Gravity panel closed (died while changing gravity?)"
            # Accept any new step: a click that registered twice is still progress, and the
            # loop keeps going forward round the wrap until it lands on the target.
            if observed is not None and observed != value:
                value = observed
                break
    if stopped():
        return False, "Gravity change interrupted"
    tap("tab")
    if value != target:
        return False, f"Gravity stopped at {value}G"
    return True, f"Gravity {start}G -> {value}G"
