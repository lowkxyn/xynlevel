"""Finding the bot room's ceiling drum (dark disc with a ring of ~8 lamps). Unlocked ults go where
the cursor is, so the bot puts the cursor on the drum's black middle, like the casts in the recorded clips;
the camera is only turned when the ring is out of view or at the edge.

Coordinates are 1920x1080 game-area pixels. Lamps are pale yellow (BGR ~132,255,255) under normal
light (cores near white) and orange under the red light; the drum is near black or cobalt.
"""

import cv2
import numpy as np

# Where the drum's middle should end up: centred, above the character's head (clips: ~960,300-450).
TARGET = (960, 360)
CLOSE_ENOUGH = 60          # px from TARGET counts as aimed
GAIN = 0.12                # mouse counts per pixel of error (live: ~5 px of drum motion per count)
MAX_STEP = 120             # counts per correction, so one bad read can't spin the camera
MIN_LAMPS_FOR_CURSOR = 3   # enough of the ring to trust its middle without centring the camera
VIEW_MARGIN = (250, 120)   # the middle must be this far inside the screen (x, y) to aim the cursor at it

# Masked out: HUD bars/portrait, MENU tab, hotbar, and the game's cursor icon at screen centre.
_IGNORE = [(0, 0, 760, 250), (0, 230, 60, 470), (1560, 650, 360, 430), (930, 515, 70, 70)]


def lamps(frame):
    """Centres of lamp-like blobs: bright yellow (or orange under the red light), solid ellipses."""
    pixels = frame.astype(np.int16)
    blue, green, red = pixels[:, :, 0], pixels[:, :, 1], pixels[:, :, 2]
    # Yellow lamps and their near-white cores have red ~= green, both high, blue lower. Skin fails
    # (green well under red), lavender walls fail (blue above red).
    yellow = (red > 200) & (green > 200) & (np.abs(red - green) < 20) & (blue < red - 12)
    orange = (red > 230) & (green > 90) & (green < 180) & (blue < 80)
    mask = (yellow | orange).astype(np.uint8)
    for x, y, w, h in _IGNORE:
        mask[y:y + h, x:x + w] = 0
    # The drum is near black in shadow and cobalt blue where lit.
    drum = (frame.max(axis=2) < 60) | (blue > red + 40)
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    found = []
    for contour in contours:
        area = cv2.contourArea(contour)
        if not 250 <= area <= 40000:
            continue
        # Solid and convex like a lamp (tilted ellipses fill their bounding box badly, so use the hull).
        if area / max(cv2.contourArea(cv2.convexHull(contour)), 1) < 0.88:
            continue
        x, y, w, h = cv2.boundingRect(contour)
        if max(w, h) > 3 * min(w, h):
            continue
        # A lamp sits on the drum: the band around it must be mostly drum-coloured.
        pad = max(w, h) // 2
        x0, y0 = max(0, x - pad), max(0, y - pad)
        around = drum[y0:y + h + pad, x0:x + w + pad]
        if around.size and around.mean() > 0.25:
            moments = cv2.moments(contour)
            found.append((moments["m10"] / moments["m00"], moments["m01"] / moments["m00"]))
    return found


def ring_centre(frame):
    """(x, y, lamp_count) of the drum's middle, or None when no lamp is visible.
    With one lamp it's only a direction to turn toward; the next read sees more of the ring."""
    points = lamps(frame)
    if not points:
        return None
    points = np.array(points, np.float32)
    x, y = points.mean(axis=0)
    height, width = frame.shape[:2]
    # A line of lamps doesn't define an ellipse; OpenCV can still return a bogus fit.
    if len(points) >= 5 and np.linalg.matrix_rank(points - points.mean(axis=0)) == 2:
        (fit_x, fit_y), axes, _ = cv2.fitEllipse(points)
        if (np.isfinite([fit_x, fit_y, *axes]).all() and min(axes) > 0
                and 0 <= fit_x < width and 0 <= fit_y < height):
            x, y = fit_x, fit_y
    if not (0 <= x < width and 0 <= y < height):
        return None
    return float(x), float(y), len(points)


def in_view(centre):
    x, y, _ = centre
    return VIEW_MARGIN[0] <= x <= 1920 - VIEW_MARGIN[0] and VIEW_MARGIN[1] <= y <= 1080 - VIEW_MARGIN[1]


def correction(centre):
    """Mouse counts (dx, dy) for a right-button drag that moves the drum toward TARGET, or None
    when it's already close enough. Dragging right turns the view so things move left; dragging
    up tilts it up so things move down."""
    x, y, _ = centre
    error_x, error_y = x - TARGET[0], y - TARGET[1]
    if abs(error_x) <= CLOSE_ENOUGH and abs(error_y) <= CLOSE_ENOUGH:
        return None
    clamp = lambda value: int(max(-MAX_STEP, min(MAX_STEP, value)))
    return clamp(error_x * GAIN), clamp(error_y * GAIN)
