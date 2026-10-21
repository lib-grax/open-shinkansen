"""Per-user joystick profile selection. No emulator files or system settings are edited."""

import json
import os
import tempfile
from pathlib import Path

JOYSTICK_PROFILES = ("generic", "pcsx2-shinkansen")
DEFAULT_PROFILE = "generic"


def validate_profile(name):
    if not isinstance(name, str) or name not in JOYSTICK_PROFILES:
        raise ValueError(
            f"Unknown joystick profile {name!r}; choose {', '.join(JOYSTICK_PROFILES)}"
        )
    return name


def settings_path():
    base = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    if not base.is_absolute():
        raise ValueError("XDG_CONFIG_HOME must be an absolute path")
    return base / "open-shinkansen" / "settings.json"


def load_profile():
    path = settings_path()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        if path.is_symlink():
            raise ValueError(f"Broken linked settings: {path}")
        return DEFAULT_PROFILE
    except ValueError as exc:
        raise ValueError(f"Invalid settings in {path}: {exc}") from exc
    if not isinstance(data, dict) or data.keys() - {"joystick_profile"}:
        raise ValueError(f"Unrecognized settings in {path}; refusing to ignore or overwrite them")
    return validate_profile(data.get("joystick_profile", DEFAULT_PROFILE))


def save_profile(name):
    validate_profile(name)
    path = settings_path()
    if path.is_symlink():
        raise ValueError(f"Refusing to overwrite symlinked settings: {path}")
    if path.exists():
        load_profile()  # Never discard unfamiliar or malformed existing user work.
        if path.stat().st_uid != os.getuid() or not os.access(path, os.W_OK):
            raise PermissionError(f"Settings are not writable/owned by this user: {path}")
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent, prefix=".settings-", delete=False
        ) as output:
            temporary = Path(output.name)
            json.dump({"joystick_profile": name}, output, indent=2)
            output.write("\n")
            output.flush()
            os.fsync(output.fileno())
        temporary.replace(path)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()  # Only the exact temporary file created by this call.
    return path
