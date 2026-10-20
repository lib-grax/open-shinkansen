"""One-command source-checkout setup, bootstrapped using only the standard library.

Executed by setup.sh, then re-executed by the project's venv after creating it.
Never installs system packages, runs pip as root, or reboots the host.
"""

import argparse
import grp
import importlib
import json
import os
import platform
import pwd
import shlex
import shutil
import subprocess
import sys
import time
import venv
from datetime import datetime, timezone
from importlib import metadata
from pathlib import Path

UNIT = "open-shinkansen.service"
GROUP = "open-shinkansen"
ASSETS = (
    ("70-open-shinkansen.rules", "/etc/udev/rules.d"),
    ("70-open-shinkansen-uinput.rules", "/etc/udev/rules.d"),
    ("open-shinkansen.conf", "/etc/modules-load.d"),
)
UINPUT = Path("/dev/uinput")


def binary_evdev(system=None, machine=None, implementation=None, version=None):
    """The verified upstream wheel range; mirror the pyproject environment markers."""
    return (
        (system if system is not None else sys.platform) == "linux"
        and (machine if machine is not None else platform.machine()) == "x86_64"
        and (implementation if implementation is not None else sys.implementation.name) == "cpython"
        and (version if version is not None else sys.version_info[:2]) < (3, 15)
    )


def run(command, **kwargs):
    return subprocess.run([str(arg) for arg in command], check=True, **kwargs)


def permissions_configured(project, user):
    """Allow safe reruns without another admin prompt when host setup already matches."""
    try:
        group = grp.getgrnam(GROUP)
        if user.pw_name not in group.gr_mem and user.pw_gid != group.gr_gid:
            return False
        for name, directory in ASSETS:
            target = Path(directory) / name
            if (
                target.is_symlink()
                or target.read_bytes() != (project / "linux" / name).read_bytes()
            ):
                return False
        if not UINPUT.is_char_device():
            return False
        if group.gr_gid in {*os.getgroups(), os.getegid()} and not os.access(
            UINPUT, os.R_OK | os.W_OK
        ):
            return False
    except (KeyError, OSError):
        return False
    return True


def administrator_command():
    for name in ("sudo", "doas"):
        command = shutil.which(name)
        if command:
            return command
    raise RuntimeError(
        "Device permissions need administrator access. Install/configure sudo or doas, "
        "or ask an administrator to follow docs/linux-setup.md, then rerun ./setup.sh."
    )


def preflight(project, user):
    if sys.platform != "linux":
        return
    if shutil.which("systemctl") is None:
        raise RuntimeError("Automatic Linux setup requires systemd user services (systemctl).")
    result = subprocess.run(
        ["systemctl", "--user", "show-environment"], capture_output=True, timeout=10, check=False
    )
    if result.returncode:
        raise RuntimeError(
            "Cannot connect to your systemd user session. Run ./setup.sh in your normal "
            "logged-in terminal, not with sudo or from a root shell."
        )
    run(["bash", project / "linux/setup-permissions.sh", "--check", user.pw_name])
    if not permissions_configured(project, user):
        administrator_command()


