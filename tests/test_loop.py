"""Replays clip frames through Bot._loop with inputs faked, and checks what it pressed.

run: python -I tests/test_loop.py
"""

import itertools
import sys
import threading
from pathlib import Path
from contextlib import ExitStack
from unittest.mock import patch

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import gc_bot  # noqa: E402
REAL_AIM = gc_bot.aim_at_ceiling

REFS = ROOT / "refs"
DEAD = "20.54.23_00107.5.png"
LOADING = "20.39.58_00189.5.png"
ALIVE_DIM = "20.47.14_00003.0.png"     # slot 7 not powered
ALIVE_READY = "20.47.14_00005.5.png"   # slot 7 lit
ALIVE_LOCKED = "20.54.23_00240.0.png"  # target panel showing


def run(frames, settings, max_frames=None, foreground=lambda: 1):
    """Feed `frames` one per loop pass; return the recorded actions and the stop reason."""
    actions, result = [], {}
    images = [np.dstack([cv2.imread(str(REFS / f)), np.zeros((1080, 1920), np.uint8)]) for f in frames]
    index = {"i": 0}
    clock = {"t": 1000.0}
    bot = gc_bot.Bot(settings, on_status=lambda t: None, on_stop=lambda r: result.setdefault("reason", r))
    global LAST_BOT
    LAST_BOT = bot
    if settings.get("auto_buy") or settings.get("ki_control_spend"):
        bot.stats["level"] = settings.get("test_level", 200)  # the shop is only checked from level 135

    class FakeScreen:
        def __enter__(self): return self
        def __exit__(self, *a): pass
        def grab(self, box):
            if index["i"] >= len(images):
                bot.stop()
                return images[-1]
            image = images[index["i"]]
            index["i"] += 1
            clock["t"] += 1.0  # each frame is a second later
            return image

    # Patched only for this run: gc_bot.time is the real time module, shared with every other test file.
    fakes = [(gc_bot.mss, "MSS", FakeScreen),
             (gc_bot, "find_roblox_window", lambda: 1),
             (gc_bot, "game_area_rect", lambda hwnd: (100, 50, 1920, 1080)),
             (gc_bot, "auto_window", lambda hwnd: (True, "Roblox is fullscreen at 1920x1080.")),
             (gc_bot, "user32", type("U", (), {"GetForegroundWindow": staticmethod(foreground)})()),
             (gc_bot, "click", lambda x, y: actions.append(("click", x, y))),
             (gc_bot, "scroll_down", lambda: actions.append(("scroll",))),
             (gc_bot, "tap", lambda key: actions.append(("tap", key))),
             (gc_bot, "aim_at_ceiling", lambda grab, x, y, memory, **checks: actions.append(("aim",)) or True),
             (gc_bot.pydirectinput, "keyDown", lambda key: actions.append(("down", key))),
             (gc_bot.pydirectinput, "keyUp", lambda key: actions.append(("up", key))),
             (gc_bot.time, "sleep", lambda s: None),
             (gc_bot.time, "monotonic", lambda: clock["t"])]
    bot._sleep = lambda s: not bot._stop.is_set()  # no real waiting
    with ExitStack() as stack:
        for target, name, fake in fakes:
            stack.enter_context(patch.object(target, name, fake))
        stack.enter_context(patch.object(bot, "_read_level"))
        bot._loop()
    return actions, result.get("reason")


def base(**overrides):
    settings = {"auto_gravity": False, "attack": "ult", "ult_slot": 7, "blast_interval": 0.4, "scroll_interval": 1.0,
                "stop_enabled": False, "stop_at_seconds": 60, "ceiling_aim": False}
    settings.update(overrides)
    return settings


def test_dead_clicks_respawn_at_offset_point():
    actions, _ = run([DEAD], base())
    assert actions[0] == ("click", 100 + 960, 50 + 550), actions


def test_loading_screen_sends_nothing():
    actions, _ = run([LOADING, LOADING], base())
    assert [a for a in actions if a[0] in ("click", "tap", "scroll")] == [], actions


def test_kame_charges_then_fires_when_slot_lights():
    actions, _ = run([ALIVE_DIM, ALIVE_DIM, ALIVE_READY, ALIVE_READY], base())
    assert ("down", "shift") in actions
    fire = actions.index(("tap", "7"))
    assert actions.index(("up", "shift")) < fire, "shift must be released before firing"


def test_presses_l_when_not_locked():
    actions, _ = run([ALIVE_DIM, ALIVE_DIM], base(attack="blasts"))
    assert ("tap", "l") in actions
    assert ("tap", "f") not in actions and ("scroll",) not in actions, "no blasting or scrolling until locked"


