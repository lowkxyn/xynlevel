"""The GC bot-room loop: respawn, attack, repeat until stopped or the time limit is reached."""

import ctypes
import ctypes.wintypes as wt
import random
import threading
import time

import mss
import numpy as np
import pydirectinput

import gc_aim
import gc_gravity
import gc_read
import gc_menu
import gc_stats
import gc_vision as vision
from window import auto_window, find_roblox_window, game_area_rect

pydirectinput.PAUSE = 0.0
user32 = ctypes.windll.user32
REFOCUS_AFTER = 1.0  # s off-focus before taking Roblox back (setting "refocus")
REFOCUS_GAP = 3.0


def _foreground_process():
    """Exe name of the foreground window, for the focus-lost event."""
    pid = wt.DWORD()
    user32.GetWindowThreadProcessId(user32.GetForegroundWindow(), ctypes.byref(pid))
    handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid.value)  # QUERY_LIMITED_INFORMATION
    if not handle:
        return f"pid {pid.value}"
    name = ctypes.create_unicode_buffer(260)
    size = wt.DWORD(260)
    ctypes.windll.kernel32.QueryFullProcessImageNameW(handle, 0, name, ctypes.byref(size))
    ctypes.windll.kernel32.CloseHandle(handle)
    return name.value.rsplit("\\", 1)[-1] or f"pid {pid.value}"


def _bring_to_front(hwnd):
    # Windows only lets a process take the foreground right after a keypress, so tap Alt first.
    user32.keybd_event(0x12, 0, 0, 0)
    user32.keybd_event(0x12, 0, 2, 0)
    user32.SetForegroundWindow(hwnd)

CHARGE_KEY = "shift"
KI_BLAST_KEY = "f"
LOCK_KEY = "l"            # toggles lock-on; scroll switches target only while locked
LOCK_RETRY = 1.0          # L toggles, so wait for the screen to confirm before pressing again
SHIFT_GAP = 0.1           # s between a Shift up and the next Shift down
SPRINT_DELAY = 0.12       # s of walking before the sprint Shift goes down
LOCK_SETTLE = 0.6         # after an L press, before zooming: a scroll while still locked switches
                          # target instead of zooming out (live 2026-10-23: aim missed, camera close)
# Charging is judged only by reading the Ki bar (vision.charge_progress), never by how long a charge
# "should" take: race and Ki Control change the speed (one test PC refilled in ~1.2 s with Ki Control,
# another took ~5 s without it). The waits below are for the game noticing a press, not for charging.
RISE_WAIT_MIN = 1.8       # s; an accepted Shift shows the bar moving 0.5-1.0 s later (charge windup,
                          # both PCs' videos), plus ~0.3 s for the bot to see it. Grows with the
                          # slowest windup this PC has shown, up to RISE_WAIT_MAX.
RISE_WAIT_MAX = 3.0
RISE_STEP = 0.03          # charge_progress gain that counts as "moving" (~15 px of the bar)
FLAT_WAIT = 2.0           # s the bar may stand still mid-charge (the pause between layers is <= 0.9 s)
POST_CAST_DROPPED = 2.5   # s after a fire: a Shift press this early was ignored every time (both test PCs'
                          # videos, ~270 shots). How much later works is learned per run (_post_cast_offset).
POST_CAST_MAX = 5.0       # the learned line never goes past this (presses ~4.4 s after worked on both PCs)
POST_CAST_REPROBE = 8     # after this many accepted presses at the learned line, try a little earlier
HUD_GONE_DEATH = 0.6      # s without the HUD while pressing an ult = dying (a cast flash hides it ~0.2 s)
SPAWN_SETTLE = 0.5        # wait after respawning before pressing anything
CAST_WAIT = 2.5           # ult_jump only: the beam animation before landing
JUMP_LIFT = 0.25          # jump-fire: time holding Space before firing, to get off the ground
LAND_WAIT = 1.0           # jump-fire: let the character fall before charging again
FIRE_CHECK = 0.6          # a fired ult's slot goes dim; still lit after this = the press was ignored
FIRE_RETRIES = 2
FIRE_CHECK_CAP = 2.0      # slow-PC ceiling for the adaptive fire wait
LEVEL_READ_EVERY = 10.0   # s between HUD level reads (OCR, ~50 ms) for the app's Level tile
LOST_SCREEN_TIMEOUT = 60  # neither alive, dead nor loading for this long = something is wrong
RESPAWN_RETRY_GAP = 1.0   # the game ignores Respawn clicks for a moment after the buttons appear
RESPAWN_DELAY_CAP = 3.0   # one laggy death mustn't make every later respawn wait long
RESPAWN_MAX_CLICKS = 30   # the dialog never accepting means something else is wrong
CHAT_MAX_CLICKS = 5       # a chat icon that never reads closed (e.g. a Roblox UI change) mustn't loop
TIMER_GRACE = 10.0        # no GC timer for this long = unknown screen: stop sending input
STOP_CONFIRM_READS = 3    # a single misread timer (6895 seen as 895) mustn't end the run
SHOP_RETRY = 120.0        # too poor: look again this often. Was 300 s; a false "too poor" (death
                          # fade, fixed) then cost ~110 levels of Ki blasts on a test PC.
