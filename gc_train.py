"""Gravity Chamber training loop for Dragon Generations (the Halloween 2026 GC).

Sets a high gravity, plays the Health training minigame, eats a Senzu bean when HP gets low (re-equipping
one from the inventory when item slot 1 is empty) and respawns after a gravity death. Standing in high
gravity gives no EXP by itself: the minigame is where the EXP comes from, scaled by the gravity's multiplier.

All boxes are (x, y, w, h) in the 1920x1080 game area.
"""

import ctypes
import re
import threading
import time

import mss
import numpy as np
import pydirectinput

import gc_read
import gc_vision as vision
from gc_bot import _bring_to_front, _foreground_process, click, tap
from window import auto_window, find_roblox_window, game_area_rect

pydirectinput.PAUSE = 0.0
user32 = ctypes.windll.user32

# Top-left card: "GRAVITY TRAINING / Press TAB to open training." (or "stop training", "Respawn to open").
CARD_BOX = (30, 268, 370, 45)
# Tab panel (Training Mode).
APPLY_BOX = (540, 300, 130, 70)
TRAINING_MODE_BOX = (245, 365, 210, 42)        # "Training Mode" heading, the cursor never sits there
PARK_AT = (960, 160)                           # empty sky: the game's cursor garbles text it covers
GRAVITY_INPUT = (484, 335)
APPLY_BUTTON = (604, 337)
MAX_GRAVITY_BOX = (556, 366, 110, 28)
STATS_LINE_BOX = (175, 772, 390, 38)          # "Resist 65% • Drain 519 HP/s • EXP x212.13"
HEALTH_BUTTON = (345, 438)
HEALTH_POINTS_BOX = (1290, 372, 230, 26)      # "Points Left: 9/260" (right-hand panel)
# Health minigame: a white marker sweeps the bar; F while it's inside the gold zone.
BAR_Y, BAR_X0, BAR_X1 = 905, 730, 1190
PRESS_GAP = 0.35
# Hotbar: H swaps skills <-> items; the items bar shows an "ITEMS" tab above it.
ITEMS_TAB_BOX = (1655, 640, 115, 28)
SLOT1_LABEL_BOX = (1690, 724, 205, 26)
# Menu (M) > Customize > Items > search "senzu" > the bean > "1) ..." to put it in item slot 1.
CUSTOMIZE_TAB = (34, 541)
ITEMS_ROW = (269, 734)
SEARCH_BOX = (450, 414)
FIRST_ROW = (253, 485)
FIRST_ROW_BOX = (90, 470, 420, 30)
RESPAWN_BUTTON = (960, 550)
# Roblox's Performance Stats bar (Ctrl+F7) covers the level and XP text.
PERF_BAR_BOX = (0, 60, 700, 34)

SENZU_COOLDOWN = 13.0     # the game's shared item cooldown is ~12 s
STATE_CONFIRM = 2         # same card reading this many times in a row before acting on it
LOST_GC_AFTER = 20.0      # no training card this long (and no menu/panel/death) = not in the GC any more
LEVEL_EVERY = 5.0
PERF_CHECK_EVERY = 60.0
SAFE_GRAVITY = 1
TINTED = 0.6              # gravity_tint above this: standing in the gravity field
TINT_FROM_DRAIN = 100     # only gravities that drain this much tint the screen clearly
WALK_TRIES = ("a", "w", "d", "s")


def parse_card(text):
    """'idle' (can open training), 'training', 'dead', or None when the card isn't there."""
    text = text.lower()
    if "training" not in text:
        return None
    if "respawn" in text:
        return "dead"
    if "stop" in text:
        return "training"
    if "open" in text:
        return "idle"
    return None