def test_blasts_press_f_and_scroll_when_locked():
    actions, _ = run([ALIVE_LOCKED, ALIVE_LOCKED], base(attack="blasts"))
    assert ("tap", "l") not in actions, "L toggles, so it must not be pressed while locked"
    assert ("tap", "f") in actions and ("scroll",) in actions


def test_waits_after_respawn_before_input():
    actions, _ = run([ALIVE_DIM], base())
    assert actions == [], "first alive frame only starts the settle wait"


def test_represses_shift_when_slot_never_lights():
    actions, _ = run([ALIVE_DIM] * 6, base())
    assert actions.count(("down", "shift")) >= 2, actions


def test_climbing_ki_is_never_interrupted():
    # However slow the charge (race, Ki Control), letting go of Shift while it climbs restarts it.
    climb = iter([0.05 * i for i in range(40)])
    with patch.object(gc_bot.vision, "charge_progress", side_effect=lambda frame: next(climb)):
        actions, _ = run([ALIVE_DIM] * 9, base())
    assert actions.count(("down", "shift")) == 1, actions


def test_flat_ki_gets_shift_pressed_again():
    with patch.object(gc_bot.vision, "charge_progress", return_value=0.0):
        actions, _ = run([ALIVE_DIM] * 4, base())
    assert actions.count(("down", "shift")) >= 2, actions


def test_full_bar_waits_for_the_slot_instead_of_repressing():
    with patch.object(gc_bot.vision, "charge_progress", return_value=2.0):
        actions, _ = run([ALIVE_DIM] * 8, base())
    assert actions.count(("down", "shift")) == 1, actions


def test_one_bright_frame_is_not_ready():
    # A flash frame that reads lit, then dim again: no ult press.
    actions, _ = run([ALIVE_DIM, ALIVE_DIM, ALIVE_READY, ALIVE_DIM, ALIVE_DIM], base())
    assert ("tap", "7") not in actions, actions


def test_cyan_flash_does_not_read_as_ready():
    frame = cv2.imread(str(REFS / ALIVE_DIM))
    y = gc_bot.vision.HOTBAR_SLOT1_Y + 6 * gc_bot.vision.HOTBAR_SLOT_SPACING
    for bgr in ((194, 154, 10), (123, 120, 22), (72, 96, 30)):  # flash frames from both test PCs' videos
        frame[y - 8:y + 8, 1665:1885] = bgr
        assert not gc_bot.vision.slot_ready(frame, 7), bgr
    frame[y - 8:y + 8, 1665:1885] = (40, 140, 68)  # really lit
    assert gc_bot.vision.slot_ready(frame, 7)


def test_ignored_press_after_a_cast_is_learned():
    bot = gc_bot.Bot(base(), lambda _: None, lambda _: None)
    learn = bot._learn_post_cast
    assert bot._post_cast_offset() == gc_bot.POST_CAST_DROPPED + 0.5
    learn(3.0, took=False)
    learn(4.4, took=True)                 # the re-press worked: 3.0 really was too early
    assert bot._post_cast_offset() == 3.7  # halfway
    learn(3.7, took=True)
    assert abs(bot._post_cast_offset() - 3.35) < 1e-9
    learn(3.35, took=False)
    bot.ignored_pending = None            # died before a re-press: proves nothing
    assert abs(bot._post_cast_offset() - 3.35) < 1e-9
    learn(3.35, took=False)
    learn(4.8, took=True)
    assert abs(bot._post_cast_offset() - 3.525) < 1e-9
    learn(10.0, took=False)               # stale fire time: ignored
    assert bot.ignored_pending is None
    learn(3.8, took=False)                # lag: the line moved past what worked before
    learn(5.2, took=True)
    assert bot.post_cast["took"] == 5.2 and abs(bot._post_cast_offset() - 4.5) < 1e-9


def test_learned_line_is_retried_earlier_and_capped():
    bot = gc_bot.Bot(base(), lambda _: None, lambda _: None)
    bot.post_cast.update(dropped=3.3, took=3.4)
    for _ in range(gc_bot.POST_CAST_REPROBE):
        bot._learn_post_cast(3.4, took=True)
    assert abs(bot._post_cast_offset() - 3.25) < 1e-9  # tries a bit earlier now and then
    bot._learn_post_cast(5.4, took=False)
    bot._learn_post_cast(5.5, took=True)
    assert bot.post_cast["dropped"] <= gc_bot.POST_CAST_MAX


