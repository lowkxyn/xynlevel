import numpy as np

import gc_train


def test_card_states():
    assert gc_train.parse_card("GRAVITY TRAINING Press TAB to open training.") == "idle"
    assert gc_train.parse_card("GRAVITY TRAINING Press TAB to stop training.") == "training"
    assert gc_train.parse_card("GRAVITY TRAINING Respawn to open training.") == "dead"
    assert gc_train.parse_card("") is None
    assert gc_train.parse_card("TRAINING Training helps players improve") is None


def test_stats_line_reads_hidden_decimal_point():
    # Real OCR outputs from the panel at 1G, 380G and 500G.
    assert gc_train.parse_stats_line("Resist1000/0 • Drain o HP/s • EXPx1.o") == (1000, 0, 1.0)
    assert gc_train.parse_stats_line("Resist99% • Drain 15 HP/s • EXP x107") == (99, 15, 1.07)
    assert gc_train.parse_stats_line("Resist65% • Drain 519 HPIs • EXPx21213") == (65, 519, 212.13)
    assert gc_train.parse_stats_line("garbage") == (None, None, None)


def test_max_gravity_and_points():
    assert gc_train.parse_max_gravity("Max 500G") == 500
    assert gc_train.parse_max_gravity("Max15G") == 15
    assert gc_train.parse_max_gravity("Apply") is None
    assert gc_train.parse_points_left("Points Left: 9/260") == 9
    assert gc_train.parse_points_left("Points Left: o/260") == 0
    assert gc_train.parse_points_left("Points Left:") is None


def test_senzu_row():
    assert gc_train.parse_senzu_row("Senzu Bean x489") == 489
    assert gc_train.parse_senzu_row("Senzu Bean x1,204") == 1204
    assert gc_train.parse_senzu_row("Senzu Bean") == 0
    assert gc_train.parse_senzu_row("Potara x147") is None
    assert gc_train.parse_senzu_row("") is None


def bar(gold=(180, 280), marker=None):
    row = np.zeros((460, 3), np.uint8)
    row[gold[0]:gold[1]] = (60, 180, 220)  # BGR gold
    if marker is not None:
        row[marker:marker + 4] = (255, 255, 255)
    return row


def test_marker_in_gold():
    assert gc_train.marker_in_gold(bar(marker=220))
    assert not gc_train.marker_in_gold(bar(marker=40))
    assert not gc_train.marker_in_gold(bar(marker=None))
    assert not gc_train.marker_in_gold(bar(gold=(0, 0), marker=220))  # no gold zone: the FAILED screen


def test_gravity_target():
    assert gc_train.gravity_target({"gravity_mode": "max"}, 500) == 500
    assert gc_train.gravity_target({"gravity_mode": "custom", "gravity": 450}, 500) == 450
    assert gc_train.gravity_target({"gravity_mode": "custom", "gravity": 450}, 15) == 15
    assert gc_train.gravity_target({"gravity_mode": "custom", "gravity": 300}, None) == 300
    assert gc_train.gravity_target({"gravity_mode": "max"}, None) is None


def test_gravity_tint():
    frame = np.zeros((1080, 1920, 3), np.uint8)
    frame[:] = (40, 40, 220)  # BGR deep red: inside the field at high gravity
    assert gc_train.gravity_tint(frame) > gc_train.TINTED
    frame[:] = (230, 230, 230)  # white walls by the LEAVE door
    assert gc_train.gravity_tint(frame) < gc_train.TINTED
