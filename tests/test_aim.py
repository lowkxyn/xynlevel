"""Ceiling-ring detector on live frames from 2026-10-22 (live/ is private, not shipped).

run: python -I tests/test_aim.py
"""

import sys
from pathlib import Path

import cv2
import numpy as np
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import gc_aim  # noqa: E402

LIVE = ROOT / "live"


def frame(name):
    return cv2.imread(str(LIVE / f"{name}.png"))


def test_full_ring_found_right_of_target():
    x, y, count = gc_aim.ring_centre(frame("yaw_6"))
    assert count >= 5 and 1250 < x < 1450 and 700 < y < 850, (x, y, count)
    dx, dy = gc_aim.correction((x, y, count))
    assert dx > 0 and dy > 0, "drum right of and below target: drag right and down"


def test_single_lamp_gives_a_direction():
    x, y, count = gc_aim.ring_centre(frame("yaw_0"))
    assert count == 1 and x < 400, (x, y, count)
    assert gc_aim.correction((x, y, count))[0] < 0, "drum on the left: drag left"


def test_no_ring_when_looking_at_the_floor():
    assert gc_aim.ring_centre(frame("ring_7")) is None


def test_close_enough_means_no_drag():
    assert gc_aim.correction((gc_aim.TARGET[0] + 20, gc_aim.TARGET[1] - 20, 6)) is None


def test_corrections_are_clamped():
    dx, dy = gc_aim.correction((5000, -5000, 3))
    assert dx == gc_aim.MAX_STEP and dy == -gc_aim.MAX_STEP


def test_aim_learns_and_replays_the_camera_move():
    import gc_bot
    drags, parks = [], []
    gc_bot.camera_drag = lambda dx, dy, stopped=None: drags.append((dx, dy))
    gc_bot.park_cursor = lambda x, y: parks.append((x, y))
    gc_bot._send_mouse = lambda *a, **k: None
    gc_bot.time.sleep = lambda s: None
    # First life: ring at the left edge with 1 lamp -> one correction, then a clear ring.
    reads = iter([(100.0, 500.0, 1), (900.0, 400.0, 6)])
    gc_aim_ring, gc_bot.gc_aim.ring_centre = gc_bot.gc_aim.ring_centre, lambda frame: next(reads)
    memory = [-160, 60]
    try:
        assert gc_bot.aim_at_ceiling(lambda: None, 10, 20, memory)
        assert memory[0] < -160, memory  # learned to turn further left
        assert parks[-1] == (910, 420), parks  # cursor on the ring's middle, in screen coordinates
        # Next life replays the learned move straight away and needs no correction.
        learned = list(memory)
        drags.clear()
        reads = iter([(900.0, 400.0, 6)])
        assert gc_bot.aim_at_ceiling(lambda: None, 10, 20, memory)
        assert drags == [(0, -gc_bot.AIM_UP), tuple(learned)], drags
    finally:
        gc_bot.gc_aim.ring_centre = gc_aim_ring


def test_synthetic_lamp_counts_and_ellipse():
    image = np.zeros((1080, 1920, 3), np.uint8)
    for points in ([], [(900, 400)], [(800, 300), (1000, 300), (800, 500), (1000, 500)]):
        with patch.object(gc_aim, "lamps", return_value=points):
            centre = gc_aim.ring_centre(image)
            if not points:
                assert centre is None
            else:
                assert centre == (*np.mean(points, axis=0), len(points)), centre
    angles = np.linspace(0, 2 * np.pi, 5, endpoint=False)
    points = [(900 + 150 * np.cos(a), 400 + 80 * np.sin(a)) for a in angles]
    with patch.object(gc_aim, "lamps", return_value=points):
        x, y, count = gc_aim.ring_centre(image)
        assert abs(x - 900) < 1 and abs(y - 400) < 1 and count == 5, (x, y, count)


def test_collinear_lamps_fall_back_to_mean():
    points = [(800 + 50 * i, 300 + 25 * i) for i in range(5)]
    with patch.object(gc_aim, "lamps", return_value=points):
        assert gc_aim.ring_centre(np.zeros((1080, 1920, 3), np.uint8)) == (900, 350, 5)


def test_bad_ellipse_fits_fall_back_to_mean():
    points = [(100, 100), (300, 100), (300, 300), (100, 300), (200, 350)]
    for centre, axes in (((float("nan"), 200), (100, 100)), ((1e30, 200), (100, 100)),
                          ((-1, 200), (100, 100)), ((200, 200), (0, 100)),
                          ((200, 200), (float("nan"), 100))):
        with patch.object(gc_aim, "lamps", return_value=points), \
                patch.object(gc_aim.cv2, "fitEllipse", return_value=(centre, axes, 0)):
            assert gc_aim.ring_centre(np.zeros((480, 640, 3), np.uint8)) == (200, 230, 5)


def test_offscreen_centre_is_rejected():
    with patch.object(gc_aim, "lamps", return_value=[(640, 200)]):
        assert gc_aim.ring_centre(np.zeros((480, 640, 3), np.uint8)) is None


def test_uniform_frames_including_small_frames():
    for shape in ((1080, 1920, 3), (480, 640, 3), (1, 1, 3)):
        for colour in (0, 127, 255):
            assert gc_aim.ring_centre(np.full(shape, colour, np.uint8)) is None, (shape, colour)


def test_in_view_and_correction_boundaries():
    for x, y in ((250, 120), (1670, 960)):
        assert gc_aim.in_view((x, y, 3))
    for x, y in ((249, 120), (1671, 960), (250, 119), (1670, 961), (float("nan"), 360)):
        assert not gc_aim.in_view((x, y, 3))
    x, y = gc_aim.TARGET
    assert gc_aim.correction((x + 60, y - 60, 1)) is None
    assert gc_aim.correction((x + 61, y - 61, 1)) == (7, -7)
    assert gc_aim.correction((x - 61, y + 61, 1)) == (-7, 7)


if __name__ == "__main__":
    for name, test in list(globals().items()):
        if name.startswith("test_"):
            test()
            print("PASS", name)
