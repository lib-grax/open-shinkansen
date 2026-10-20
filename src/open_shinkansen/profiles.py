"""Strict JSON configuration, validated before USB or virtual-device access."""

import json
from pathlib import Path

CONTROLS = {
    "a",
    "b",
    "c",
    "d",
    "select",
    "start",
    "pedal",
    "emergency",
    "up",
    "down",
    "left",
    "right",
}
SPECIAL_KEYS = {
    "SPACE",
    "ENTER",
    "ESC",
    "TAB",
    "BACKSPACE",
    "UP",
    "DOWN",
    "LEFT",
    "RIGHT",
    "LEFTSHIFT",
    "RIGHTSHIFT",
    "LEFTCTRL",
    "RIGHTCTRL",
    "LEFTALT",
    "RIGHTALT",
    "COMMA",
    "DOT",
    "SLASH",
    "SEMICOLON",
    "APOSTROPHE",
    "MINUS",
    "EQUAL",
    "LEFTBRACE",
    "RIGHTBRACE",
    "BACKSLASH",
    "GRAVE",
    "HOME",
    "END",
    "PAGEUP",
    "PAGEDOWN",
    "INSERT",
    "DELETE",
    "PAUSE",
    "CAPSLOCK",
    "NUMLOCK",
}
KEY_NAMES = {"KEY_" + name for name in SPECIAL_KEYS}
KEY_NAMES |= {"KEY_" + char for char in "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"}
KEY_NAMES |= {f"KEY_F{i}" for i in range(1, 13)}


def _key(value):
    if not isinstance(value, str) or value not in KEY_NAMES:
        raise ValueError(f"Unsupported key {value!r}; use Linux KEY_* names (e.g. KEY_A)")
    return value


def _fields(value, allowed, label):
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    extra = value.keys() - allowed
    if extra:
        raise ValueError(f"Unknown {label} fields: {', '.join(sorted(extra))}")


def validate(profile: dict) -> dict:
    _fields(
        profile,
        {"name", "description", "pulse_ms", "gap_ms", "buttons", "power", "brake"},
        "profile",
    )
    result = dict(profile)
    for name, default in (("pulse_ms", 80), ("gap_ms", 60)):
        value = profile.get(name, default)
        if type(value) is not int or not 10 <= value <= 2000:
            raise ValueError(f"{name} must be an integer between 10 and 2000")
        result[name] = value
    buttons = profile.get("buttons", {})
    _fields(buttons, CONTROLS, "buttons")
    result["buttons"] = {control: _key(key) for control, key in buttons.items()}
    for axis, count in (("power", 14), ("brake", 9)):
        config = profile.get(axis, {"mode": "disabled"})
        if not isinstance(config, dict):
            raise ValueError(f"{axis} must be an object")
        mode = config.get("mode")
        if mode == "disabled":
            _fields(config, {"mode"}, axis)
        elif mode == "absolute":
            _fields(config, {"mode", "keys"}, axis)
            keys = config.get("keys")
            if not isinstance(keys, list) or len(keys) != count:
                raise ValueError(f"{axis}.keys requires {count} entries (null means unbound)")
            for key in keys:
                if key is not None:
                    _key(key)
        elif mode == "relative":
            _fields(config, {"mode", "steps", "increase", "decrease"}, axis)
            if type(config.get("steps")) is not int or not 1 <= config["steps"] <= 64:
                raise ValueError(f"{axis}.steps must be between 1 and 64")
            if _key(config.get("increase")) == _key(config.get("decrease")):
                raise ValueError(f"{axis} increase and decrease must differ")
        else:
            raise ValueError(f"{axis}.mode must be absolute, relative or disabled")
        result[axis] = dict(config)
    return result


def load(path) -> dict:
    return validate(json.loads(Path(path).read_text(encoding="utf-8")))
