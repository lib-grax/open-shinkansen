"""Read-only capability checks; no distribution detection or package-manager commands."""

import importlib.util
import os
import shutil
import subprocess
import sys
from pathlib import Path

GROUP = "open-shinkansen"
RULES = ("70-open-shinkansen.rules", "70-open-shinkansen-uinput.rules")
RULES_DIRECTORY = Path("/etc/udev/rules.d")
UINPUT = Path("/dev/uinput")


def group_active():
    import grp

    try:
        gid = grp.getgrnam(GROUP).gr_gid
    except KeyError:
        return False
    return gid in {*os.getgroups(), os.getegid()}


def inspect():
    checks = []

    def add(name, ok, detail):
        checks.append({"name": name, "ok": bool(ok), "detail": detail})

    add("linux", sys.platform == "linux", "Linux is required for systemd/uinput output")
    add("python", sys.version_info >= (3, 9), "Python 3.9+; use a dedicated virtual environment")
    add("normal_user", os.geteuid() != 0, "Run the worker and service management without sudo/root")
    for name in ("usb", "evdev"):
        add(name, importlib.util.find_spec(name) is not None, f"Python module: {name}")
    try:
        from .usb import backend

        backend()
    except Exception as exc:
        add("libusb_backend", False, f"libusb cannot load: {exc}")
    else:
        add("libusb_backend", True, "libusb loads; no controller was claimed")
    add("udevadm", shutil.which("udevadm") is not None, "udev manages device permissions")
    if shutil.which("systemctl") is None:
        add("systemd_user", False, "systemctl is missing; a systemd user manager is required")
    else:
        try:
            result = subprocess.run(
                ["systemctl", "--user", "show-environment"],
                capture_output=True,
                timeout=5,
                check=False,
            )
            add(
                "systemd_user",
                result.returncode == 0,
                "User-manager connection; run from the intended user's login session",
            )
        except (OSError, subprocess.TimeoutExpired):
            add("systemd_user", False, "Cannot reach the systemd user manager")
    add(
        "uinput_access",
        UINPUT.is_char_device() and os.access(UINPUT, os.R_OK | os.W_OK),
        "Character device /dev/uinput must be readable/writable by this user",
    )
    add(
        "permission_group",
        group_active(),
        "Current session must include open-shinkansen; fully log out/in after setup",
    )
    add(
        "permission_rules",
        all((RULES_DIRECTORY / name).is_file() for name in RULES),
        "Project udev rules installed; reconnect USB after installing/reloading them",
    )
    return {"ready": all(check["ok"] for check in checks), "checks": checks}
