"""Screen reading for the GC bot room.

Every box is in 1920x1080 game-area coordinates (the size Set window gives Roblox),
measured from the 2026-10-21 clips. Boxes are (x, y, width, height).
"""

from pathlib import Path

import cv2
import numpy as np

ASSETS = Path(__file__).parent / "assets"

RESPAWN_BUTTON_BOX = (700, 535, 520, 30)
OTHER_WORLD_BUTTON_BOX = (700, 588, 520, 30)
DEATH_STRIP_BOX = (720, 470, 480, 40)
RESPAWN_POINT = (960, 550)
HUD_LABELS_BOX = (160, 128, 24, 62)  # the green HP/KI/FR tags; grey or gone while dead/loading
TIME_LIMIT_BOX = (470, 60, 150, 33)  # digits only, right of "Time Limit:"
KI_BAR_BOX = (195, 158, 495, 10)
HOTBAR_SLOT1_Y = 736
HOTBAR_SLOT_SPACING = 36
HOTBAR_BAR_X = (1665, 1885)

# Ready ult slot measured 115-127 green, dim 59-69.
SLOT_READY_GREEN = 95
SLOT_READY_OVER_BLUE = 50


def crop(frame, box):
    x, y, w, h = box
    return frame[y:y + h, x:x + w].astype(np.int16)


def _green_fraction(frame, box):
    region = crop(frame, box)
    b, g, r = region[:, :, 0], region[:, :, 1], region[:, :, 2]
    return float(((g > r + 25) & (g > b + 25) & (g > 70)).mean())


def _dark_fraction(frame, box):
    return float((crop(frame, box).max(axis=2) < 60).mean())


def death_buttons_visible(frame):
    """YOU ARE DEAD with RESPAWN / GO TO OTHER WORLD on screen.

    The red death text can't be used: at 100G the whole room is red.
    """
    return (_green_fraction(frame, RESPAWN_BUTTON_BOX) > 0.6
            and _green_fraction(frame, OTHER_WORLD_BUTTON_BOX) > 0.6
            and _dark_fraction(frame, DEATH_STRIP_BOX) > 0.5)


def alive(frame):
    return _green_fraction(frame, HUD_LABELS_BOX) > 0.08 and not death_buttons_visible(frame)


def disconnected(frame):
    """Roblox's Disconnected / error box (idle kick 278, lost connection, server kick): a flat grey
    (57,59,61) panel with a pure-white Reconnect button. Same layout for every disconnect reason."""
    panel = frame[470:600, 790:1130].astype(np.int16)
    grey = (np.abs(panel - np.array([61, 59, 57])).max(axis=2) <= 6).mean()
    button = frame[615:640, 975:1130]
    white = (button.min(axis=2) > 245).mean()
    return grey > 0.6 and white > 0.7


CHAT_ICON_POINT = (138, 35)


def chat_open(frame):
    """Roblox's chat button is solid white while chat is on (even after the window fades),
    an outline when it's off. Measured 0.595 on vs 0.14-0.16 off.

    Open chat covers the HP/KI/FR tags, which would read as a loading screen.
    """
    icon = frame[24:46, 127:150]
    return float((icon.min(axis=2) > 200).mean()) > 0.35


def locked_on(frame):
    """The target panel (e.g. "Gravity Room Bot") is showing top-right.

    Needs both the target's orange HP/KI/FR tags and its green HP or blue KI bar:
    loading-screen art and the Kame beam can each fake the tags on their own.
    """
    tags = crop(frame, (1738, 128, 22, 72))
    b, g, r = tags[:, :, 0], tags[:, :, 1], tags[:, :, 2]
    tag_fraction = float(((r > 120) & (g > 50) & (g < 170) & (b < 60) & (r - g > 30)).mean())
    if not 0.15 < tag_fraction < 0.6:
        return False
    hp = crop(frame, (1300, 130, 400, 10))
    hp_green = float(((hp[:, :, 1] > 140) & (hp[:, :, 1] > hp[:, :, 2] + 30) & (hp[:, :, 1] > hp[:, :, 0] + 30)).mean())
    ki = crop(frame, (1300, 158, 400, 12))
    ki_blue = float(((ki[:, :, 0] > 150) & (ki[:, :, 0] > ki[:, :, 2] + 60)).mean())
    return hp_green > 0.3 or ki_blue > 0.3


def slot_has_move(frame, slot):
    """A move is equipped in the slot (lit or dim): its name text stands out from the bar.

    Filled slots measured 0.07-0.15, empty ones 0.000.
    """
    y = HOTBAR_SLOT1_Y + (slot - 1) * HOTBAR_SLOT_SPACING
    bar = cv2.cvtColor(np.ascontiguousarray(frame[y - 9:y + 9, 1700:1885]), cv2.COLOR_BGR2GRAY).astype(np.int16)
    return float((bar > np.median(bar) + 35).mean()) > 0.03


