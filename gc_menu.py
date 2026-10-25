"""Buying and equipping 4x Kaioken Kamehameha through DBOG's menu, done while dead.

Dying closes menus, so the macro only opens them on the death screen, before respawning.
Every click is confirmed by what appears next (titles, rows, the Purchased toast); nothing is
timed blind. Coordinates are 1920x1080 game-area pixels from the 2026-10-21 buy/equip clips.
"""

import math
import re
import time

import cv2
import numpy as np

import gc_read
from gc_vision import ASSETS

MENU_TAB_CLOSED = (22, 594)
MENU_TAB_OPEN = (559, 594)
SHOP_ICON = (34, 657)
CUSTOMIZE_ICON = (34, 541)
ZENI_TAB = (148, 473)
BUY_BUTTON = (997, 818)
LIST_SCROLL_POINT = (296, 640)
PARK_X = 610                      # just right of the menu panel: off its text, short cursor hop
LIST_BOX = (70, 450, 460, 330)    # where list rows live
TITLE_Y = 412
PICKER_ROW_Y = {7: 486, 8: 548}
PRICE_X = (400, 515)              # right end of a shop row: "5000 Zeni" white = affordable, red = not
TOAST_BOX = (670, 50, 580, 100)
NORMAL_MENU_OPEN = 0.35           # s from clicking MENU to the panel showing, on a normal PC (guess; see _learn_lag)
LAG_CAP = 4.0

_TEMPLATES = {}


def _template(name):
    if name not in _TEMPLATES:
        _TEMPLATES[name] = cv2.imread(str(ASSETS / "menu" / f"{name}.png"), cv2.IMREAD_GRAYSCALE)
    return _TEMPLATES[name]


def find(frame, name, box=None, threshold=0.85):
    """Centre (x, y) of the best match of template `name` inside `box`, or None."""
    x0, y0, w, h = box or (0, 0, frame.shape[1], frame.shape[0])
    gray = cv2.cvtColor(np.ascontiguousarray(frame[y0:y0 + h, x0:x0 + w]), cv2.COLOR_BGR2GRAY)
    template = _template(name)
    if gray.shape[0] < template.shape[0] or gray.shape[1] < template.shape[1]:
        return None
    _, score, _, (x, y) = cv2.minMaxLoc(cv2.matchTemplate(gray, template, cv2.TM_CCOEFF_NORMED))
    if score < threshold:
        return None
    return x0 + x + template.shape[1] // 2, y0 + y + template.shape[0] // 2