def usable_venv(directory):
    if not (directory / "bin/python").is_file():
        return False
    probe = (
        "import json,sys,pip; print(json.dumps([sys.prefix,sys.base_prefix,sys.platform,"
        "list(sys.version_info[:2])]))"
    )
    try:
        result = subprocess.run(
            [str(directory / "bin/python"), "-c", probe],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        prefix, base, system, version = (
            json.loads(result.stdout) if result.returncode == 0 else (None,) * 4
        )
        return (
            prefix is not None
            and Path(prefix).resolve() == directory.resolve()
            and prefix != base
            and system == sys.platform
            and tuple(version) >= (3, 9)
        )
    except (OSError, ValueError, TypeError, subprocess.TimeoutExpired):
        return False


def bootstrap(project, args, user):
    print("[1/4] Checking this computer...", flush=True)
    preflight(project, user)
    directory = project / ".venv"
    if directory.is_symlink() or (directory.exists() and not directory.is_dir()):
        raise RuntimeError(
            "The project's .venv must be an ordinary directory, not a file or symlink."
        )
    if directory.exists() and directory.stat().st_uid != os.getuid():
        raise RuntimeError(
            "The existing .venv belongs to another user. Do not rerun setup as root."
        )
    print("[2/4] Preparing the private Python environment...", flush=True)
    if not usable_venv(directory):
        if directory.exists():
            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
            backup = project / (".venv-backup-" + stamp)
            if backup.exists():
                raise RuntimeError(
                    "Virtual-environment backup already exists; refusing to overwrite it."
                )
            directory.rename(backup)
            print(f"Preserved the unusable/copied environment in {backup.name}", flush=True)
        try:
            venv.EnvBuilder(with_pip=True).create(directory)
        except (OSError, subprocess.CalledProcessError) as exc:
            raise RuntimeError(
                "Could not create a Python environment with pip. Your host needs Python's "
                "venv/ensurepip support; see docs/linux-setup.md. No environment was deleted."
            ) from exc
    command = [directory / "bin/python", Path(__file__).resolve(), "--_venv"]
    if args.dev:
        command.append("--dev")
    if args.replace_service:
        command.append("--replace-service")
    try:
        run(command)
    except subprocess.CalledProcessError as exc:
        # The venv phase already printed the actual error; don't bury it under
        # another outer traceback/command summary.
        return exc.returncode
    return 0


def prepare_evdev():
    """Migrate only a conflicting provider in the already-validated project venv."""
    if sys.platform != "linux":
        return
    wrong = "evdev" if binary_evdev() else "evdev-binary"
    try:
        metadata.distribution(wrong)
    except metadata.PackageNotFoundError:
        return
    # Both distributions own the same evdev module files. Remove both so pip
    # reinstalls exactly one complete provider rather than leaving overlapping files.
    print("Updating the input backend inside this project's venv...", flush=True)
    run([sys.executable, "-m", "pip", "uninstall", "--yes", "evdev", "evdev-binary"])


def finish(project, args, user):
    directory = project / ".venv"
    if Path(sys.prefix).resolve() != directory.resolve() or sys.prefix == sys.base_prefix:
        raise RuntimeError(
            "Refusing to install dependencies outside this project's virtual environment."
        )
    run([sys.executable, "-m", "pip", "install", "--upgrade", "pip"])
    prepare_evdev()
    package = str(project) + ("[dev]" if args.dev else "")
    run([sys.executable, "-m", "pip", "install", "--only-binary=evdev-binary", "-e", package])
    importlib.invalidate_caches()
    # Editable .pth files are newly installed; this process started before pip ran.
    sys.path.insert(0, str(project / "src"))
    if sys.platform == "darwin":
        print(
            "\nSetup complete. macOS USB/debug tools are installed; no Linux service was created."
        )
        print("Run: " + shlex.quote(str(directory / "bin/open-shinkansen")) + " debug")
        return
    # Verify the native wheel actually imports, not just that module metadata exists.
    from evdev import AbsInfo, UInput, ecodes

    from open_shinkansen import doctor, service

    if not all((AbsInfo, UInput, ecodes.EV_KEY, ecodes.BTN_JOYSTICK)):
        raise RuntimeError("The Linux input backend did not load correctly.")
    print("[3/4] Configuring controller access...", flush=True)
    if not permissions_configured(project, user):
        print("Administrator access is needed for USB/uinput permissions only.", flush=True)
        print("The open-shinkansen group can inject input; add only trusted users.", flush=True)
        run([administrator_command(), "bash", project / "linux/setup-permissions.sh", user.pw_name])
    report = doctor.inspect()
    failed = {item["name"] for item in report["checks"] if not item["ok"]}
    pending = not doctor.group_active()
    allowed = {"permission_group", "uinput_access"} if pending else set()
    if failed - allowed or not doctor.UINPUT.is_char_device():
        for item in report["checks"]:
            if not item["ok"]:
                print("Check: " + item["detail"], file=sys.stderr)
        raise RuntimeError(
            "Host setup checks failed. Fix the reported prerequisite and rerun ./setup.sh."
        )
    print("[4/4] Enabling the background service...", flush=True)
    service.install(replace=args.replace_service, start=False)
    if pending:
        service.manage("stop")
        print("\nSETUP COMPLETE - REBOOT REQUIRED")
        print("The service is enabled and will start at your next login after reboot.")
        print("You do not need to run setup again. Then plug in the controller.")
    else:
        run(["systemctl", "--user", "reset-failed", UNIT])
        service.manage("restart")
        time.sleep(0.5)
        run(["systemctl", "--user", "is-active", "--quiet", UNIT])
        print("\nSETUP COMPLETE - the background service is enabled and running.")
        print("Plug in the controller. No terminal needs to stay open.")
    print("Keep this project folder in place. Games/companion apps still need their own bindings.")


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="One-time open-shinkansen setup; run ./setup.sh without sudo"
    )
    parser.add_argument("--dev", action="store_true", help="Also install test/lint dependencies")
    parser.add_argument(
        "--replace-service",
        action="store_true",
        help="Back up and replace a differing user service",
    )
    parser.add_argument("--_venv", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    try:
        if sys.version_info < (3, 9):
            raise RuntimeError("Python 3.9 or newer is required.")
        if sys.platform not in ("linux", "darwin"):
            raise RuntimeError("This setup supports Linux and macOS only.")
        if os.getuid() == 0 or os.geteuid() == 0:
            raise RuntimeError(
                "Do not run ./setup.sh with sudo. It requests admin access only when needed."
            )
        project = Path(__file__).resolve().parents[2]
        if (
            not (project / "pyproject.toml").is_file()
            or not (project / "linux/setup-permissions.sh").is_file()
        ):
            raise RuntimeError(
                "Run setup.sh from a complete project checkout, not an installed wheel."
            )
        user = pwd.getpwuid(os.getuid())
        if args._venv:
            finish(project, args, user)
        else:
            return bootstrap(project, args, user)
        return 0
    except KeyboardInterrupt:
        print("\nSetup cancelled. No reboot was requested.", file=sys.stderr)
        return 130
    except (RuntimeError, OSError, ImportError, subprocess.SubprocessError) as exc:
        print("\nSetup could not finish: " + str(exc), file=sys.stderr)
        print(
            "Correct the reported issue and rerun ./setup.sh; existing data is preserved.",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