def test_slow_windup_widens_the_ignored_press_check():
    bot = gc_bot.Bot(base(), lambda _: None, lambda _: None)
    assert bot._rise_wait() == gc_bot.RISE_WAIT_MIN
    bot.rise_delays = [0.6, 1.4]
    assert abs(bot._rise_wait() - 2.1) < 1e-9
    bot.rise_delays = [5.0]
    assert bot._rise_wait() == gc_bot.RISE_WAIT_MAX


def test_respawn_retries_then_learns_the_delay():
    actions, _ = run([DEAD, DEAD, DEAD, LOADING], base())
    clicks = [a for a in actions if a[0] == "click"]
    assert len(clicks) == 3, clicks  # first click + 2 retries, one per second
    assert LAST_BOT.respawn_delay == 2.0, LAST_BOT.respawn_delay


def test_circle_movement_holds_w_and_a_side():
    actions, _ = run([ALIVE_LOCKED] * 3, base(attack="blasts", movement="circle"))
    downs = {a[1] for a in actions if a[0] == "down"}
    assert "w" in downs and downs & {"a", "d"}, downs
    assert ("up", "w") in actions, "movement released when the run stops"


def test_kame_mode_never_moves():
    actions, _ = run([ALIVE_DIM] * 3, base(movement="circle"))
    assert not any(a[0] == "down" and a[1] in "wad" for a in actions), actions


def test_auto_uses_ult_when_slot_has_a_move():
    actions, _ = run([ALIVE_DIM] * 3, base(attack="auto"))  # slot 7 holds Full Power Energy Wave
    assert ("down", "shift") in actions


def test_auto_uses_blasts_when_slot_is_empty():
    actions, _ = run([ALIVE_LOCKED] * 3, base(attack="auto", ult_slot=8))  # slot 8 empty in that frame
    assert ("tap", "f") in actions and ("down", "shift") not in actions


def test_ult_mode_stops_on_empty_slot():
    _, reason = run([ALIVE_DIM] * 2, base(ult_slot=8))
    assert "slot 8 is empty" in reason, reason


def test_closes_open_chat_once_then_carries_on():
    # chat on in the first two frames: one read alone isn't trusted
    actions, _ = run(["21.11.48_00020.0.png", "21.11.48_00020.0.png", ALIVE_LOCKED], base(attack="blasts"))
    assert actions[0] == ("click", 100 + 138, 50 + 35), actions
    assert sum(a[0] == "click" for a in actions) == 1


def test_one_chat_read_alone_clicks_nothing():
    actions, _ = run(["21.11.48_00020.0.png", ALIVE_LOCKED], base(attack="blasts"))
    assert not any(a[0] == "click" for a in actions), actions


def test_green_respawn_art_does_not_start_a_life():
    # Live 2026-10-23: this loading picture passes alive(); the bot blasted on it (L + W/A/D) in ult runs.
    art = str(ROOT / "live" / "loading_art_green.png")
    actions, _ = run([DEAD, art, art, art, art], base(attack="auto", movement="circle", sprint=True))
    assert not any(a[0] in ("tap", "down") for a in actions), actions


def test_leaves_chat_alone_when_toggle_off():
    actions, _ = run(["21.11.48_00020.0.png"], base(attack="blasts", hide_chat=False))
    assert not any(a[0] == "click" for a in actions), actions


def test_sprint_holds_shift_only_while_moving():
    actions, _ = run([ALIVE_LOCKED] * 3, base(attack="blasts", movement="w", sprint=True))
    downs = [a[1] for a in actions if a[0] == "down"]
    assert "w" in downs and "shift" in downs, downs
    actions, _ = run([ALIVE_LOCKED] * 3, base(attack="blasts", movement="off", sprint=True))
    assert ("down", "shift") not in actions, "standing still with Shift would charge"


def test_jump_fire_hops_then_fires_in_the_air():
    actions, _ = run([ALIVE_DIM, ALIVE_DIM, ALIVE_READY, ALIVE_READY], base(ult_jump=True))
    fire = actions.index(("tap", "7"))
    assert ("down", "space") in actions[:fire] and ("up", "space") in actions[fire:], actions


def test_one_low_timer_read_does_not_stop():
    _, reason = run([ALIVE_DIM, ALIVE_LOCKED, ALIVE_DIM], base(stop_enabled=True, stop_at_seconds=6600))
    assert reason == "Stopped", reason  # 6447 once (ALIVE_LOCKED), not three times in a row


def test_no_input_until_gc_timer_seen():
    actions, _ = run(["20.39.58_00142.5.png"] * 3, base(attack="blasts", hide_chat=False))  # timer unreadable
    assert actions == [], actions


