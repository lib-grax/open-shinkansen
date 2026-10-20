"""Install/manage only the current user's systemd unit; never invoke sudo."""

import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

UNIT_NAME = "open-shinkansen.service"
MARKER = "# Managed by open-shinkansen service install\n"


def _quote(value):
    # systemd ExecStart is not a shell. Escape its own specifiers/variable syntax.
    value = str(value)
    if any(ord(char) < 32 for char in value):
        raise ValueError("Service paths cannot contain control characters")
    return (
        '"'
        + value.replace("\\", "\\\\").replace('"', '\\"').replace("%", "%%").replace("$", "$$")
        + '"'
    )


def render_unit(python):
    python = Path(python)
    if not python.is_absolute():
        raise ValueError("Service interpreter must be an absolute path")
    return (
        MARKER
        + f"""[Unit]
Description=open-shinkansen USB controller hotplug bridge
StartLimitIntervalSec=120
StartLimitBurst=5

[Service]
Type=simple
ExecStart={_quote(python)} -m open_shinkansen daemon
Environment=PYTHONUNBUFFERED=1
Restart=on-failure
RestartSec=10
TimeoutStopSec=5
KillSignal=SIGTERM
UMask=0077
NoNewPrivileges=yes
RestrictSUIDSGID=yes

[Install]
WantedBy=default.target
"""
    )


def unit_path():
    base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    if not base.is_absolute():
        raise ValueError("XDG_CONFIG_HOME must be an absolute path")
    return base / "systemd" / "user" / UNIT_NAME


def _systemctl(*args):
    subprocess.run(["systemctl", "--user", *args], check=True)


def install(replace=False, start=True):
    path = unit_path()
    # Do not resolve symlinks: .venv/bin/python must NOT become system Python.
    content = render_unit(Path(sys.executable).absolute())
    if path.is_symlink():
        raise RuntimeError(f"Refusing to replace a symlink: {path}")
    if path.exists():
        old = path.read_text(encoding="utf-8")
        if old != content:
            if not replace:
                raise RuntimeError(
                    f"Unit differs; refusing to overwrite {path}. Review it, then use --replace."
                )
            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
            backup = path.with_name(path.name + f".backup-{stamp}")
            with backup.open("x", encoding="utf-8") as handle:
                handle.write(old)
            print(f"Existing unit backed up to {backup}")
            path.write_text(content, encoding="utf-8")
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("x", encoding="utf-8") as handle:
            handle.write(content)
    _systemctl("daemon-reload")
    _systemctl(*(("enable", "--now", UNIT_NAME) if start else ("enable", UNIT_NAME)))
    print(f"Enabled {UNIT_NAME} for this user's login sessions.")
    print("The service does not install device permissions. See docs/background-service.md.")


def uninstall():
    path = unit_path()
    if path.is_symlink():
        raise RuntimeError(f"Refusing to remove a symlink: {path}")
    if not path.exists():
        print("No project-managed user unit is installed.")
        return
    if not path.read_text(encoding="utf-8").startswith(MARKER):
        raise RuntimeError(f"Refusing to remove an unfamiliar unit: {path}")
    _systemctl("disable", "--now", UNIT_NAME)
    path.unlink()
    _systemctl("daemon-reload")
    print(
        "Removed the user service. Project files, captures and host permission rules are unchanged."
    )


def manage(action, replace=False, start=True):
    if sys.platform != "linux":
        raise RuntimeError("Service management requires Linux and a systemd user session")
    if os.geteuid() == 0:
        raise RuntimeError("Run service management as your normal user, NOT sudo/root")
    if action == "install":
        install(replace=replace, start=start)
    elif action == "uninstall":
        uninstall()
    elif action in ("start", "stop", "restart", "status"):
        _systemctl(action, UNIT_NAME)
    elif action == "logs":
        subprocess.run(
            ["journalctl", "--user", "-u", UNIT_NAME, "-n", "80", "--no-pager"], check=True
        )
