"""Reading text off the HUD and menus with the OCR engine built into Windows.

Coordinates are game-area pixels at 1920x1080. Small game text is upscaled before OCR because
Windows OCR misses text under ~20 px tall.

HUD and menu samples: Omar Toketa <omar.toketa47@proton.me>
"""

import asyncio
import math
import re

import cv2
import numpy as np
from winrt.windows.graphics.imaging import BitmapPixelFormat, SoftwareBitmap
from winrt.windows.media.ocr import OcrEngine
from winrt.windows.storage.streams import DataWriter

LEVEL_BOX = (352, 82, 110, 24)       # "Lvl: 1251"
XP_BOX = (560, 82, 165, 24)          # "43.7M / 88.1M"
XP_BAR_Y, XP_BAR_X0, XP_BAR_X1 = 112, 365, 714   # gold fill row of the XP bar under the text
HOTBAR_X, HOTBAR_W = 1655, 235
HOTBAR_Y = {"T": 700, 1: 736, 2: 772, 3: 808, 4: 844, 5: 880, 6: 916, 7: 952, 8: 988}
HOTBAR_H = 26

_engine = None


def _ocr_engine():
    global _engine
    if _engine is None:
        _engine = OcrEngine.try_create_from_user_profile_languages()
    return _engine


def gold_only(frame, box):
    """Copy of frame with box reduced to black gold-text on white.

    The level/XP text is gold and sits straight on the 3D world, so any brightness threshold
    breaks over lit buildings or sky. Gold (red high, blue well below red) doesn't.
    """
    x, y, w, h = box
    crop = frame[y:y + h, x:x + w].astype(np.int16)
    blue, green, red = crop[:, :, 0], crop[:, :, 1], crop[:, :, 2]
    gold = (red > 130) & (green > 90) & (blue < red - 45)
    out = frame.copy()
    out[y:y + h, x:x + w] = np.where(gold[:, :, None], 0, 255).astype(np.uint8)
    return out


def ocr(frame, box, scale=4, binarize=True):
    """Text in box (x, y, w, h) of a BGR frame, lines joined by spaces."""
    result = _recognise(frame, box, scale, binarize)
    return " ".join(line.text for line in result.lines).strip()


def ocr_lines(frame, box, scale=4, binarize=True):
    """[(text, centre_x, centre_y)] per line, in frame coordinates."""
    x, y = box[0], box[1]
    lines = []
    for line in _recognise(frame, box, scale, binarize).lines:
        words = list(line.words)
        rects = [w.bounding_rect for w in words]
        left = min(r.x for r in rects)
        right = max(r.x + r.width for r in rects)
        top = min(r.y for r in rects)
        bottom = max(r.y + r.height for r in rects)
        # Undo the 20 px border and the upscale.
        lines.append((line.text, x + ((left + right) / 2 - 20) / scale, y + ((top + bottom) / 2 - 20) / scale))
    return lines


def _recognise(frame, box, scale, binarize):
    """
    binarize: game text is yellow/white, so it's bright in the red channel while the green and
    blue bars behind it aren't. Otsu on red gives black text on white, which OCR reads far better.
    """
    x, y, w, h = box
    crop = frame[y:y + h, x:x + w]
    if binarize:
        _, crop = cv2.threshold(crop[:, :, 2], 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
        crop = cv2.cvtColor(crop, cv2.COLOR_GRAY2BGR)
    crop = cv2.resize(crop, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
    crop = cv2.copyMakeBorder(crop, 20, 20, 20, 20, cv2.BORDER_REPLICATE)
    bgra = np.ascontiguousarray(cv2.cvtColor(crop, cv2.COLOR_BGR2BGRA))
    writer = DataWriter()
    writer.write_bytes(bgra.tobytes())
    bitmap = SoftwareBitmap.create_copy_from_buffer(writer.detach_buffer(), BitmapPixelFormat.BGRA8,
                                                    bgra.shape[1], bgra.shape[0])

    async def recognise():
        return await _ocr_engine().recognize_async(bitmap)

    return asyncio.run(recognise())


_SUFFIX = {"": 1, "K": 1e3, "M": 1e6, "B": 1e9, "T": 1e12}


def parse_amount(text):
    """'43.7M' -> 43700000.0, '1,250' -> 1250.0, junk -> None."""
    text = text.upper().replace("O", "0").replace("L", "1").replace("I", "1")
    match = re.fullmatch(r"\s*([\d.,]+)\s*([KMBT]?)\s*", text)
    if not match:
        return None
    try:
        amount = float(match.group(1).replace(",", "")) * _SUFFIX[match.group(2)]
        return amount if math.isfinite(amount) else None
    except ValueError:
        return None


def level(frame):
    text = ocr(gold_only(frame, LEVEL_BOX), LEVEL_BOX, scale=2, binarize=False)
    digits = re.sub(r"^\s*Lv[lI1]\s*:?\s*", "", text, flags=re.IGNORECASE)
    digits = digits.split(":")[-1].replace("l", "1").replace("I", "1")
    match = re.search(r"(\d[\d,]*)", digits)
    return int(match.group(1).replace(",", "")) if match else None


def xp_bar_fraction(frame):
    row = frame[XP_BAR_Y, XP_BAR_X0:XP_BAR_X1 + 1].astype(np.int16)
    gold = (row[:, 2] > 150) & (row[:, 1] > 100) & (row[:, 0] < row[:, 2] - 60)
    filled = np.where(gold)[0]
    return (filled.max() + 1) / len(row) if len(filled) else 0.0


def xp(frame):
    """(current, needed, raw text). Numbers are None if unreadable.

    OCR often reads the "/" as a "1" ("43.7M 188.1M"), so when there's no slash both readings of
    the second number are tried and the one matching how full the XP bar is wins.
    """
    text = ocr(gold_only(frame, XP_BOX), XP_BOX, scale=2, binarize=False)
    if "/" in text:
        first, second = text.split("/", 1)
        options = [second]
    else:
        parts = text.split()
        if len(parts) != 2:
            return None, None, text
        first, second = parts
        options = [second, second[1:]] if second[:1] in "1lI" else [second]
    current = parse_amount(first)
    readings = [(current, parse_amount(option)) for option in options]
    readings = [(c, n) for c, n in readings if c is not None and n and c <= n]
    if not readings:
        return None, None, text
    bar = xp_bar_fraction(frame)
    current, needed = min(readings, key=lambda r: abs(r[0] / r[1] - bar))
    return current, needed, text


def hotbar(frame):
    """{slot: move name or ''} for T and 1-8."""
    return {slot: hotbar_slot(frame, slot) for slot in HOTBAR_Y}


def hotbar_slot(frame, slot):
    """The move name in one hotbar slot, or ''. Exact while alive; the death screen's dimming garbles it."""
    y = HOTBAR_Y[slot]
    return re.sub(r"\s+", " ", ocr(frame, (HOTBAR_X, y - HOTBAR_H // 2, HOTBAR_W, HOTBAR_H)))