def test_chat_close_gives_up_after_five_clicks():
    actions, _ = run(["21.11.48_00020.0.png"] * 14, base(attack="blasts"))
    assert sum(a[0] == "click" for a in actions) == 5


def test_respawn_delay_is_capped():
    actions, _ = run([DEAD] * 8 + [LOADING], base())
    assert LAST_BOT.respawn_delay == 3.0, LAST_BOT.respawn_delay


def test_ult_mode_turns_lock_on_off():
    actions, _ = run([ALIVE_LOCKED] * 3, base(ult_slot=7, attack="ult"))  # locked frame, slot 7 has a move
    assert ("tap", "l") in actions, "locked ult shots hit fewer bots, so unlock first"


class FakeDriver:
    calls = []
    buy_result, equip_result = "bought", "equipped"
    owned = False
    replaced_name = None

    def __init__(self, **kw):
        self.replaced = FakeDriver.replaced_name

    def equip_by_name(self, name, slot):
        FakeDriver.calls.append(f"restore {name} {slot}")
        return "equipped"

    def buy_kame(self):
        FakeDriver.calls.append("buy")
        FakeDriver.owned = FakeDriver.owned or FakeDriver.buy_result == "bought"
        return FakeDriver.buy_result

    def equip_kame(self, slot, replace):
        FakeDriver.calls.append(f"equip{slot}{'r' if replace else ''}")
        return FakeDriver.equip_result if FakeDriver.owned else "not_owned"

    def close_menu(self):
        FakeDriver.calls.append("close")
        return True


def test_auto_buy_shops_once_on_death_then_respawns():
    gc_bot.gc_menu.MenuDriver = FakeDriver
    FakeDriver.calls, FakeDriver.owned = [], False
    actions, _ = run([DEAD, DEAD, LOADING, DEAD, DEAD], base(auto_buy=True, ult_slot=8))
    assert FakeDriver.calls == ["equip8", "buy", "equip8", "close"], FakeDriver.calls  # second death: done, no shop
    assert any(a[0] == "click" for a in actions), "still respawns afterwards"


def test_auto_buy_skips_shop_when_kame_already_on_the_hotbar():
    gc_bot.gc_menu.MenuDriver = FakeDriver
    FakeDriver.calls, FakeDriver.owned = [], False
    with patch.object(gc_bot.gc_read, "hotbar_slot", return_value="4x Kaioken Kamehameha"):
        run([ALIVE_DIM, ALIVE_DIM, DEAD, DEAD], base(auto_buy=True))
    assert FakeDriver.calls == [], FakeDriver.calls
    with patch.object(gc_bot.gc_read, "hotbar_slot", return_value="Energy Wave"):
        run([ALIVE_DIM, ALIVE_DIM, DEAD, DEAD], base(auto_buy=True))
    assert "buy" in FakeDriver.calls, FakeDriver.calls


def test_owned_kame_is_equipped_without_the_shop():
    gc_bot.gc_menu.MenuDriver = FakeDriver
    FakeDriver.calls, FakeDriver.owned = [], True
    run([DEAD, DEAD, LOADING, DEAD], base(auto_buy=True))
    assert FakeDriver.calls == ["equip7", "close"], FakeDriver.calls


def test_auto_buy_skips_shop_below_kame_level():
    gc_bot.gc_menu.MenuDriver = FakeDriver
    FakeDriver.calls, FakeDriver.owned = [], False
    actions, _ = run([DEAD, DEAD, LOADING, DEAD, DEAD], base(auto_buy=True, test_level=134))
    assert FakeDriver.calls == [], FakeDriver.calls
    assert any(a[0] == "click" for a in actions), "respawns without shopping"


class FakeSpender:
    calls = []
    result = ("done", "Ki Control 316 -> 300.2")

    def __init__(self, driver, type_text, press, say):
        pass

    def spend_to(self, name, target, confirm=True):
        FakeSpender.calls.append((name, target, confirm))
        return FakeSpender.result


def test_ki_control_spend_once_on_death_when_on():
    gc_bot.gc_menu.MenuDriver = FakeDriver
    FakeSpender.calls, FakeSpender.result = [], ("done", "")
    with patch.object(gc_bot.gc_stats, "StatSpender", FakeSpender):
        actions, _ = run([DEAD, DEAD, LOADING, DEAD, DEAD], base(ki_control_spend=True, ki_control_target=300))
        assert FakeSpender.calls == [("Ki Control", 300.0, True)], FakeSpender.calls
        assert any(a[0] == "click" for a in actions), "still respawns afterwards"
        FakeSpender.calls = []
        run([DEAD, DEAD], base())
        assert FakeSpender.calls == [], "off by default"


