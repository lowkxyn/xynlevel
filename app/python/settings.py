"""Validated, atomic per-user preferences. Never read the legacy core settings file."""
import json
import math
import os
from pathlib import Path

DEFAULTS = {
    "attack": "auto", "ult_slot": 7, "blast_interval": 0.4,
    "scroll_interval": 1.0, "stop_enabled": False, "stop_at_seconds": 60,
    "movement": "circle", "relock": True, "hide_chat": True, "auto_gravity": True, "gravity": 100, "sprint": True, "blast_jump": True, "ult_jump": False, "auto_buy": False, "replace_slot": False,
    "restore_slot": True, "ceiling_aim": True, "ki_control_spend": False, "ki_control_target": 300,
    "theme": "dark", "accent": "#b4bbc8", "reduced_motion": False,
    "notifications": True, "sound": False, "after_run": "none",
    "always_on_top": False, "nav_style": "keycap", "dial_sounds": False,
}
CORE_KEYS = ("attack", "ult_slot", "blast_interval", "scroll_interval", "stop_enabled", "stop_at_seconds",
             "movement", "relock", "hide_chat", "auto_gravity", "gravity", "sprint", "blast_jump", "ult_jump", "auto_buy", "replace_slot", "restore_slot", "ceiling_aim", "ki_control_spend", "ki_control_target")


def validate(raw):
    if not isinstance(raw, dict) or set(raw) - DEFAULTS.keys():
        raise ValueError("Settings must be an object containing supported fields only")
    result = {**DEFAULTS, **raw}
    if result["nav_style"] not in ("keycap", "dial"):
        result["nav_style"] = DEFAULTS["nav_style"]
    if type(result["dial_sounds"]) is not bool:
        result["dial_sounds"] = DEFAULTS["dial_sounds"]
    for key, choices in {
        "attack": ("auto", "blasts", "ult"), "ult_slot": (7, 8),
        "movement": ("off", "w", "wa", "wd", "circle"),
        "theme": ("dark", "aero", "light", "system"),
        "after_run": ("none", "close_app", "shutdown"),
    }.items():
        if result[key] not in choices or (key == "ult_slot" and type(result[key]) is not int):
            raise ValueError(f"Invalid {key}")
    for key in ("stop_enabled", "relock", "hide_chat", "auto_gravity", "sprint", "blast_jump", "ult_jump", "auto_buy", "replace_slot", "restore_slot", "ceiling_aim", "ki_control_spend", "reduced_motion", "notifications", "sound", "always_on_top"):
        if type(result[key]) is not bool:
            raise ValueError(f"{key} must be true or false")
    for key in ("blast_interval", "scroll_interval"):
        value = result[key]
        if type(value) not in (int, float) or not math.isfinite(value) or not 0.05 <= value <= 60:
            raise ValueError(f"{key} must be between 0.05 and 60 seconds")
    if type(result["gravity"]) is not int or result["gravity"] not in range(0, 101, 10):
        raise ValueError("Gravity must be 0, 10, 20 ... 100")
    if type(result["ki_control_target"]) is not int:
        raise ValueError("Ki Control target must be a whole number")
    result["ki_control_target"] = max(1, min(5000, result["ki_control_target"]))
    value = result["stop_at_seconds"]
    if type(value) is not int or not 0 <= value <= 604800:
        raise ValueError("Stop time must be a whole number from 0 to 604800")
    accent = result["accent"]
    if not isinstance(accent, str) or len(accent) != 7 or accent[0] != "#" or any(c not in "0123456789abcdefABCDEF" for c in accent[1:]):
        raise ValueError("Choose a six-digit accent colour")
    return result


class SettingsStore:
    def __init__(self, directory):
        self.path = Path(directory) / "settings.json"
        self.warning = None
        self.blocked = False
        self.value = dict(DEFAULTS)
        if self.path.exists():
            try:
                self.value = validate(json.loads(self.path.read_text(encoding="utf-8")))
            except (OSError, ValueError, UnicodeError):
                self.blocked = True
                self.warning = "Settings are unreadable. Defaults are shown; restore defaults to preserve a backup and continue."

    def save(self, raw):
        if self.blocked:
            raise ValueError("Restore defaults first; the unreadable settings file has been preserved")
        value = validate(raw)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        with temporary.open("w", encoding="utf-8") as output:
            json.dump(value, output, indent=2, allow_nan=False)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, self.path)
        self.value = value
        return value

    def reset(self):
        if self.path.exists():
            suffix = 1
            while self.path.with_name(f"settings.backup-{suffix}.json").exists():
                suffix += 1
            self.path.rename(self.path.with_name(f"settings.backup-{suffix}.json"))
        self.blocked = False
        self.warning = None
        return self.save(dict(DEFAULTS))
