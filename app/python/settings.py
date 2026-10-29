"""Validated, atomic per-user preferences. Never read the legacy core settings file."""
import json
import os
from pathlib import Path

DEFAULTS = {
    "gravity_mode": "max", "gravity": 500, "auto_senzu": True, "senzu_at": 35,
    "stop_after_minutes": 0, "stop_at_level": 0,
    "theme": "dark", "accent": "#b4bbc8", "reduced_motion": False,
    "notifications": True, "sound": False, "after_run": "none",
    "always_on_top": False, "nav_style": "keycap", "dial_sounds": False,
}
CORE_KEYS = ("gravity_mode", "gravity", "auto_senzu", "senzu_at", "stop_after_minutes", "stop_at_level")


def validate(raw):
    if not isinstance(raw, dict) or set(raw) - DEFAULTS.keys():
        raise ValueError("Settings must be an object containing supported fields only")
    result = {**DEFAULTS, **raw}
    for key, choices in {
        "gravity_mode": ("max", "custom"), "nav_style": ("keycap", "dial"),
        "theme": ("dark", "aero", "light", "system"),
        "after_run": ("none", "close_app", "shutdown"),
    }.items():
        if result[key] not in choices:
            raise ValueError(f"Invalid {key}")
    for key in ("auto_senzu", "dial_sounds", "reduced_motion", "notifications", "sound", "always_on_top"):
        if type(result[key]) is not bool:
            raise ValueError(f"{key} must be true or false")
    for key, minimum, maximum in (("gravity", 1, 500), ("senzu_at", 10, 90),
                                  ("stop_after_minutes", 0, 10080), ("stop_at_level", 0, 100000)):
        value = result[key]
        if type(value) is not int or not minimum <= value <= maximum:
            raise ValueError(f"{key} must be a whole number from {minimum} to {maximum}")
    accent = result["accent"]
    if not isinstance(accent, str) or len(accent) != 7 or accent[0] != "#" or any(c not in "0123456789abcdefABCDEF" for c in accent[1:]):
        raise ValueError("Choose a six-digit accent colour")
    return result


def load_settings(raw):
    if not isinstance(raw, dict):
        raise ValueError("Settings must be an object")
    supported = {key: value for key, value in raw.items() if key in DEFAULTS}
    # The bot-room gravity scale doesn't carry over to training.
    if "gravity_mode" not in raw and "auto_gravity" in raw:
        supported.pop("gravity", None)
    if supported.get("nav_style", DEFAULTS["nav_style"]) not in ("keycap", "dial"):
        supported["nav_style"] = DEFAULTS["nav_style"]
    if type(supported.get("dial_sounds", DEFAULTS["dial_sounds"])) is not bool:
        supported["dial_sounds"] = DEFAULTS["dial_sounds"]
    return validate(supported)


class SettingsStore:
    def __init__(self, directory):
        self.path = Path(directory) / "settings.json"
        self.warning = None
        self.blocked = False
        self.value = dict(DEFAULTS)
        if self.path.exists():
            try:
                self.value = load_settings(json.loads(self.path.read_text(encoding="utf-8")))
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