def test_ki_control_too_few_points_waits():
    gc_bot.gc_menu.MenuDriver = FakeDriver
    FakeSpender.calls, FakeSpender.result = [], ("too_few_points", "")
    with patch.object(gc_bot.gc_stats, "StatSpender", FakeSpender):
        run([DEAD, DEAD, LOADING, DEAD], base(ki_control_spend=True))
    assert len(FakeSpender.calls) == 1, FakeSpender.calls  # not retried within 5 minutes


def test_ki_control_not_checked_below_kame_level():
    gc_bot.gc_menu.MenuDriver = FakeDriver
    FakeSpender.calls, FakeSpender.result = [], ("done", "")
    with patch.object(gc_bot.gc_stats, "StatSpender", FakeSpender):
        run([DEAD, DEAD, LOADING, DEAD], base(ki_control_spend=True, test_level=60))
    assert FakeSpender.calls == []


def test_auto_buy_too_poor_closes_menu_and_waits():
    gc_bot.gc_menu.MenuDriver = FakeDriver
    FakeDriver.calls, FakeDriver.owned, FakeDriver.buy_result = [], False, "too_poor"
    run([DEAD, DEAD, LOADING, DEAD], base(auto_buy=True))
    FakeDriver.buy_result = "bought"
    assert FakeDriver.calls == ["equip7", "buy", "close"], FakeDriver.calls  # not retried within 2 minutes


def test_replaced_move_is_put_back_after_stop_time():
    gc_bot.gc_menu.MenuDriver = FakeDriver
    FakeDriver.calls, FakeDriver.owned, FakeDriver.replaced_name = [], False, "Final Explosion"
    # ALIVE_DIM reads 6895 s left: past the stop time, so the next death puts the old move back.
    _, reason = run([DEAD, DEAD, LOADING] + [ALIVE_DIM] * 4 + [DEAD, DEAD],
                    base(auto_buy=True, replace_slot=True, stop_enabled=True, stop_at_seconds=7000))
    FakeDriver.replaced_name = None
    assert "restore Final Explosion 7" in FakeDriver.calls, FakeDriver.calls
    assert "Put Final Explosion back in slot 7" in reason, reason


def test_no_restore_when_turned_off():
    gc_bot.gc_menu.MenuDriver = FakeDriver
    FakeDriver.calls, FakeDriver.owned, FakeDriver.replaced_name = [], False, "Final Explosion"
    _, reason = run([DEAD, DEAD, LOADING] + [ALIVE_DIM] * 4 + [DEAD, DEAD],
                    base(auto_buy=True, replace_slot=True, restore_slot=False, stop_enabled=True, stop_at_seconds=7000))
    FakeDriver.replaced_name = None
    assert not any(c.startswith("restore") for c in FakeDriver.calls), FakeDriver.calls
    assert reason.startswith("Stopped: 6895s"), reason


def test_ceiling_aim_once_per_life_while_charging():
    actions, _ = run([ALIVE_DIM, ALIVE_DIM, ALIVE_DIM, DEAD, LOADING, ALIVE_DIM, ALIVE_DIM], base(ceiling_aim=True))
    assert actions.count(("aim",)) == 2, actions  # one per life
    assert actions.index(("down", "shift")) < actions.index(("aim",)), "charges first, aims while charging"


def test_no_ceiling_aim_for_ki_blasts():
    actions, _ = run([ALIVE_DIM] * 4, base(attack="blasts", ceiling_aim=True))
    assert ("aim",) not in actions, actions


def test_disconnect_box_stops_the_run():
    actions, reason = run(["dc_idle.png"], base())
    assert "disconnected" in reason and actions == [], (reason, actions)


def test_counts_deaths_and_ults():
    run([DEAD, LOADING, ALIVE_DIM, ALIVE_READY, ALIVE_READY, ALIVE_DIM], base())  # slot dims after the press = fired
    assert LAST_BOT.stats["deaths"] == 1 and LAST_BOT.stats["ults"] >= 1, LAST_BOT.stats


def test_ult_press_retried_when_slot_stays_lit():
    actions, _ = run([ALIVE_DIM, ALIVE_READY, ALIVE_READY, ALIVE_READY, ALIVE_READY], base())
    assert actions.count(("tap", "7")) >= 3, actions  # first press + 2 retries, then again next frame
    assert LAST_BOT.stats["ults"] == 0, "an ignored press isn't counted"


