"""Joystick-only hotplug worker for an unprivileged systemd user service.

No keyboard profiles, display commands, game process launching or root privileges.
USB absence/timeouts are normal; uinput/configuration/programming failures are not
hidden in an endless retry loop. Each attachment gets fresh decoding state.
"""

import logging
import math
import os
import stat
from contextlib import ExitStack
from pathlib import Path

from .events import JoystickMapper
from .protocol import decode

LOG = logging.getLogger(__name__)


class AlreadyRunning(RuntimeError):
    pass


class InstanceLock:
    """Per-user flock; never unlink a lock file that another process could open."""

    def __init__(self, directory=None):
        runtime = os.environ.get("XDG_RUNTIME_DIR")
        base = Path(runtime) if runtime else Path.home() / ".cache"
        self.directory = Path(directory) if directory else base / "open-shinkansen"
        self.fd = None

    def __enter__(self):
        import fcntl

        self.directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        info = self.directory.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise RuntimeError(
                f"Lock directory must be owned by you with mode 0700: {self.directory}"
            )
        fd = os.open(self.directory / "daemon.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_nlink != 1:
                raise RuntimeError("Refusing an unsafe daemon lock file")
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise AlreadyRunning(
                    "The open-shinkansen daemon is already running for this user"
                ) from exc
            os.ftruncate(fd, 0)
            os.write(fd, str(os.getpid()).encode("ascii"))
            self.fd = fd
            return self
        except BaseException:
            os.close(fd)
            raise

    def __exit__(self, *args):
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None


def serve_connection(controller, stop, output_factory, logger=LOG):
    """Wait for valid state, create the joystick, and guarantee output cleanup."""
    state = None
    output = None
    mapper = JoystickMapper()
    with ExitStack() as resources:
        while not stop.is_set():
            raw = controller.read(100)
            if stop.is_set():
                break
            if raw is None:
                continue  # This controller need not send heartbeat reports.
            state = decode(raw, state)
            if not state.ready:
                continue
            if output is None:
                # Do not advertise fabricated neutral state from an unknown startup packet.
                output = output_factory()
                resources.callback(logger.info, "Virtual joystick session ended; device closed")
                resources.callback(output.close)
                resources.callback(lambda: output.emit(mapper.close()))
                logger.info("Virtual joystick ready; controller inputs active")
            output.emit(mapper.update(state))


def run(stop, poll_interval=1.0, controller_factory=None, output_factory=None, logger=LOG):
    import usb.core

    from .output import UInputOutput
    from .usb import Controller, DeviceNotFound

    if not math.isfinite(poll_interval) or not 0.1 <= poll_interval <= 60:
        raise ValueError("Hotplug poll interval must be between 0.1 and 60 seconds")
    controller_factory = controller_factory or Controller
    output_factory = output_factory or (lambda: UInputOutput("joystick"))
    last_notice = None
    logger.info("Waiting for TCPP-20011 (0ae4:0005); automatic joystick hotplug enabled")
    try:
        while not stop.is_set():
            try:
                with controller_factory() as controller:
                    logger.info("USB controller connected; waiting for valid handle readings")
                    serve_connection(controller, stop, output_factory, logger)
            except DeviceNotFound:
                if last_notice != "absent":
                    logger.info("Controller absent; waiting for it to be plugged in")
                last_notice = "absent"
            except usb.core.USBError as exc:
                # Includes unplug, enumeration/udev ACL races, and a device temporarily
                # claimed elsewhere. Never retry an evdev/uinput OSError here.
                notice = (exc.errno, exc.backend_error_code, str(exc))
                if notice != last_notice:
                    logger.warning("USB unavailable (%s); output released, retrying", exc)
                last_notice = notice
            if not stop.is_set():
                stop.wait(poll_interval)
    finally:
        logger.info("Hotplug worker stopped")