def title_is(frame, name):
    """Titles need a near-perfect match at the title position: "SHOP" also sits inside "SKILL SHOP"."""
    template = _template(name)
    box = (90, TITLE_Y - 25, 360, 50)
    hit = find(frame, name, box, threshold=0.95)
    return hit is not None and abs(hit[0] - (95 + template.shape[1] // 2)) <= 12


def menu_open(frame):
    """The green MENU tab slides from the left edge to x~559 when the menu opens. This works on every
    page, including ones with no known title (the 7)/8) slot picker, Skill Information)."""
    region = frame[540:650, 545:570].astype(np.int16)
    b, g, r = region[:, :, 0], region[:, :, 1], region[:, :, 2]
    return float(((g > r + 25) & (g > b + 25) & (g > 70)).mean()) > 0.4


ACCESS_DENIED_CLOSE = (960, 950)   # anywhere on the box closes it


def access_denied(frame):
    """The "Gravity Room Training - Access Denied -" box. Live 2026-10-23 it followed answering No
    to the leave prompt during a respawn, stayed up, and XP stopped while it was open."""
    return find(frame, "access_denied", (650, 830, 620, 90), threshold=0.85) is not None


def leave_prompt_no(frame):
    """Centre of "No." on the "Would you like to leave the Gravity Bot Room?" prompt, or None.

    It pops up when you stand (or die) beside EXIT, which is where you respawn, and it blocks the
    menu. Only ever "No." is clicked: it must match the No template AND sit on the left half,
    because "Yes!" walks out of the bot room.
    """
    if not find(frame, "leave_question", (640, 830, 640, 80), threshold=0.85):
        return None
    hit = find(frame, "leave_no", (700, 990, 300, 70), threshold=0.85)
    return hit if hit and hit[0] < 960 else None


def price_affordable(frame, row_y):
    """The price on a shop row is white when you can pay it and red when you can't: True, False,
    or None when neither shows. Judged by hue, not brightness: the menu opened right at death is
    still dimmed by the death fade (a slow PC: "5000 Zeni" read grey ~150, not >200, = "too poor")."""
    region = frame[row_y - 10:row_y + 10, PRICE_X[0]:PRICE_X[1]].astype(np.int16)
    b, g, r = region[:, :, 0], region[:, :, 1], region[:, :, 2]
    white = ((region.min(axis=2) > 110) & (region.max(axis=2) - region.min(axis=2) < 40)).sum()
    red = ((r > 110) & (r - np.maximum(g, b) > 70)).sum()
    if max(white, red) < 30:
        return None
    return bool(white > red)


# The owned list and slot picker use smaller text than the shop list, so each move has two
# templates: row_<move> (shop) and row_<move>_owned (owned list / "7) <name>").
MOVES = {"kame": "4x Kaioken Kamehameha", "fpeb": "Full Power Energy Ball", "bba": "Big Bang Attack",
         "md": "Marbling Drop", "fe": "Final Explosion", "angry": "Angry Kamehameha",
         "bss": "Brave Sword Stream", "cde": "Chaotic Dead End"}


class Interrupted(Exception):
    """Stop pressed or Roblox lost focus: send no more input, not even a menu close."""


class MenuDriver:
    """grab() -> frame, click(x, y), park(x, y), scroll(notches) (negative = down, at the cursor), stopped().

    Waits end as soon as the screen shows the result, so a fast PC runs at full speed. The few
    fixed time limits (when to give up and click again) are multiplied by `lag`, learned from how
    long the menu takes to open, so a slow or laggy PC doesn't get double clicks. It's a class
    attribute: drivers are made per menu visit, the PC's speed carries over.
    """

    lag = 1.0

    def __init__(self, grab, click, park, scroll, stopped):
        self.grab, self.__click, self.__park, self.__scroll, self.stopped = grab, click, park, scroll, stopped
        self._cursor_on_menu, self._cursor_y = True, 540
        self.replaced = None  # name of the move an equip pushed out of its slot

    def _guard(self):
        if self.stopped():
            raise Interrupted

    def _park(self, x, y):
        self._guard()
        self.__park(x, y)

    def _scroll(self, notches):
        self._guard()
        self.__scroll(notches)

    def frame(self):
        self._guard()  # every read checks for stop / focus loss, so waits end promptly
        if self._cursor_on_menu:
            # Step aside at the same height so the cursor doesn't cover the text being matched.
            self._park(PARK_X, self._cursor_y)
            self._cursor_on_menu = False
            time.sleep(0.02)
        return self.grab()

    def click(self, x, y):
        self._guard()
        self.__click(x, y)
        self._cursor_on_menu, self._cursor_y = x < PARK_X, y
        time.sleep(0.05)

    def wait(self, check, timeout=3.0):
        """Poll until check(frame) returns something truthy; return it (or None on timeout)."""
        deadline = time.monotonic() + timeout * MenuDriver.lag
        while time.monotonic() < deadline:
            result = check(self.frame())  # frame() raises Interrupted once stopped()
            if result:
                return result
            time.sleep(0.04)
        return None

    def open_menu(self):
        no = leave_prompt_no(self.frame())
        if no:
            self.click(*no)
            self.wait(lambda f: not leave_prompt_no(f), timeout=1.5)
        for _attempt in range(2):  # a click right after a prompt closes can be swallowed
            if menu_open(self.frame()):
                return True
            self.click(*MENU_TAB_CLOSED)
            clicked = time.monotonic()
            if self.wait(menu_open, timeout=1.5):
                self._learn_lag(time.monotonic() - clicked)
                return True
        return False

    @staticmethod
    def _learn_lag(seconds):
        """Smoothed slowness factor from one menu-open time (1.0 = normal, capped at 4)."""
        if not math.isfinite(seconds) or seconds <= 0:
            return
        sample = max(1.0, min(LAG_CAP, seconds / NORMAL_MENU_OPEN))
        MenuDriver.lag = 0.5 * MenuDriver.lag + 0.5 * sample

    def close_menu(self):
        if not menu_open(self.frame()):
            return True
        self.click(*MENU_TAB_OPEN)
        return bool(self.wait(lambda f: not menu_open(f)))

    def _list_pixels(self, frame):
        x, y, w, h = LIST_BOX
        return cv2.cvtColor(np.ascontiguousarray(frame[y:y + h, x:x + w]), cv2.COLOR_BGR2GRAY).astype(np.int16)

    def search(self, template, max_scrolls=80, end_below=None):
        """Scroll until `template` is in the list; return its centre, or None if it isn't there.

        `template` is a template name, or a function frame -> centre or None (OCR lookups).

        The menu remembers its scroll position, so: down until the list stops moving, then up
        until it stops again. Each scroll waits only until the list has visibly moved.
        `end_below(frame)` true means nothing further down can match (the shop lists locked
        moves last), so going down stops there as if the list had ended.
        """
        direction, turned = -1, False
        frame = self.frame()
        for _ in range(max_scrolls):
            hit = template(frame) if callable(template) else find(frame, template, LIST_BOX)
            if hit:
                return hit
            if direction < 0 and end_below and end_below(frame):
                if turned:
                    return None
                direction, turned = 1, True
            before = self._list_pixels(frame)
            self._park(*LIST_SCROLL_POINT)
            self._cursor_on_menu, self._cursor_y = True, LIST_SCROLL_POINT[1]
            self._scroll(direction)
            moved = False
            deadline = time.monotonic() + 0.4 * MenuDriver.lag
            while time.monotonic() < deadline:
                time.sleep(0.04)
                frame = self.frame()
                if np.abs(self._list_pixels(frame) - before).mean() > 2:
                    moved = True
                    break
            if not moved:  # reached the end in this direction
                if turned:
                    return None
                direction, turned = -direction, True
        return None

    def open_row(self, row, title):
        """Click the list row matching template `row` and wait for `title`."""
        hit = self.search(row)
        if hit is None:
            return False
        _, hit = self.stable_row(row)
        if hit is None:
            return False
        self.click(*hit)
        return bool(self.wait(lambda f: title_is(f, title)))

    def section_page(self, icon, pages):
        """Like _section_page, but if the menu is stuck on a page we don't know (a move's info or
        the slot picker left open by a previous step), close and reopen the menu and try again."""
        page = self._section_page(icon, pages)
        if page is None and self.close_menu() and self.open_menu():
            page = self._section_page(icon, pages)
        return page

    def _section_page(self, icon, pages):
        """Click a section icon and return which of `pages` (title templates) is showing.

        The menu reopens on the last page used, so the section may already be deeper than its root.
        """
        self.click(*icon)
        return self.wait(lambda f: next((p for p in pages if title_is(f, p)), None))

    # ----- buying -----

    def buy_kame(self):
        return self.buy_move("kame")

    def buy_move(self, move, confirm=True):
        """confirm=False stops on the Preview screen without pressing BUY (returns "would_buy")."""
        try:
            return self._buy_move(move, confirm)
        except Interrupted:
            return "interrupted"

    def scroll_to(self, template, end_below=None):
        """Scroll until `template` shows, then return (frame, position) once it's still."""
        if self.search(template, end_below=end_below) is None:
            return self.frame(), None
        return self.stable_row(template)

    def stable_row(self, template):
        """The row's position once the list has stopped sliding in (two matching reads), or None."""
        previous = None
        for _ in range(10):
            frame = self.frame()
            hit = find(frame, template, LIST_BOX)
            if hit and hit == previous:
                return frame, hit
            previous = hit
            time.sleep(0.06)
        return self.frame(), None

    def _buy_move(self, move, confirm):
        """Returns one of: "bought", "locked_or_owned", "too_poor", or an error string."""
        if not self.open_menu():
            return "error: menu didn't open"
        page = self.section_page(SHOP_ICON, ("title_shop", "title_skill_shop", "title_ultimate"))
        if page is None:
            return "error: shop didn't open"
        if page == "title_shop":
            self.click(*ZENI_TAB)
            if not self.wait(lambda f: find(f, "row_skill_shop", LIST_BOX)):
                return "error: Zeni tab didn't open"
            if not self.open_row("row_skill_shop", "title_skill_shop"):
                return "error: Skill Shop didn't open"
            page = "title_skill_shop"
        if page == "title_skill_shop" and not self.open_row("row_ultimate_attacks", "title_ultimate"):
            return "error: Ultimate Attacks didn't open"

        # Locked moves ("???  Level N") come after every buyable one, so the first lock ends the search.
        frame, row = self.scroll_to(f"row_{move}", end_below=lambda f: find(f, "row_locked", LIST_BOX))
        if row is None:
            # Locked rows read "??? Level 135"; once bought the row leaves the shop list.
            return "locked_or_owned"
        # Until the death fade clears the price can read as neither colour; wait for one.
        for _ in range(10):
            affordable = price_affordable(frame, row[1])
            if affordable is not None:
                break
            time.sleep(0.3)
            frame = self.frame()
        if not affordable:
            return "too_poor"
        self.click(*row)
        if not self.wait(lambda f: find(f, "buy_button", (800, 780, 400, 70))):
            return "error: preview didn't open"
        # The list doesn't move once Preview opens: the same row must still be this move.
        still = find(self.frame(), f"row_{move}", (70, row[1] - 20, 460, 40))
        if still is None or abs(still[0] - row[0]) > 4:
            return "error: the selected row changed before BUY; not buying"
        if not confirm:
            return "would_buy"
        self.click(*BUY_BUTTON)
        # Either the "Purchased" toast, or the move leaving the shop list (it only lists unowned
        # moves). The toast alone was missed live on another account.
        row_box = (70, row[1] - 20, 460, 40)
        bought = lambda f: find(f, "purchased", TOAST_BOX) or not find(f, f"row_{move}", row_box)
        if not self.wait(bought, timeout=4.0):
            return "error: no sign the purchase went through"
        return "bought"

    # ----- equipping -----

    def equip_kame(self, slot, replace):
        return self.equip_move("kame", slot, replace)

    def equip_move(self, move, slot, replace):
        """Put a move in ult slot 7 or 8. Returns "equipped", "already", "slot_taken", "not_owned" or an error."""
        try:
            return self._equip_move(move, slot, replace)
        except Interrupted:
            return "interrupted"

    def _open_owned_ultimates(self):
        """Customize > Skills > Ultimate Attacks. Returns None or an error string."""
        if not self.open_menu():
            return "error: menu didn't open"
        page = self.section_page(CUSTOMIZE_ICON, ("title_customize", "title_skills", "title_ultimate"))
        if page is None:
            return "error: Customize didn't open"
        if page == "title_customize":
            if not self.open_row("row_skills", "title_skills"):
                return "error: Skills didn't open"
            page = "title_skills"
        if page == "title_skills" and not self.open_row("row_ultimate_attacks", "title_ultimate"):
            return "error: owned Ultimate Attacks didn't open"
        return None

    def equip_by_name(self, name, slot):
        """Put an owned move in slot 7/8 by its on-screen name (read with OCR, so any move works).
        Used to put back whatever the macro replaced. Returns "equipped", "already" or an error."""
        try:
            return self._equip_by_name(name, slot)
        except Interrupted:
            return "interrupted"

    def _equip_by_name(self, name, slot):
        error = self._open_owned_ultimates()
        if error:
            return error
        row = self.search(lambda f: list_row_named(f, name))
        if row is None:
            return f"error: {name} isn't in your owned ultimates"
        time.sleep(0.06)  # let the list settle, then take the row's final position
        row = list_row_named(self.frame(), name) or row
        self.click(*row)
        if not self.wait(picker_open, timeout=0.8):
            if list_row_named(self.frame(), name) is None:
                return "error: the move list changed after the first click"
            self.click(*row)
        if not self.wait(picker_open):
            return "error: slot picker didn't open"
        if same_move(picker_slot_name(self.frame(), slot), name):
            return "already"
        self.click(296, PICKER_ROW_Y[slot])
        changed = lambda f: not picker_open(f) or same_move(picker_slot_name(f, slot), name)
        if not self.wait(changed):
            return "error: slot didn't change"
        return "equipped"

    def _equip_move(self, move, slot, replace):
        error = self._open_owned_ultimates()
        if error:
            return error
        owned = f"row_{move}_owned"
        _, row = self.scroll_to(owned)
        if row is None:
            return "not_owned"
        # First click shows Skill Information, the second opens the 7)/8) slot picker. Never click
        # blind: if the picker is already up, a second click would land on a slot row.
        self.click(*row)
        if not self.wait(lambda f: picker_open(f, owned), timeout=0.8):
            if find(self.frame(), owned, LIST_BOX) != row:
                return "error: the move list changed after the first click"
            self.click(*row)
        if not self.wait(lambda f: picker_open(f, owned)):
            return "error: slot picker didn't open"
        slot_row = (80, PICKER_ROW_Y[slot] - 20, 440, 40)
        frame = self.frame()
        if move_in_picker_row(frame, slot_row, owned):
            return "already"
        if not find(frame, "row_empty", slot_row) and not replace:
            self.saved_occupant = frame[slot_row[1]:slot_row[1] + slot_row[3], slot_row[0]:slot_row[0] + slot_row[2]].copy()
            return "slot_taken"
        # Remember what was there so the run can put it back at the end.
        self.replaced = picker_slot_name(frame, slot) or None
        self.click(296, PICKER_ROW_Y[slot])
        # Some accounts keep the picker up showing "8) <move>"; others drop straight back to the
        # owned list once the slot is set. Either means the game took the choice.
        if not self.wait(lambda f: move_in_picker_row(f, slot_row, owned) or not picker_open(f)):
            return "error: slot didn't change"
        return "equipped"



def _plain(name):
    return re.sub(r"[^a-z0-9]", "", name.lower())


def same_move(read, name):
    """OCR can split or drop a letter ("Gi antic Hammer"), so compare letters only."""
    read = _plain(read) if read else ""
    return bool(read) and read == _plain(name)


def list_row_named(frame, name):
    """Centre of the list row whose OCR text is `name`, or None. Reads at two zooms because
    Windows OCR drops a different row at each."""
    for scale in (3, 4):
        for text, x, y in gc_read.ocr_lines(frame, LIST_BOX, scale=scale, binarize=False):
            if same_move(text, name):
                return int(x), int(y)
    return None


def picker_slot_name(frame, slot):
    """The move in picker row "7) <name>" / "8) <name>", '' if unreadable, None-ish for Empty."""
    text = gc_read.ocr(frame, (80, PICKER_ROW_Y[slot] - 20, 440, 40), scale=3, binarize=False)
    name = re.sub(r"^\s*[78]\s*\)\s*", "", text)
    name = re.sub(r"\s+", " ", name).strip()
    return "" if name.lower() == "empty" else name


def picker_open(frame, owned=None):
    """The 7)/8) slot picker, recognised by its "7)" / "8)" row prefixes, which show whatever the
    slots hold. (Matching "Empty" or the move itself missed a picker with two other moves in it.)"""
    return bool(find(frame, "picker_7", (80, 460, 50, 40), threshold=0.85)
                or find(frame, "picker_8", (80, 522, 50, 40), threshold=0.85))


def move_in_picker_row(frame, box, owned):
    # In the owned list a name starts at x~95; in the picker "7) " pushes it to ~120.
    hit = find(frame, owned, box)
    return hit is not None and hit[0] - _template(owned).shape[1] // 2 >= 110