def test_leave_prompt_gets_no_never_yes():
    actions, _ = run(["leave_prompt.png"], base())
    clicks = [a for a in actions if a[0] == "click"]
    assert clicks and clicks[0] == ("click", 100 + 828, 50 + 1026), clicks  # "No.", left button


def test_stops_at_time_left():
    # ALIVE_DIM reads 6895 seconds left.
    actions, reason = run([ALIVE_DIM] * 3, base(stop_enabled=True, stop_at_seconds=7000))
    assert reason.startswith("Stopped: 6895s (1h 54m 55s)"), reason


def test_charge_released_on_death():
    actions, _ = run([ALIVE_DIM, ALIVE_DIM, DEAD], base())
    down = actions.index(("down", "shift"))
    assert ("up", "shift") in actions[down:], actions


def test_ceiling_aim_off_never_aims():
    actions, _ = run([ALIVE_DIM] * 4, base(ceiling_aim=False))
    assert ("aim",) not in actions, actions


def test_aim_no_ring_stops_after_one_read():
    memory = list(gc_bot.AIM_START)
    with patch.object(gc_bot, "camera_drag") as drag, patch.object(gc_bot, "park_cursor"), \
            patch.object(gc_bot, "_send_mouse"), patch.object(gc_bot.time, "sleep"), \
            patch.object(gc_bot.gc_aim, "ring_centre", return_value=None) as read:
        assert not REAL_AIM(lambda: None, 0, 0, memory)
        assert read.call_count == 1 and drag.call_count == 2
        assert memory == list(gc_bot.AIM_START)


def test_aim_single_lamp_near_target_is_not_a_ring():
    with patch.object(gc_bot, "camera_drag"), patch.object(gc_bot, "park_cursor") as park, \
            patch.object(gc_bot, "_send_mouse"), patch.object(gc_bot.time, "sleep"), \
            patch.object(gc_bot.gc_aim, "ring_centre", return_value=(*gc_bot.gc_aim.TARGET, 1)):
        assert not REAL_AIM(lambda: None, 0, 0, list(gc_bot.AIM_START))
        assert park.call_count == 1, "only the initial cursor park"


def test_aim_flipping_reads_have_bounded_attempts():
    memory = list(gc_bot.AIM_START)
    reads = [(100, 500, 1), (1820, 500, 1)] * gc_bot.AIM_CORRECTIONS
    with patch.object(gc_bot, "camera_drag") as drag, patch.object(gc_bot, "park_cursor"), \
            patch.object(gc_bot, "_send_mouse"), patch.object(gc_bot.time, "sleep"), \
            patch.object(gc_bot.gc_aim, "ring_centre", side_effect=reads) as read:
        assert not REAL_AIM(lambda: None, 0, 0, memory)
        assert read.call_count == gc_bot.AIM_CORRECTIONS
        assert drag.call_count == 2 + gc_bot.AIM_CORRECTIONS


def test_aim_memory_cannot_grow_across_failed_lives():
    for centre in ((1800, 1000, 1), (0, 0, 1)):
        memory = list(gc_bot.AIM_START)
        with patch.object(gc_bot, "camera_drag") as drag, patch.object(gc_bot, "park_cursor"), \
                patch.object(gc_bot, "_send_mouse"), patch.object(gc_bot.time, "sleep"), \
                patch.object(gc_bot.gc_aim, "ring_centre", return_value=centre):
            for _ in range(100):
                assert not REAL_AIM(lambda: None, 0, 0, memory)
            budget = gc_bot.AIM_CORRECTIONS * gc_bot.gc_aim.MAX_STEP
            assert all(abs(value - start) <= budget for value, start in zip(memory, gc_bot.AIM_START)), memory
            assert all(abs(call.args[0]) <= abs(gc_bot.AIM_START[0]) + budget for call in drag.call_args_list)


def test_level_jump_filter():
    bot = gc_bot.Bot(base(), lambda _: None, lambda _: None)
    for level, expected in ((None, None), (100, 100), (99, 100), (151, 100), (100000, 100), (150, 150), (150, 150)):
        with patch.object(gc_bot.gc_read, "level", return_value=level), \
                patch.object(gc_bot.gc_read, "xp", return_value=(25, 100, "")):
            bot._read_level(None)
        assert bot.stats.get("level") == expected, bot.stats
    assert bot.stats["start_level"] == 100 and bot.stats["levels"] == 50
    assert bot.stats["xp_percent"] == 25


from contextlib import ExitStack, contextmanager