KAME_LEVEL = 135          # 4x Kame stays locked in the shop below this, so checking earlier is wasted time
SHOP_BLIND_DEATHS = 3     # level never read (no OCR): shop anyway after this many deaths
SHOP_MAX_ERRORS = 3       # menu steps failing repeatedly: give up for this run
STATS_RETRY = 300.0       # not enough skill points yet: look again this often
AIM_ZOOM_OUT = 15         # wheel notches out before aiming
AIM_UP, AIM_STEP = 600, 5  # mouse counts: far past the top of the tilt; drag step size
DRAG_STROKE = 200          # counts per right-drag stroke; the cursor starts mid-game, 540 px from the edge
AIM_START = (-160, 60)    # (turn, tilt back) counts after the top-tilt: drum near the middle (live sweep)
AIM_CORRECTIONS = 6
RESTORE_WAIT = 120.0      # after the stop time, how long to wait for a death to put the old move back
RELOCK_EVERY = (8.0, 15.0)  # scroll sometimes stops switching targets; dropping and retaking the lock fixes it
STRAFE_SWITCH = (3.0, 6.0)  # circle movement: swap between W+A and W+D this often
JUMP_EVERY = (1.2, 2.0)     # ki blasts with blast_jump on: a double hop this often (time to land)
JUMP_GAP = (0.25, 0.4)      # between the two hops of a double hop
MOVEMENT_KEYS = {"off": (), "w": ("w",), "wa": ("w", "a"), "wd": ("w", "d")}


# ---------------- input ----------------

class _MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", wt.LONG), ("dy", wt.LONG), ("mouseData", wt.DWORD), ("dwFlags", wt.DWORD),
                ("time", wt.DWORD), ("dwExtraInfo", ctypes.POINTER(wt.ULONG))]


class _INPUT(ctypes.Structure):
    _fields_ = [("type", wt.DWORD), ("mi", _MOUSEINPUT)]


MOUSEEVENTF_MOVE, MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP, MOUSEEVENTF_WHEEL = 0x1, 0x2, 0x4, 0x800
MOUSEEVENTF_RIGHTDOWN, MOUSEEVENTF_RIGHTUP = 0x8, 0x10


def _send_mouse(flags, dx=0, dy=0, data=0):
    event = _INPUT(type=0, mi=_MOUSEINPUT(dx, dy, ctypes.c_ulong(data & 0xFFFFFFFF).value, flags, 0, None))
    user32.SendInput(1, ctypes.byref(event), ctypes.sizeof(_INPUT))


def click(x, y):
    user32.SetCursorPos(int(x), int(y))
    time.sleep(0.02)
    # Roblox ignores a click until it sees a real relative mouse move (XynMacro found this).
    _send_mouse(MOUSEEVENTF_MOVE, 1, 0)
    time.sleep(0.005)
    _send_mouse(MOUSEEVENTF_MOVE, -1, 0)
    time.sleep(0.02)
    _send_mouse(MOUSEEVENTF_LEFTDOWN)
    time.sleep(0.05)
    _send_mouse(MOUSEEVENTF_LEFTUP)


def scroll_down():
    _send_mouse(MOUSEEVENTF_WHEEL, data=-120)


def scroll(notches):
    """Wheel `notches` (negative = down), one notch per event: on a slow PC, Roblox ignored a single
    600-delta event (the Stats list never scrolled up)."""
    for _ in range(abs(notches)):
        _send_mouse(MOUSEEVENTF_WHEEL, data=120 if notches > 0 else -120)
        time.sleep(0.02)


def park_cursor(x, y):
    """Move the cursor without clicking. It slides in over the last 30 px: on a slow PC, Roblox ignored
    the wheel over a list the cursor had only jumped onto (Stats never scrolled up)."""
    user32.SetCursorPos(int(x) - 30, int(y))
    for _ in range(3):
        _send_mouse(MOUSEEVENTF_MOVE, 10, 0)
        time.sleep(0.02)