def slot_ready(frame, slot):
    """True when the hotbar slot is lit (ult powered up and off cooldown).

    Lit is green, BGR ~(40,140,68). The cyan full-screen flash (charge start, LEVEL UP) brightens a dim
    slot to ~(194,154,10) fading through (123,120,22): bright enough green, but blue as high, so hue
    decides. That flash used to fire ults into an empty bar (22% of shots in one run)."""
    y = HOTBAR_SLOT1_Y + (slot - 1) * HOTBAR_SLOT_SPACING
    x0, x1 = HOTBAR_BAR_X
    b, g = frame[y - 8:y + 8, x0:x1, :2].reshape(-1, 2).mean(axis=0)
    return bool(g > SLOT_READY_GREEN and g - b > SLOT_READY_OVER_BLUE)


def ki_fraction(frame):
    region = crop(frame, KI_BAR_BOX)
    b, g, r = region[:, :, 0], region[:, :, 1], region[:, :, 2]
    blue = (b > 150) & (b > r + 60)
    return float(blue.any(axis=0).mean())


# The Ki bar has two layers. Layer 1 (light blue, BGR ~168,136,9) fills first; once it's full,
# charging goes on and layer 2 (deeper blue, ~177,103,4) fills over it from the left. The ult slot
# lights partway into layer 2. Measured on both PCs' recordings 2026-10-23.
KI_BAR_MID_ROWS = (160, 166)  # the bar's flat middle; its top/bottom rows are shaded darker
KI_LAYER2_MAX_GREEN = 120


def ki_layers(frame):
    """(layer1, layer2): the fraction of the bar each colour covers. Full layer 1 under a third of
    layer 2 reads (0.67, 0.33)."""
    x, _, w, _ = KI_BAR_BOX
    mid = frame[KI_BAR_MID_ROWS[0]:KI_BAR_MID_ROWS[1], x:x + w].astype(np.int16).mean(axis=0)
    b, g, r = mid[:, 0], mid[:, 1], mid[:, 2]
    blue = (b > 150) & (b > r + 60)
    layer2 = blue & (g < KI_LAYER2_MAX_GREEN)
    return float((blue & ~layer2).mean()), float(layer2.mean())


def charge_progress(frame):
    """0 (empty) .. 1 (layer 1 full) .. 2 (layer 2 full): goes up the whole time a charge is
    working, whatever the race or Ki Control makes the speed."""
    layer1, layer2 = ki_layers(frame)
    return layer1 + 2 * layer2


# ---------------- Time Limit digits ----------------

DIGIT_SIZE = (14, 22)  # every glyph is normalised to this before comparing


def _white_mask(region):
    return (region.min(axis=2) > 215).astype(np.uint8)


def split_glyphs(mask):
    """Connected blobs tall enough to be digits, left to right."""
    count, _, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
    glyphs = []
    for i in range(1, count):
        x, y, w, h, _ = stats[i]
        if h >= 14:  # drops the colon dots and specks
            glyphs.append((x, mask[y:y + h, x:x + w]))
    return [cv2.resize(g * 255, DIGIT_SIZE, interpolation=cv2.INTER_AREA) for _, g in sorted(glyphs, key=lambda t: t[0])]


def _load_digit_templates():
    folder = ASSETS / "time_digits"
    return {d: cv2.imread(str(folder / f"{d}.png"), cv2.IMREAD_GRAYSCALE).astype(np.float32)
            for d in range(10) if (folder / f"{d}.png").exists()}


_DIGITS = None


def time_limit(frame):
    """Seconds left on GC's Time Limit, or None when it can't be read."""
    global _DIGITS
    if _DIGITS is None:
        _DIGITS = _load_digit_templates()
    glyphs = split_glyphs(_white_mask(crop(frame, TIME_LIMIT_BOX).astype(np.uint8)))
    if not glyphs or len(glyphs) > 5:
        return None
    value = ""
    for glyph in glyphs:
        glyph = glyph.astype(np.float32)
        scores = {d: float(np.abs(glyph - t).mean()) for d, t in _DIGITS.items()}
        best = min(scores, key=scores.get)
        if scores[best] > 60:  # nothing close: occluded or not digits
            return None
        value += str(best)
    return int(value)


def format_seconds(seconds):
    """3725 -> '1h 2m 5s', 90 -> '1m 30s', 45 -> '45s'."""
    seconds = max(0, int(seconds))
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)
    if hours:
        return f"{hours}h {minutes}m {secs}s"
    if minutes:
        return f"{minutes}m {secs}s"
    return f"{secs}s"