@contextmanager
def live_hud(dead=False):
    """_press_ult's own checks: focused Roblox, HUD up (or the death screen)."""
    with ExitStack() as stack:
        stack.enter_context(patch.object(gc_bot.Bot, "_roblox_focused", return_value=True))
        stack.enter_context(patch.object(gc_bot.vision, "death_buttons_visible", return_value=dead))
        stack.enter_context(patch.object(gc_bot.vision, "alive", return_value=not dead))
        yield


def test_ult_dimmed_by_death_is_not_a_cast():
    bot = gc_bot.Bot(base(), lambda _: None, lambda _: None)
    with patch.object(gc_bot, "tap"), patch.object(gc_bot.time, "sleep"),             patch.object(gc_bot.vision, "slot_ready", return_value=False), live_hud(dead=True):
        assert not bot._press_ult(7, lambda: None)
    with patch.object(gc_bot, "tap"), patch.object(gc_bot.time, "sleep"),             patch.object(gc_bot.vision, "slot_ready", return_value=False),             patch.object(gc_bot.Bot, "_roblox_focused", return_value=True),             patch.object(gc_bot.vision, "death_buttons_visible", return_value=False),             patch.object(gc_bot.vision, "alive", side_effect=[False, False, True]):
        assert bot._press_ult(7, lambda: None)  # the cast's flash hides the HUD briefly; HUD back = cast
    with patch.object(gc_bot, "tap") as tap, patch.object(gc_bot.time, "sleep"),             patch.object(gc_bot.vision, "slot_ready", return_value=True),             patch.object(gc_bot.Bot, "_roblox_focused", return_value=True),             patch.object(gc_bot.vision, "death_buttons_visible", return_value=False),             patch.object(gc_bot.vision, "alive", return_value=False),             patch.object(gc_bot.time, "monotonic", side_effect=itertools.count(0, 0.1)):
        assert not bot._press_ult(7, lambda: None)  # dying ("YOU ARE DEAD", no buttons yet)
    assert tap.call_count == 1, "no more ult presses on the death screen"


def test_ult_not_pressed_without_focus():
    bot = gc_bot.Bot(base(), lambda _: None, lambda _: None)
    with patch.object(gc_bot, "tap") as tap, patch.object(gc_bot.Bot, "_roblox_focused", return_value=False):
        assert not bot._press_ult(7, lambda: None)
    assert tap.call_count == 0


def test_ult_wait_bounds_and_retry_count():
    for history, expected in (([], gc_bot.FIRE_CHECK), ([0.01], gc_bot.FIRE_CHECK),
                               ([0.3], 0.9), ([10000], gc_bot.FIRE_CHECK_CAP)):
        bot = gc_bot.Bot(base(), lambda _: None, lambda _: None)
        bot.fire_times = history
        clock, pressed = [0.0], []
        def sleep(seconds):
            clock[0] += seconds
        with patch.object(gc_bot.time, "monotonic", side_effect=lambda: clock[0]), \
                patch.object(gc_bot.time, "sleep", side_effect=sleep), \
                patch.object(gc_bot, "tap", side_effect=lambda key: pressed.append(clock[0])), \
                patch.object(gc_bot.vision, "slot_ready", return_value=True), live_hud():
            assert not bot._press_ult(7, lambda: None)
        assert len(pressed) == 1 + gc_bot.FIRE_RETRIES, pressed
        durations = [b - a for a, b in zip(pressed, pressed[1:] + [clock[0]])]
        assert all(expected - 1e-6 <= seconds <= expected + 0.05 + 1e-6 for seconds in durations), durations


def test_ult_stopped_run_never_presses_again():
    for stop_before in (False, True):
        bot = gc_bot.Bot(base(), lambda _: None, lambda _: None)
        if stop_before:
            bot.stop()
        def sleep(seconds):
            bot.stop()
        with patch.object(gc_bot, "tap") as tap, patch.object(gc_bot.time, "sleep", side_effect=sleep), \
                patch.object(gc_bot.vision, "slot_ready", return_value=True), live_hud():
            assert not bot._press_ult(7, lambda: None)
        assert tap.call_count == (0 if stop_before else 1), tap.call_count


def test_ult_fire_history_is_recent_and_bounded():
    bot = gc_bot.Bot(base(), lambda _: None, lambda _: None)
    bot.fire_times = [0.1] * 5
    clock = [0.0]
    def sleep(seconds):
        clock[0] += seconds
    with patch.object(gc_bot.time, "monotonic", side_effect=lambda: clock[0]), \
            patch.object(gc_bot.time, "sleep", side_effect=sleep), patch.object(gc_bot, "tap"), \
            patch.object(gc_bot.vision, "slot_ready", return_value=False), live_hud():
        assert bot._press_ult(7, lambda: None)
    assert len(bot.fire_times) == 5 and abs(bot.fire_times[-1] - 0.05) < 1e-6, bot.fire_times