def parse_stats_line(text):
    """(resist %, drain HP/s, EXP multiplier) from the panel line. The font hides the decimal point
    ("x21213" is x212.13, "x107" is x1.07), so a multiplier without a dot is read as hundredths."""
    text = text.replace("o", "0").replace("O", "0")
    resist = re.search(r"Resist\s*(\d+)", text, re.IGNORECASE)
    drain = re.search(r"Drain\s*(\d+)", text, re.IGNORECASE)
    exp = re.search(r"EXP\s*x?\s*(\d+(?:[.,]\d+)?)", text, re.IGNORECASE)
    multiplier = None
    if exp:
        raw = exp.group(1).replace(",", ".")
        multiplier = float(raw) if "." in raw else int(raw) / 100
    return (int(resist.group(1)) if resist else None, int(drain.group(1)) if drain else None, multiplier)


def parse_max_gravity(text):
    match = re.search(r"(\d+)\s*G", text.replace("o", "0").replace("O", "0"))
    return int(match.group(1)) if match else None


def parse_points_left(text):
    match = re.search(r"(\d+)\s*/\s*(\d+)", text.replace("o", "0").replace("O", "0"))
    return int(match.group(1)) if match else None


def parse_senzu_row(text):
    """Beans left from 'Senzu Bean x489', or None if the row isn't the Senzu."""
    if "senzu" not in text.lower():
        return None
    match = re.search(r"x\s*(\d[\d,]*)", text, re.IGNORECASE)
    return int(match.group(1).replace(",", "")) if match else 0


def hp_fraction(frame):
    row = frame[135, 197:705].astype(np.int16)
    return float(((row[:, 1] > 100) & (row[:, 1] > row[:, 0] + 40)).mean())


def marker_in_gold(row):
    """Bar row (BGR): True when the white marker sits inside the gold zone."""
    row = row.astype(np.int16)
    gold = np.where((row[:, 2] > 170) & (row[:, 1] > 130) & (row[:, 0] < 120))[0]
    white = np.where((row > 225).all(axis=1))[0]
    if len(gold) <= 5 or not len(white):
        return False
    marker = np.median(white)
    return gold.min() - 2 <= marker <= gold.max() + 2


def gravity_tint(frame):
    """Share of the middle band that's the deep red high gravity paints over the chamber. The
    respawn spot by the LEAVE door is outside the gravity field: white walls there, no drain."""
    band = frame[320:520].astype(np.int16)
    return float(((band[..., 2] > 150) & (band[..., 1] < 110) & (band[..., 0] < 110)).mean())


def gravity_target(settings, unlocked):
    if settings.get("gravity_mode", "max") == "custom":
        wanted = int(settings.get("gravity", 500))
        return max(1, min(wanted, unlocked or wanted))
    return unlocked