def camera_drag(dx, dy, stopped=lambda: False):
    """Right-button drag by (dx, dy) mouse counts: turns/tilts the Roblox camera.

    Done in short strokes, each restarting from where the cursor began. Roblox doesn't always
    lock the cursor during a right-drag (live 2026-10-23), and one long stroke could carry it off
    the game; releasing right-click over another window then took focus and paused the run.
    """
    origin = wt.POINT()
    user32.GetCursorPos(ctypes.byref(origin))
    strokes = max(1, -(-max(abs(dx), abs(dy)) // DRAG_STROKE))
    for stroke in range(strokes):
        if stopped():  # alt-tab mid-drag: no right-button release over another window
            break
        stroke_dx = dx * (stroke + 1) // strokes - dx * stroke // strokes
        stroke_dy = dy * (stroke + 1) // strokes - dy * stroke // strokes
        user32.SetCursorPos(origin.x, origin.y)
        _send_mouse(MOUSEEVENTF_RIGHTDOWN)
        time.sleep(0.03)
        steps = max(1, max(abs(stroke_dx), abs(stroke_dy)) // AIM_STEP)
        for i in range(steps):
            # Spread the remainder so the total is exact.
            _send_mouse(MOUSEEVENTF_MOVE, stroke_dx * (i + 1) // steps - stroke_dx * i // steps,
                        stroke_dy * (i + 1) // steps - stroke_dy * i // steps)
            time.sleep(0.004)
        time.sleep(0.03)
        _send_mouse(MOUSEEVENTF_RIGHTUP)
    user32.SetCursorPos(origin.x, origin.y)


def aim_at_ceiling(grab, left, top, memory, ready=lambda frame: False, stopped=lambda: False):
    """Put the cursor on the black middle of the ceiling drum (the ring of lamps), where the recorded
    casts went. Unlocked ults go where the cursor is, so the camera only has to bring the
    ring into view. Returns True if the cursor ended on the ring.

    memory = [turn, tilt] in mouse counts from the start pose. It's replayed every life (fast,
    like muscle memory) and only corrected when the scan says the ring is off to the side.

    Live 2026-10-22: wheel-down (unlocked) zooms out; without it the camera is pressed against
    the character. A long upward drag ends at Roblox's tilt limit, so the start pose is the same
    every life; from the EXIT spawn the drum is then up and to the left.

    ready(frame): the ult is charged. Then the aim stops where it is so the shot isn't held back
    (charging comes first; a shot without the ring can still hit). stopped(): Stop or focus lost.
    """
    park_cursor(left + 960, top + 540)
    for _ in range(AIM_ZOOM_OUT):
        _send_mouse(MOUSEEVENTF_WHEEL, data=-120)
        time.sleep(0.01)
    if stopped():
        return False
    camera_drag(0, -AIM_UP, stopped)
    camera_drag(*memory, stopped=stopped)
    for _ in range(AIM_CORRECTIONS):
        time.sleep(0.08)  # let the camera settle before reading
        frame = grab()
        if stopped():
            return False
        centre = gc_aim.ring_centre(frame)
        if centre is None:
            return False
        move = gc_aim.correction(centre)
        if centre[2] >= gc_aim.MIN_LAMPS_FOR_CURSOR and gc_aim.in_view(centre):
            park_cursor(left + int(centre[0]), top + int(centre[1]))
            return True
        if move is None or ready(frame):
            return False
        camera_drag(*move, stopped=stopped)
        # Keep the replay within one correction pass of the start pose, even after failed lives.
        budget = AIM_CORRECTIONS * gc_aim.MAX_STEP
        for axis in (0, 1):
            memory[axis] = max(AIM_START[axis] - budget, min(AIM_START[axis] + budget, memory[axis] + move[axis]))
    return False


def tap(key):
    pydirectinput.keyDown(key)
    time.sleep(0.05)
    pydirectinput.keyUp(key)


# ---------------- loop ----------------

class Bot:
    """Runs on its own thread. `on_status(text)` is called with short status lines."""

    def __init__(self, settings, on_status, on_stop):
        self.settings = settings
        self.on_status = on_status
        self.on_stop = on_stop
        self._stop = threading.Event()
        self._charging = False
        self._held = set()
        self._shift_up = 0.0
        self.time_left = None
        self.replaced = None  # (slot, move name) that auto-equip pushed out, to put back at the end
        self.fire_times = []  # seconds from pressing an ult key to its slot dimming (recent fires)
        self.rise_delays = []  # seconds from an accepted Shift press to the Ki bar moving (recent)
        # Seconds after a fire: latest a Shift press was ignored, earliest one worked (None = not yet).
        self.post_cast = {"dropped": POST_CAST_DROPPED, "took": None, "streak": 0}
        # An ignored post-cast press only moves the line once a later press of the same recharge
        # works: that shows the timing, not lag or a misread, was why.
        self.ignored_pending = None
        self.fired_at = None  # when the last ult fired, until the recharge after it gets going
        self.aim_memory = list(AIM_START)  # learned camera move to the ceiling ring, see aim_at_ceiling
        # Shown in the app. Plain ints, only written by the bot thread.
        self.stats = {"started": None, "deaths": 0, "ults": 0, "blasts": 0, "paused": 0}
        # Seconds after the death buttons appear that a Respawn click gets accepted. Learned
        # from each death: retried clicks push it later, first-try successes pull it earlier.
        self.respawn_delay = 0.0
        # (monotonic seconds, name) per thing the loop already notices, for per-life timing.
        # A list append each, no extra screen reads.
        self.events = []

    def _event(self, name):
        self.events.append((round(time.monotonic(), 3), name))

    def start(self):
        self._stop.clear()
        threading.Thread(target=self._run, daemon=True).start()

    def stop(self):
        self._stop.set()

    def _set_charge(self, want):
        if want != self._charging:
            if want:
                # Right after a sprint Shift came up, a new Shift down was dropped (live CSV 10:48:28).
                time.sleep(max(0.0, self._shift_up + SHIFT_GAP - time.monotonic()))
            (pydirectinput.keyDown if want else pydirectinput.keyUp)(CHARGE_KEY)
            self._charging = want

    def _hold(self, keys):
        """Hold exactly `keys`, releasing anything else this bot was holding."""
        keys = set(keys)
        for key in self._held - keys:
            pydirectinput.keyUp(key)
            if key == CHARGE_KEY:
                self._shift_up = time.monotonic()
        started_walking = bool(keys & set("wasd")) and not self._held & set("wasd")
        for key in keys - self._held - {CHARGE_KEY}:
            pydirectinput.keyDown(key)
        if CHARGE_KEY in keys:
            # Sprint only kicks in when Shift goes down while already walking (otherwise it only walks).
            if started_walking:
                if CHARGE_KEY in self._held:
                    pydirectinput.keyUp(CHARGE_KEY)
                    self._shift_up = time.monotonic()
                time.sleep(max(SPRINT_DELAY, self._shift_up + SHIFT_GAP - time.monotonic()))
                pydirectinput.keyDown(CHARGE_KEY)
            elif CHARGE_KEY not in self._held:
                time.sleep(max(0.0, self._shift_up + SHIFT_GAP - time.monotonic()))
                pydirectinput.keyDown(CHARGE_KEY)
        self._held = keys

    def _release_all(self):
        self._set_charge(False)
        self._hold(())

    def _finish(self, reason):
        self._release_all()
        self.on_stop(reason)

    def _movement(self, now, strafe):
        mode = self.settings.get("movement", "off")
        if mode == "circle":
            if now >= strafe["switch_at"]:
                strafe["side"] = "d" if strafe["side"] == "a" else "a"
                strafe["switch_at"] = now + random.uniform(*STRAFE_SWITCH)
            keys = ("w", strafe["side"])
        else:
            keys = MOVEMENT_KEYS.get(mode, ())
        if keys and self.settings.get("sprint", False):
            keys += (CHARGE_KEY,)  # Shift while moving is sprint, not charge
        return keys

    def _read_level(self, frame):
        """Level and XP off the HUD into stats. A misread (beam glare, LEVEL UP banner) is skipped,
        and so is a jump that can't be real, so one bad read can't spoil the levels-gained count."""
        try:
            level = gc_read.level(frame)
            current, needed, _ = gc_read.xp(frame)
        except OSError:  # Windows OCR unavailable (no language pack): the tile just stays empty
            return
        known = self.stats.get("level")
        if level is None or (known is not None and not known <= level <= known + 50):
            return
        self.stats.setdefault("start_level", level)
        self.stats["level"] = level
        self.stats["levels"] = level - self.stats["start_level"]
        self._event(f"level {level}")
        if current is not None and needed:
            self.stats["xp_percent"] = int(min(100, 100 * current / needed))
            if self.stats["start_level"] == level:
                self.stats.setdefault("start_xp_percent", self.stats["xp_percent"])

    @staticmethod
    def _roblox_focused():
        return user32.GetForegroundWindow() == find_roblox_window()

    def _press_ult(self, slot, grab):
        """Press the slot key until the slot goes dim (fired). Pressing too early can be ignored.

        How long to wait before pressing again adapts to the PC: 3x the slowest of the last few
        real fires, never below FIRE_CHECK, so a laggy game isn't pressed twice."""
        wait = max(FIRE_CHECK, min(FIRE_CHECK_CAP, 3 * max(self.fire_times, default=0.0)))
        hud_gone_since = None
        for attempt in range(1 + FIRE_RETRIES):
            if self._stop.is_set() or not self._roblox_focused():
                return False
            if hud_gone_since is not None:
                return False  # the HUD went and stayed gone through the wait: no retry into a death
            tap(str(slot))
            pressed = time.monotonic()
            deadline = pressed + wait
            while time.monotonic() < deadline and not self._stop.is_set():
                time.sleep(0.05)
                frame = grab()
                if vision.death_buttons_visible(frame):
                    return False
                # Dying: the HUD goes before the death buttons come (video: 7 pressed again on
                # "YOU ARE DEAD"). Timed, not counted: the cast's own flash hides it ~0.2 s.
                hud_up = vision.alive(frame)
                if hud_up:
                    hud_gone_since = None
                elif hud_gone_since is None:
                    hud_gone_since = time.monotonic()
                elif time.monotonic() - hud_gone_since > HUD_GONE_DEATH:
                    return False
                # Dying also dims the hotbar; only a dim slot with the HUD still up is a cast.
                if hud_up and not vision.slot_ready(frame, slot):
                    self.fire_times = (self.fire_times + [time.monotonic() - pressed])[-5:]
                    return True
            if attempt < FIRE_RETRIES:
                self.on_status(f"Slot {slot} didn't fire; pressing again")
        return False

    def _fire_ult(self, slot, grab):
        if not self.settings.get("ult_jump", False):
            fired = self._press_ult(slot, grab)
            if fired:
                self.fired_at, self.ignored_pending = time.monotonic(), None
                # A Shift press any earlier is ignored, so don't spend one there.
                self._sleep(self._post_cast_offset())
            return fired
        # A little run and hop: fire in the air, then land before charging again.
        if user32.GetForegroundWindow() != find_roblox_window():
            return False
        self._hold(("w", "space"))
        time.sleep(JUMP_LIFT)
        fired = self._press_ult(slot, grab)
        self._hold(())
        if fired:
            self._sleep(CAST_WAIT + LAND_WAIT)
        return fired

    def _rise_wait(self):
        """How long after a Shift press the bar must start moving, or the press counts as ignored.
        From this PC's own windups (an early re-press would restart a charge that was starting)."""
        return min(RISE_WAIT_MAX, max(RISE_WAIT_MIN, 1.5 * max(self.rise_delays, default=0.0)))

    def _post_cast_offset(self):
        """Seconds after a fire to put Shift down: halfway between the latest press that was ignored
        and the earliest that worked, until they're close; then the one that worked."""
        dropped, took = self.post_cast["dropped"], self.post_cast["took"]
        if took is None:
            return dropped + 0.5
        return (dropped + took) / 2 if took - dropped > 0.15 else took

    def _learn_post_cast(self, offset, took):
        learned = self.post_cast
        if offset > learned["dropped"] + 3:
            return  # not a recharge right after a fire (stale fire time)
        self._event(f"post-cast press at {offset:.2f}s {'took' if took else 'ignored'}")
        if not took:
            self.ignored_pending = max(self.ignored_pending or 0.0, offset)
            return
        if self.ignored_pending is not None:
            learned["dropped"] = min(POST_CAST_MAX, max(learned["dropped"], self.ignored_pending))
            self.ignored_pending = None
            if learned["took"] is not None and learned["took"] <= learned["dropped"]:
                learned["took"] = None  # the line moved later (lag): find it again
        learned["took"] = offset if learned["took"] is None else min(learned["took"], offset)
        learned["dropped"] = min(learned["dropped"], learned["took"] - 0.15)
        learned["streak"] = learned["streak"] + 1 if learned["took"] - learned["dropped"] <= 0.15 else 0
        if learned["streak"] >= POST_CAST_REPROBE:
            # Never trying earlier would keep one slow spell's line for the whole run.
            learned["dropped"], learned["streak"] = learned["took"] - 0.3, 0

    def _start_press(self, now, frame):
        """Shift down for a charge. Returns the press record _check_press follows."""
        self._set_charge(True)
        self._event("charge")
        return {"at": now, "base": vision.charge_progress(frame), "checked": now,
                "rising": 0, "first_rise": None, "mark": None,
                "post_cast": None if self.fired_at is None else now - self.fired_at}

    def _check_press(self, now, frame, press):
        """Watch the Ki bar after a Shift press; re-press when it shows the press was ignored or the
        charge stopped. Letting go of Shift while it charges restarts the windup, so only then."""
        progress = vision.charge_progress(frame)
        gap, press["checked"] = now - press["checked"], now
        if press["mark"] is None:  # waiting for the bar to start moving
            if progress > press["base"] + RISE_STEP:
                press["rising"] += 1
                if press["first_rise"] is None:
                    # A long gap (the aim) since the last read would make the windup look slow.
                    press["first_rise"] = now if gap < 0.3 else False
            else:
                press["rising"], press["first_rise"] = 0, None
            if press["base"] >= 1.95:
                pass  # bar already full: nothing can rise, wait for the slot
            elif press["rising"] >= 2:  # two reads, so one odd frame can't count as a rise
                if press["first_rise"]:
                    self.rise_delays = (self.rise_delays + [press["first_rise"] - press["at"]])[-5:]
                if press["post_cast"] is not None:
                    self._learn_post_cast(press["post_cast"], took=True)
                self.fired_at = None
                press["mark"] = (now, progress)
            elif not press["rising"] and now - press["at"] > self._rise_wait():
                if press["post_cast"] is not None:
                    self._learn_post_cast(press["post_cast"], took=False)
                return self._repress(frame)
        elif progress > press["mark"][1] + RISE_STEP or progress < press["mark"][1] - 0.3:
            # Higher: still charging. Much lower: the mark was an odd read; measure from here.
            press["mark"] = (now, progress)
        elif now - press["mark"][0] > FLAT_WAIT:
            return self._repress(frame)
        return press

    def _repress(self, frame):
        self._set_charge(False)
        self._event("charge repress")
        time.sleep(SHIFT_GAP)
        return self._start_press(time.monotonic(), frame)

    def _sleep(self, seconds):
        return not self._stop.wait(seconds)

    @staticmethod
    def _close_menu_safely(driver):
        try:
            driver.close_menu()
        except gc_menu.Interrupted:
            pass

    def _menu_driver(self, screen, rect, hwnd):
        def area():
            # Read the window's place at every step: a window moved mid-menu would otherwise get
            # clicks at its old spot (security review).
            return game_area_rect(hwnd) or rect

        def grab():
            left, top, width, height = area()
            return np.asarray(screen.grab({"left": left, "top": top, "width": width, "height": height}))[:, :, :3]

        return gc_menu.MenuDriver(
            grab=grab,
            click=lambda x, y: click(area()[0] + x, area()[1] + y),
            park=lambda x, y: park_cursor(area()[0] + x, area()[1] + y),
            scroll=scroll,
            stopped=lambda: self._stop.is_set() or user32.GetForegroundWindow() != hwnd,
        )

    def _restore_slot(self, screen, rect, hwnd):
        """Put back the move auto-equip replaced. Returns a sentence for the stop message."""
        slot, name = self.replaced
        self.on_status(f"Putting {name} back in slot {slot}")
        driver = self._menu_driver(screen, rect, hwnd)
        result = driver.equip_by_name(name, slot)
        if result != "interrupted":
            self._close_menu_safely(driver)
        if result in ("equipped", "already"):
            self.replaced = None
            return f"Put {name} back in slot {slot}"
        return f"Couldn't put {name} back in slot {slot} ({result})"

    def _shop_for_kame(self, screen, rect, hwnd):
        """Get 4x Kame into the ult slot and close the menu. The hotbar was already read while alive;
        here: equip it if it's owned, and only go to the shop when it isn't (the shop search scrolls
        its whole list to learn a move is owned: 17 s of a death).

        Returns (done_for_this_run, retry) where retry is None, "later" or "error".
        """
        slot = self.settings["ult_slot"]
        replace = self.settings.get("replace_slot", False)
        driver = self._menu_driver(screen, rect, hwnd)
        self.on_status("Looking for 4x Kamehameha in your moves")
        equipped = driver.equip_kame(slot, replace=replace)
        bought = None
        if equipped == "not_owned":
            self.on_status("Checking the shop for 4x Kamehameha")
            bought = driver.buy_kame()
            if bought == "interrupted":
                return False, "error"
            if bought == "too_poor":
                self._close_menu_safely(driver)
                self.on_status("4x Kamehameha needs 5000 Zeni; checking again in 2 min")
                return False, "later"
            if bought == "locked_or_owned":  # not owned and not for sale: still locked
                self._close_menu_safely(driver)
                self.on_status("4x Kamehameha unlocks at level 135; checking again in 2 min")
                return False, "later"
            if bought.startswith("error"):
                self._close_menu_safely(driver)
                self.on_status(f"Shop: {bought}")
                return False, "error"
            equipped = driver.equip_kame(slot, replace=replace)
        if equipped == "interrupted":
            return False, "error"
        self._close_menu_safely(driver)
        if equipped == "equipped" and driver.replaced:
            self.replaced = (slot, driver.replaced)
        if equipped in ("equipped", "already"):
            self.on_status(f"4x Kamehameha is in slot {slot}" + (" (bought it)" if bought == "bought" else ""))
            return True, None
        if equipped == "slot_taken":
            self.on_status(f"Slot {slot} already has another move. Turn on 'Replace' or pick the other slot")
            return True, None
        self.on_status(f"Equip: {equipped}")
        return False, "error"

    def _spend_ki_control(self, screen, rect, hwnd):
        """Skill points into Ki Control up to the target output. Returns (done_for_this_run, retry)."""
        target = float(self.settings.get("ki_control_target", 300))
        driver = self._menu_driver(screen, rect, hwnd)
        self.on_status(f"Checking Ki Control (target {target:g})")
        spender = gc_stats.StatSpender(driver, type_text=pydirectinput.write, press=pydirectinput.press,
                                       say=self.on_status)
        result, detail = spender.spend_to("Ki Control", target)
        if result == "interrupted":
            return False, "error"
        self._close_menu_safely(driver)
        self._event(f"ki control {result}")
        if result == "done":
            self.on_status(f"Ki Control: {detail}")
            return True, None
        if result == "too_few_points":
            self.on_status(f"Not enough skill points yet ({detail}); checking again in 5 min")
            return False, "later"
        self.on_status(f"Ki Control: {result}")
        return False, "error"

    def _run(self):
        try:
            self._loop()
        except Exception as error:  # surface it in the UI instead of dying silently
            self._finish(f"Stopped: error: {error}")

    def _loop(self):
        s = self.settings
        hwnd = find_roblox_window()
        if hwnd is None:
            return self._finish("Stopped: Roblox not found")

        ok, message = auto_window(hwnd)
        self._event(message)
        if not ok:
            return self._finish(f"Stopped: {message}")

        last_seen = time.monotonic()
        self.stats["started"] = time.time()
        next_f = next_scroll = 0.0
        next_relock = time.monotonic() + random.uniform(*RELOCK_EVERY)
        next_jump, second_hop = 0.0, False
        strafe = {"side": "a", "switch_at": 0.0}
        press = None  # the Shift press charging now: see _start_press
        lit_reads = 0  # ult slot read lit this many frames in a row
        last_lock_press = 0.0
        was_locked = None
        chat_seen = False
        life_ult = None  # this life's attack, fixed once the hotbar is seen
        alive_since = None
        death_seen = None
        respawn_clicks = 0
        last_respawn_click = 0.0
        last_chat_click = 0.0
        chat_clicks = 0
        last_leave_click = 0.0
        leave_clicks = 0
        last_denied_click = 0.0
        denied_clicks = 0
        last_timer_seen = None
        loop_started = time.monotonic()
        stop_reads = []
        restore_by, stop_reason = None, ""
        aimed = False
        next_level_read = 0.0
        shop_done = not s.get("auto_buy", False)
        next_shop = 0.0
        shop_errors = 0
        hotbar_checked = False
        stats_done = not s.get("ki_control_spend", False)
        next_stats = 0.0
        stats_errors = 0
        gravity_attempts = 0
        gravity_done = not s.get("auto_gravity", True)
        focus_lost, last_refocus = None, 0.0

        with mss.MSS() as screen:
            while not self._stop.is_set():
                rect = game_area_rect(hwnd)
                if rect is None:
                    return self._finish("Stopped: Roblox window closed")
                left, top, width, height = rect
                if (width, height) != (1920, 1080):
                    return self._finish(f"Stopped: game area is {width}x{height}, start again to fix the window")
                if user32.GetForegroundWindow() != hwnd:
                    self._release_all()
                    self.fired_at = None  # Shift was let go: the next press isn't a post-cast one
                    now = time.monotonic()
                    if focus_lost is None:
                        focus_lost = now
                        self._event(f"focus lost to {_foreground_process()}")
                    # Some PCs flash cmd windows that keep focus after they close; take it back.
                    if s.get("refocus", False) and now - focus_lost > REFOCUS_AFTER and now - last_refocus > REFOCUS_GAP:
                        last_refocus = now
                        _bring_to_front(hwnd)
                        self._event("refocus")
                    self.on_status("Paused: Roblox isn't the active window")
                    self._sleep(0.5 if not s.get("refocus", False) else 0.25)
                    continue
                if focus_lost is not None:
                    away = time.monotonic() - focus_lost
                    self.stats["paused"] += int(round(away))
                    self._event(f"focus back after {away:.1f}s")
                    focus_lost = None

                frame = np.asarray(screen.grab({"left": left, "top": top, "width": width, "height": height}))[:, :, :3]
                now = time.monotonic()

                if vision.disconnected(frame):
                    # Reconnecting lands at the game's spawn, not in GC, so there's nothing to resume.
                    return self._finish("Stopped: Roblox disconnected you (idle kick, lost connection or server kick)")

                seconds = vision.time_limit(frame)
                if seconds is not None:
                    self.time_left = seconds
                    last_timer_seen = now
                    if s["stop_enabled"] and seconds <= s["stop_at_seconds"]:
                        stop_reads.append(seconds)
                        recent = stop_reads[-STOP_CONFIRM_READS:]
                        if len(recent) == STOP_CONFIRM_READS and max(recent) - min(recent) <= 5:
                            reason = f"Stopped: {seconds}s ({vision.format_seconds(seconds)}) left"
                            if not (s.get("restore_slot", True) and self.replaced):
                                return self._finish(reason)
                            if restore_by is None:
                                # Menus are only safe on the death screen: keep going until the next death.
                                restore_by, stop_reason = now + RESTORE_WAIT, reason
                                self.on_status(f"Time's up; putting {self.replaced[1]} back after the next death")
                    else:
                        stop_reads.clear()

                if restore_by is not None and now > restore_by:
                    return self._finish(f"{stop_reason}. Couldn't put {self.replaced[1]} back "
                                        f"in slot {self.replaced[0]} (no death within {RESTORE_WAIT:.0f}s)")

                no = gc_menu.leave_prompt_no(frame)
                if no:
                    if leave_clicks >= 10:
                        return self._finish("Stopped: the 'leave the bot room?' prompt won't close")
                    if now - last_leave_click > 1.0:
                        self._release_all()
                        self.on_status("Answering No to 'leave the bot room?'")
                        click(left + no[0], top + no[1])
                        last_leave_click, leave_clicks = now, leave_clicks + 1
                    self._sleep(0.2)
                    continue
                leave_clicks = 0

                if gc_menu.access_denied(frame):
                    if denied_clicks >= 10:
                        return self._finish("Stopped: the 'Access Denied' box won't close")
                    if now - last_denied_click > 1.0:
                        self._release_all()
                        self.on_status("Closing 'Access Denied'")
                        self._event("access denied")
                        click(left + gc_menu.ACCESS_DENIED_CLOSE[0], top + gc_menu.ACCESS_DENIED_CLOSE[1])
                        last_denied_click, denied_clicks = now, denied_clicks + 1
                    self._sleep(0.2)
                    continue
                denied_clicks = 0

                chat_now = vision.chat_open(frame)
                chat_confirmed = chat_now and chat_seen
                chat_seen = chat_now
                if s.get("hide_chat", True) and chat_clicks < CHAT_MAX_CLICKS and chat_confirmed:
                    if now - last_chat_click > 2.0:
                        chat_clicks += 1
                        self.on_status("Closing chat" if chat_clicks < CHAT_MAX_CLICKS
                                       else "Couldn't close chat; leaving it for this run")
                        click(left + vision.CHAT_ICON_POINT[0], top + vision.CHAT_ICON_POINT[1])
                        last_chat_click = now
                    self._sleep(0.3)
                    continue
                if not chat_now:
                    chat_clicks = 0

                # Only act once the GC timer has been seen, and pause when it goes missing: that's a
                # screen this bot doesn't know (outside GC, session over, a Roblox dialog).
                if last_timer_seen is None or now - last_timer_seen > TIMER_GRACE:
                    self._release_all()
                    if now - (last_timer_seen or loop_started) > LOST_SCREEN_TIMEOUT:
                        return self._finish("Stopped: couldn't see the GC timer for 60s")
                    self.on_status("Waiting for the GC screen (Time Limit not visible)")
                    self._sleep(0.3)
                    continue

                if vision.death_buttons_visible(frame):
                    self._release_all()
                    press, lit_reads = None, 0
                    self.fired_at = None
                    alive_since = None
                    last_seen = now
                    aimed = False
                    was_locked, life_ult = None, None
                    if death_seen is None:
                        death_seen, respawn_clicks = now, 0
                        self.stats["deaths"] += 1
                        self._event("death")
                        if restore_by is not None:
                            return self._finish(f"{stop_reason}. {self._restore_slot(screen, rect, hwnd)}")
                        level = self.stats.get("level")
                        shop_unlocked = (level >= KAME_LEVEL if level is not None
                                         else self.stats["deaths"] > SHOP_BLIND_DEATHS)
                        menu_work = False
                        if not shop_done and shop_unlocked and now >= next_shop:
                            # Menus only stay open while dead, so shopping happens here.
                            self._event("shop")
                            shop_done, retry = self._shop_for_kame(screen, rect, hwnd)
                            self._event(f"shop done {retry or 'ok'}")
                            if retry == "later":
                                next_shop = time.monotonic() + SHOP_RETRY
                            elif retry == "error":
                                shop_errors += 1
                                shop_done = shop_errors >= SHOP_MAX_ERRORS
                            menu_work = True
                        # Same level gate as the shop: at low level there aren't enough points, and each
                        # try costs part of a short life. Same death as the buy, so 4x lives start with it.
                        if not stats_done and shop_unlocked and now >= next_stats:
                            self._event("stats")
                            stats_done, retry = self._spend_ki_control(screen, rect, hwnd)
                            if retry == "later":
                                next_stats = time.monotonic() + STATS_RETRY
                            elif retry == "error":
                                stats_errors += 1
                                stats_done = stats_errors >= SHOP_MAX_ERRORS
                            menu_work = True
                        if menu_work:
                            death_seen = time.monotonic()  # respawn timing starts after the menu work
                            continue
                    first_due = respawn_clicks == 0 and now - death_seen >= self.respawn_delay
                    retry_due = respawn_clicks > 0 and now - last_respawn_click >= RESPAWN_RETRY_GAP
                    if respawn_clicks >= RESPAWN_MAX_CLICKS:
                        return self._finish("Stopped: Respawn didn't respond to 30 clicks")
                    if first_due or retry_due:
                        self.on_status("Dead: clicking Respawn" + (f" (retry {respawn_clicks})" if respawn_clicks else ""))
                        click(left + vision.RESPAWN_POINT[0], top + vision.RESPAWN_POINT[1])
                        respawn_clicks += 1
                        last_respawn_click = now
                    self._sleep(0.1)
                    continue

                if death_seen is not None:
                    # The dialog closed, so the last click is the one that worked.
                    if respawn_clicks == 1:
                        self.respawn_delay = max(0.0, self.respawn_delay - 0.1)
                    elif respawn_clicks > 1:
                        self.respawn_delay = min(RESPAWN_DELAY_CAP, last_respawn_click - death_seen)
                    death_seen = None

                # One "Respawning..." picture is green where alive() looks: the bot started a life on it, saw no hotbar and blasted (L, W/A/D).
                # So a life only starts once the GC timer and the hotbar are readable too.
                starting = alive_since is None and not (
                    seconds is not None and any(vision.slot_has_move(frame, k) for k in range(1, 9)))
                if starting or not vision.alive(frame):
                    # Loading screen, the death text before its buttons slide in, or a one-frame
                    # flash (the charge start briefly hides the HUD tags).
                    self._hold(())
                    if now - last_seen > LOST_SCREEN_TIMEOUT:
                        return self._finish("Stopped: couldn't see the GC screen for 60s")
                    self.on_status("Waiting (respawning / loading)")
                    self._sleep(0.2)
                    continue
                last_seen = now
                if alive_since is None:
                    alive_since = now
                    self._event("spawn")
                if now - alive_since < SPAWN_SETTLE:
                    self._sleep(0.05)
                    continue

                if now >= next_level_read:
                    next_level_read = now + LEVEL_READ_EVERY
                    self._read_level(frame)

                if not shop_done and not hotbar_checked:
                    # Already bought and equipped: skip the shop. Its check of an owned move took 17 s
                    # of a death. Read while alive; the death screen garbles the OCR.
                    hotbar_checked = True
                    try:
                        in_slot = gc_read.hotbar_slot(frame, s["ult_slot"])
                    except OSError:  # Windows OCR unavailable: shop as before
                        in_slot = ""
                    if gc_menu.same_move(in_slot, gc_menu.MOVES["kame"]):
                        shop_done = True
                        self._event("kame already in slot")
                        self.on_status(f"4x Kamehameha is in slot {s['ult_slot']} already; skipping the shop")

                if not gravity_done and gravity_attempts < 3:
                    # Right after respawn, inside the shield. Gravity persists through death,
                    # so one success covers the whole run.
                    gravity_attempts += 1
                    self._release_all()
                    target = int(s.get("gravity", 100))
                    self.on_status(f"Setting gravity to {target}G")
                    box = {"left": left, "top": top, "width": width, "height": height}
                    ok, message = gc_gravity.set_gravity(
                        target,
                        grab=lambda: np.asarray(screen.grab(box))[:, :, :3],
                        click=lambda x, y: click(left + x, top + y),
                        park=lambda x, y: park_cursor(left + x, top + y),
                        tap=tap,
                        # Losing focus mid-way must not send Tab or clicks to another window.
                        stopped=lambda: self._stop.is_set() or user32.GetForegroundWindow() != hwnd,
                    )
                    gravity_done = ok
                    self.on_status(message if ok else f"{message} (try {gravity_attempts}/3)")
                    continue

                slot = s["ult_slot"]
                if life_ult is None:
                    life_ult = s["attack"] == "ult" or (s["attack"] == "auto" and vision.slot_has_move(frame, slot))
                use_ult = life_ult
                if s["attack"] == "ult" and not vision.slot_has_move(frame, slot):
                    return self._finish(f"Stopped: slot {slot} is empty. Put an ult there or pick Auto")

                # Ki blasts need lock-on; ults go where the camera points, and every ult in the
                # clips was fired unlocked (locked Kame hit ~5 bots, unlocked ~10).
                # Two reads in a row before pressing L: one glare frame (beam, LEVEL UP) faking the
                # target panel would otherwise toggle a lock ON mid-ult.
                locked = vision.locked_on(frame)
                if locked == use_ult and was_locked == use_ult and now - last_lock_press > LOCK_RETRY:
                    tap(LOCK_KEY)
                    last_lock_press = now
                    self._event("lock key")
                was_locked = locked

                if use_ult:
                    self._hold(())  # drop any blast-mode movement/sprint before using Shift to charge
                    lit = vision.slot_ready(frame, slot)
                    if not lit and (press is None or not self._charging):
                        # Life start, after a fire, or Shift was let go (focus loss). Not when the
                        # slot is already lit: no Shift tap right before the ult key.
                        press = self._start_press(now, frame)
                    if s.get("ceiling_aim", True) and not aimed:
                        # Once per life (respawning resets the camera). Shift is already down so
                        # the charge runs while the camera turns.
                        if locked or now - last_lock_press < LOCK_SETTLE:
                            self.on_status("Charging; dropping lock-on before aiming")
                            self._sleep(0.05)
                            continue
                        self.on_status("Charging and aiming at the ceiling")
                        grab = lambda: np.asarray(screen.grab({"left": left, "top": top, "width": width, "height": height}))[:, :, :3]
                        found = aim_at_ceiling(grab, left, top, self.aim_memory,
                                               ready=lambda f: vision.slot_ready(f, slot),
                                               stopped=lambda: self._stop.is_set() or user32.GetForegroundWindow() != hwnd)
                        self._event("aimed" if found else "aim missed")
                        if not found:
                            self.on_status("Couldn't find the ceiling ring; firing anyway")
                        aimed = True
                        continue
                    lit_reads = lit_reads + 1 if lit else 0
                    if lit_reads >= 2:
                        lit_reads = 0
                        self._set_charge(False)
                        self._event("ready")
                        self.on_status(f"Firing slot {slot}")
                        grab = lambda: np.asarray(screen.grab({"left": left, "top": top, "width": width, "height": height}))[:, :, :3]
                        if self._fire_ult(slot, grab):
                            self.stats["ults"] += 1
                            self._event("fired")
                        else:
                            self._event("fire failed")
                            self.fired_at = None
                        press = None
                    elif lit_reads:
                        self._sleep(0.05)  # read it once more before letting go of the charge
                    else:
                        press = self._check_press(now, frame, press)
                        self.on_status("Charging")
                        self._sleep(0.1)
                elif not locked:
                    self._set_charge(False)
                    # Keep running while looking for a target, so a lost lock doesn't leave it standing still.
                    self._hold(self._movement(now, strafe))
                    self.on_status("Locking on")
                    self._sleep(0.1)
                else:
                    self._set_charge(False)  # auto mode may have been charging an ult a frame ago
                    self._hold(self._movement(now, strafe))
                    if s.get("relock", True) and now >= next_relock:
                        tap(LOCK_KEY)
                        time.sleep(0.15)
                        tap(LOCK_KEY)
                        last_lock_press = now
                        next_relock = now + random.uniform(*RELOCK_EVERY)
                    if s.get("blast_jump", False) and now >= next_jump:
                        tap("space")
                        second_hop = not second_hop
                        next_jump = now + random.uniform(*(JUMP_GAP if second_hop else JUMP_EVERY))
                    if now >= next_scroll:
                        scroll_down()
                        next_scroll = now + s["scroll_interval"] * random.uniform(0.8, 1.2)
                    if now >= next_f:
                        if self.stats["blasts"] == 0 or self.events[-1][1] != "blasting":
                            self._event("blasting")
                        tap(KI_BLAST_KEY)
                        self.stats["blasts"] += 1
                        next_f = now + s["blast_interval"] * random.uniform(0.8, 1.2)
                    self.on_status("Ki blasts")
                    self._sleep(0.05)

        self._finish("Stopped")