def test_restore_timeout_survives_timer_jitter():
    gc_bot.gc_menu.MenuDriver = FakeDriver
    FakeDriver.calls, FakeDriver.owned = [], False
    with patch.object(FakeDriver, "replaced_name", "Final Explosion"), \
            patch.object(gc_bot.vision, "time_limit", side_effect=[8000] * 3 + [6895] * 3 + [7001] * 6), \
            patch.object(gc_bot, "RESTORE_WAIT", 2.0):
        _, reason = run([DEAD, DEAD, LOADING] + [ALIVE_DIM] * 8,
                        base(auto_buy=True, replace_slot=True, stop_enabled=True, stop_at_seconds=7000))
    assert "no death within 2s" in reason, reason
    assert not any(call.startswith("restore") for call in FakeDriver.calls), FakeDriver.calls


def test_restore_timeout_survives_missing_timer():
    gc_bot.gc_menu.MenuDriver = FakeDriver
    FakeDriver.calls, FakeDriver.owned = [], False
    with patch.object(FakeDriver, "replaced_name", "Final Explosion"), \
            patch.object(gc_bot.vision, "time_limit", side_effect=[8000] * 3 + [6895] * 3 + [None] * 6), \
            patch.object(gc_bot, "RESTORE_WAIT", 2.0):
        _, reason = run([DEAD, DEAD, LOADING] + [ALIVE_DIM] * 8,
                        base(auto_buy=True, replace_slot=True, stop_enabled=True, stop_at_seconds=7000))
    assert "no death within 2s" in reason, reason


if __name__ == "__main__":
    tests = [(n, f) for n, f in globals().items() if n.startswith("test_")]
    failed = 0
    for name, test in tests:
        try:
            test()
            print("PASS", name)
        except AssertionError as error:
            failed += 1
            print("FAIL", name, error)
    sys.exit(1 if failed else 0)



def test_refocus_takes_roblox_back_after_a_window_steals_focus():
    """A cmd flash leaves another window in front; with refocus on, the bot takes Roblox back
    instead of pausing for good, and logs who had focus."""
    state = {"fg": 2}
    with patch.object(gc_bot, "_bring_to_front", side_effect=lambda hwnd: state.update(fg=hwnd)) as bring,          patch.object(gc_bot, "_foreground_process", return_value="cmd.exe"),          patch.object(gc_bot, "REFOCUS_AFTER", -1.0):  # the test clock only moves on screen grabs
        run([DEAD, DEAD], base(refocus=True), foreground=lambda: state["fg"])
    names = [name for _, name in LAST_BOT.events]
    assert bring.called
    assert "focus lost to cmd.exe" in names
    assert any(name.startswith("focus back") for name in names)


def test_no_refocus_when_setting_off():
    calls = {"n": 0}
    def foreground():
        calls["n"] += 1
        if calls["n"] > 20:
            LAST_BOT.stop()
        return 2
    with patch.object(gc_bot, "_bring_to_front") as bring,          patch.object(gc_bot, "_foreground_process", return_value="cmd.exe"):
        run([DEAD], base(), foreground=foreground)
    assert not bring.called


def test_sprint_shift_goes_down_after_walking_starts():
    """Shift pressed with or before W only walks; it has to come after W is down."""
    presses = []
    bot = gc_bot.Bot(base(), on_status=lambda t: None, on_stop=lambda r: None)
    with patch.object(gc_bot.pydirectinput, "keyDown", side_effect=lambda k: presses.append(("down", k))), \
         patch.object(gc_bot.pydirectinput, "keyUp", side_effect=lambda k: presses.append(("up", k))), \
         patch.object(gc_bot.time, "sleep"):
        bot._hold(("w", "a", gc_bot.CHARGE_KEY))
        assert presses[-1] == ("down", gc_bot.CHARGE_KEY) and len(presses) == 3
        presses.clear()
        bot._hold(("w", "d", gc_bot.CHARGE_KEY))  # strafe switch: still walking, Shift stays down
        assert ("up", gc_bot.CHARGE_KEY) not in presses
        bot._hold(())
        presses.clear()
        bot._hold((gc_bot.CHARGE_KEY,))
        bot._hold(("w", gc_bot.CHARGE_KEY))  # Shift already down before walking: pressed again after W
        assert presses[-3:] == [("down", "w"), ("up", gc_bot.CHARGE_KEY), ("down", gc_bot.CHARGE_KEY)]