class Bot:
    """Runs on its own thread. `on_status(text)` gets short status lines, `on_stop(reason)` the end."""

    def __init__(self, settings, on_status, on_stop):
        self.settings = settings
        self.on_status = on_status
        self.on_stop = on_stop
        self._stop = threading.Event()
        self.time_left = None  # the GC has no on-screen timer any more
        self.stats = {"started": None, "deaths": 0, "senzus": 0, "refills": 0, "pulls": 0, "paused": 0}
        self.events = []
        self.grab = None
        self.slot_loaded = None  # is a bean in item slot 1? None = not checked yet
        self.check_field = True  # look for the gravity field before the next training (start, respawn)
        self.debug_dir = None  # a folder to save a screenshot at each failure (live testing)

    def _event(self, name, shot=False):
        self.events.append((round(time.monotonic(), 3), name))
        if shot and self.debug_dir and self.grab:
            import cv2
            cv2.imwrite(str(self.debug_dir / f"{time.strftime('%H%M%S')}_{name.replace(' ', '_')[:40]}.jpg"),
                        self.grab()[::2, ::2])

    def start(self):
        self._stop.clear()
        threading.Thread(target=self._run, daemon=True).start()

    def stop(self):
        self._stop.set()

    def _sleep(self, seconds):
        self._stop.wait(seconds)

    def _run(self):
        try:
            self._loop()
        except Exception as error:  # surface it in the UI instead of dying silently
            self._finish(f"Stopped: error: {error}")

    def _finish(self, reason):
        for key in ("f", "h", "ctrl", "shift"):
            pydirectinput.keyUp(key)
        self.on_stop(reason)

    # Screen reads ---------------------------------------------------------------------------

    def _ocr(self, box, frame=None, scale=3, binarize=False):
        try:
            return gc_read.ocr(self.grab() if frame is None else frame, box, scale=scale, binarize=binarize)
        except OSError as error:  # e.g. no Windows OCR language pack
            if not getattr(self, "_ocr_error_logged", False):
                self._ocr_error_logged = True
                self._event(f"ocr error: {error}")
            return ""

    def _has(self, box, word, frame=None):
        """True if `word` shows in the box. Each label only reads well with some OCR settings
        ("ITEMS" comes out "ITEus" unless binarized, "Apply" vanishes at scale 3), so try several."""
        frame = self.grab() if frame is None else frame
        return any(word in self._ocr(box, frame, scale=scale, binarize=b).lower()
                   for scale in (2, 3) for b in (True, False))

    def _card(self, frame):
        return parse_card(self._ocr(CARD_BOX, frame, scale=2))

    def _panel_open(self, frame=None):
        frame = self.grab() if frame is None else frame
        return self._has(TRAINING_MODE_BOX, "mode", frame) or self._has(APPLY_BOX, "apply", frame)

    def _items_bar(self, frame=None):
        return self._has(ITEMS_TAB_BOX, "items", frame)

    def _read_level(self, frame):
        try:
            level = gc_read.level(frame)
            current, needed, _ = gc_read.xp(frame)
        except OSError:
            return
        known = self.stats.get("level")
        if level is None or (known is not None and not known <= level <= known + 50):
            return
        self.stats.setdefault("start_level", level)
        self.stats["level"] = level
        self.stats["levels"] = level - self.stats["start_level"]
        if current is not None and needed:
            self.stats["xp_percent"] = int(min(100, 100 * current / needed))
            if self.stats["start_level"] == level:
                self.stats.setdefault("start_xp_percent", self.stats["xp_percent"])

    # Actions --------------------------------------------------------------------------------

    def _click(self, point):
        left, top = self.origin
        click(left + point[0], top + point[1])
        time.sleep(0.05)
        user32.SetCursorPos(left + PARK_AT[0], top + PARK_AT[1])

    def _type(self, text):
        pydirectinput.keyDown("ctrl")
        tap("a")
        pydirectinput.keyUp("ctrl")
        pydirectinput.write(str(text), interval=0.08)

    def _close_perf_bar(self):
        text = self._ocr(PERF_BAR_BOX, scale=2).lower()
        if "cpu" in text and ("gpu" in text or "mem" in text):
            pydirectinput.keyDown("ctrl")
            tap("f7")
            pydirectinput.keyUp("ctrl")
            self._event("closed the Performance Stats bar")

    def _open_panel(self):
        for _ in range(3):
            if self._panel_open():
                return True
            tap("tab")
            self._sleep(1.2)
        return self._panel_open()

    def _close_panel(self):
        for _ in range(3):
            if not self._panel_open():
                return True
            tap("tab")
            self._sleep(1.0)
        return not self._panel_open()

    def _set_gravity(self, value):
        """With the panel open: type the gravity, Apply, and read back drain and EXP."""
        self.on_status(f"Setting gravity to {value}G")
        self._click(GRAVITY_INPUT)
        self._sleep(0.3)
        self._type(value)
        previous = self._ocr(STATS_LINE_BOX)
        self._click(APPLY_BUTTON)
        # The line under the buttons updates a second or more after Apply: wait for it to change.
        line = previous
        for _ in range(10):
            self._sleep(0.5)
            line = self._ocr(STATS_LINE_BOX)
            if line != previous:
                self._sleep(0.5)
                line = self._ocr(STATS_LINE_BOX)
                break
        resist, drain, multiplier = parse_stats_line(line)
        self.stats["gravity"] = value
        if drain is not None:
            self.stats["drain"] = drain
        if multiplier is not None:
            self.stats["exp_mult"] = multiplier
        self._event(f"gravity {value}G resist {resist} drain {drain} exp x{multiplier}")

    def _start_training(self):
        """From the normal view: open the panel, set gravity, read Health points, start Health."""
        if not self._open_panel():
            self._event("panel didn't open", shot=True)
            return False
        unlocked = parse_max_gravity(self._ocr(MAX_GRAVITY_BOX))
        if unlocked:
            self.stats["max_gravity"] = unlocked
        target = gravity_target(self.settings, unlocked)
        if target and target != self.stats.get("gravity"):
            self._set_gravity(target)
        if self.check_field and self.stats.get("drain", 0) >= TINT_FROM_DRAIN:
            if not self._walk_into_gravity():
                self._event("couldn't find the gravity field", shot=True)
                return False
            self.check_field = False
        points = parse_points_left(self._ocr(HEALTH_POINTS_BOX, scale=2))
        if points is not None:
            self.stats["points_left"] = points
        self._click(HEALTH_BUTTON)
        for _ in range(6):
            self._sleep(0.5)
            if self._card(self.grab()) == "training":
                self.on_status("Training: Health")
                self._event("training started")
                return True
        self._event("health didn't start", shot=True)
        return False

    def _walk_into_gravity(self):
        """With the panel open and a draining gravity set: make sure the character stands in the
        field (after a death it respawns by the door, outside it). Leaves the panel open."""
        if not self._close_panel():
            return False
        self._sleep(1.0)
        for key in (None,) + WALK_TRIES:
            if key:
                pydirectinput.keyDown(key)
                self._sleep(2.5)
                pydirectinput.keyUp(key)
                self._sleep(1.0)
            if gravity_tint(self.grab()) > TINTED:
                if key:
                    self._event(f"walked into the gravity field ({key})")
                return self._open_panel()
        return False

    def _stop_training(self):
        """Training -> normal view (Tab stops training and shows the panel, Tab again hides it)."""
        tap("tab")
        self._sleep(1.2)
        return self._close_panel()

    def _show_items(self, want):
        for _ in range(3):
            if self._items_bar() == want:
                return True
            tap("h")
            self._sleep(0.7)
        return self._items_bar() == want

    def _refill_senzu(self):
        """Put a bean from the inventory into item slot 1. Returns how many beans the inventory had
        (0 = none to load), or None if the menu didn't go as expected."""
        self.on_status("Getting a Senzu from the inventory")
        tap("m")
        self._sleep(1.3)
        self._click(CUSTOMIZE_TAB)
        self._sleep(1.2)
        self._click(ITEMS_ROW)
        self._sleep(1.2)
        self._click(SEARCH_BOX)
        self._sleep(0.4)
        self._type("senzu")
        self._sleep(1.2)
        frame = self.grab()
        left = next((value for b in (False, True)
                     if (value := parse_senzu_row(self._ocr(FIRST_ROW_BOX, frame, scale=2, binarize=b))) is not None), None)
        if not left:
            # Leave the search box before M, or the M is typed into it.
            tap("enter")
            self._sleep(0.4)
            tap("m")
            self._sleep(1.0)
            return 0 if left == 0 else None
        self._click(FIRST_ROW)
        self._sleep(1.2)
        frame = self.grab()
        if not any(re.match(r"\s*[1Il|]\s*\)", self._ocr(FIRST_ROW_BOX, frame, scale=2, binarize=b)) for b in (False, True)):
            tap("m")
            self._sleep(1.0)
            return None
        self._click(FIRST_ROW)  # "1) Empty" (or whatever slot 1 holds): the bean goes there
        self._sleep(1.2)
        tap("m")
        self._sleep(1.2)
        self.stats["refills"] += 1
        self.stats["senzu_left"] = left - 1
        self._event(f"refilled senzu, {left - 1} left")
        return left

    def _ensure_senzu_loaded(self):
        """Keep a bean in item slot 1 while HP is high, so eating at low HP is only H then 1.
        Refilling takes ~10 s in the menu, which a character at 3% HP under high gravity doesn't have."""
        if self.slot_loaded is None:
            self.slot_loaded = self._slot1_loaded()
        if self.slot_loaded:
            return True
        found = self._refill_senzu()
        if not found:
            return found  # None: menu trouble, 0: no beans
        self.slot_loaded = True
        return True

    def _slot1_loaded(self):
        if not self._show_items(True):
            return False
        loaded = self._has(SLOT1_LABEL_BOX, "senzu")
        self._show_items(False)
        return loaded

    def _eat_senzu(self, training):
        """Returns True if a bean was eaten. Item keys don't work during the minigame, so it stops first."""
        self.on_status("Eating a Senzu")
        if training and not self._stop_training():
            self._event("senzu: training didn't stop", shot=True)
            return False
        self._sleep(0.5)
        before = hp_fraction(self.grab())
        if self.slot_loaded is False or (self.slot_loaded is None and not self._slot1_loaded()):
            found = self._refill_senzu()
            if not found:
                if found == 0:
                    self.stats["senzu_left"] = 0
                self._event("senzu: none to load", shot=True)
                return False
        if not self._show_items(True):
            self._event("senzu: items bar didn't open", shot=True)
            return False
        tap("1")  # only ever slot 1: other item slots can hold things like Potara
        # The HP bar takes a moment to fill back up.
        after = before
        for _ in range(8):
            self._sleep(0.5)
            after = hp_fraction(self.grab())
            if after > before + 0.1:
                break
        eaten = after > before + 0.1 or not self._has(SLOT1_LABEL_BOX, "senzu")
        self._show_items(False)
        if not eaten:
            self._event(f"senzu: not eaten, hp {before:.2f}->{after:.2f}", shot=True)
            return False
        self.slot_loaded = False
        self.stats["senzus"] += 1
        self._event(f"senzu hp {before:.2f}->{after:.2f}")
        self._ensure_senzu_loaded()  # HP is up again: the safe moment to load the next one
        return True

    def _leave_safe(self):
        """End of run: stop training and put gravity back to 1G so an idle character doesn't drain."""
        if self._card(self.grab()) == "training":
            tap("tab")
            self._sleep(1.2)
        if self._open_panel():
            self._set_gravity(SAFE_GRAVITY)
            self._close_panel()

    # Main loop ------------------------------------------------------------------------------

    def _loop(self):
        s = self.settings
        hwnd = find_roblox_window()
        if hwnd is None:
            return self._finish("Stopped: Roblox not found")
        ok, message = auto_window(hwnd)
        self._event(message)
        if not ok:
            return self._finish(f"Stopped: {message}")
        self.stats["started"] = time.time()
        self.on_status("Getting ready")

        with mss.MSS() as screen:
            def grab():
                left, top, width, height = game_area_rect(hwnd)
                shot = screen.grab({"left": left, "top": top, "width": width, "height": height})
                return np.ascontiguousarray(np.asarray(shot)[:, :, :3])
            self.grab = grab
            self.origin = game_area_rect(hwnd)[:2]
            _bring_to_front(hwnd)
            self._sleep(0.5)
            self._close_perf_bar()
            if s.get("auto_senzu", True) and self._card(grab()) == "idle":
                if self._ensure_senzu_loaded() is False:
                    return self._finish("Stopped: no Senzu beans left")

            readings = []
            focus_lost = None
            lost_since = None
            last_press = next_level = next_perf = 0.0
            next_senzu = 0.0
            senzu_failures = 0
            train_failures = 0
            deadline = time.monotonic() + 60 * s["stop_after_minutes"] if s.get("stop_after_minutes") else None
            reason = None

            while not self._stop.is_set():
                rect = game_area_rect(hwnd)
                if rect is None:
                    return self._finish("Stopped: Roblox window closed")
                if rect[2:] != (1920, 1080):
                    return self._finish(f"Stopped: game area is {rect[2]}x{rect[3]}, start again to fix the window")
                self.origin = rect[:2]
                if user32.GetForegroundWindow() != hwnd:
                    for key in ("f", "h"):
                        pydirectinput.keyUp(key)
                    if focus_lost is None:
                        focus_lost = time.monotonic()
                        self._event(f"focus lost to {_foreground_process()}")
                    self.on_status("Paused: Roblox isn't the active window")
                    self._sleep(0.5)
                    continue
                if focus_lost is not None:
                    self.stats["paused"] += int(round(time.monotonic() - focus_lost))
                    focus_lost = None

                frame = grab()
                now = time.monotonic()
                if vision.disconnected(frame):
                    return self._finish("Stopped: Roblox disconnected you (idle kick, lost connection or server kick)")
                if deadline and now >= deadline:
                    reason = f"Stopped: ran for {s['stop_after_minutes']} min"
                    break
                if now >= next_perf:
                    next_perf = now + PERF_CHECK_EVERY
                    self._close_perf_bar()

                readings = (readings + [self._card(frame)])[-STATE_CONFIRM:]
                state = readings[0] if len(set(readings)) == 1 and len(readings) == STATE_CONFIRM else "unsure"

                if state == "training":
                    lost_since = None
                    train_failures = 0
                    if now >= next_level:
                        next_level = now + LEVEL_EVERY
                        self._read_level(frame)
                        target = s.get("stop_at_level")
                        if target and self.stats.get("level", 0) >= target:
                            reason = f"Stopped: reached level {self.stats['level']}"
                            break
                    hp = hp_fraction(frame)
                    if s.get("auto_senzu", True) and hp <= s.get("senzu_at", 35) / 100 and now >= next_senzu:
                        next_senzu = time.monotonic() + SENZU_COOLDOWN
                        if self._eat_senzu(training=True):
                            senzu_failures = 0
                        else:
                            senzu_failures += 1
                            self._event("senzu failed", shot=True)
                            if self.stats.get("senzu_left") == 0:
                                reason = "Stopped: out of Senzu beans"
                                break
                            if senzu_failures >= 2:
                                # Don't keep training at a draining gravity without a way to heal.
                                reason = "Stopped: couldn't eat a Senzu (gravity set back to 1G)"
                                break
                        readings = []
                        continue
                    # Play the bar for a second between the slower checks above.
                    until = time.monotonic() + 1.0
                    while time.monotonic() < until and not self._stop.is_set():
                        row = grab()[BAR_Y, BAR_X0:BAR_X1]
                        if time.monotonic() - last_press >= PRESS_GAP and marker_in_gold(row):
                            tap("f")
                            last_press = time.monotonic()
                            self.stats["pulls"] += 1
                        time.sleep(0.008)
                elif state == "idle":
                    lost_since = None
                    if self._items_bar(frame):
                        self._show_items(False)
                    if self._start_training():
                        train_failures = 0
                    else:
                        train_failures += 1
                        self._event("training didn't start")
                        self._close_panel()
                        if train_failures >= 5:
                            reason = "Stopped: training wouldn't start (no training points left?)"
                            break
                    readings = []
                elif state == "dead":
                    lost_since = None
                    self.on_status("Respawning")
                    self.stats["deaths"] += 1
                    self._event("died")
                    for _ in range(10):
                        self._click(RESPAWN_BUTTON)
                        self._sleep(3.0)
                        if not vision.death_buttons_visible(grab()):
                            break
                    self.stats.pop("gravity", None)  # set it again for the new life
                    self.check_field = True  # respawned by the door, outside the field
                    readings = []
                else:
                    if self._panel_open(frame):
                        self._close_panel()
                        readings = []
                        continue
                    if vision.death_buttons_visible(frame):
                        readings = ["dead"] * STATE_CONFIRM
                        continue
                    if lost_since is None:
                        self._event("no training card", shot=True)
                    lost_since = lost_since or now
                    if now - lost_since > LOST_GC_AFTER:
                        return self._finish("Stopped: not in the Gravity Chamber "
                                            "(the daily training limit may be used up)")
                    self._sleep(0.3)

            self._leave_safe()
            self._finish(reason or "Stopped")
