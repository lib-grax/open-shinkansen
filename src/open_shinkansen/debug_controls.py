"""Explicit manual display tests and terminal keyboard handling; never game input."""

import os
import select
import sys
import warnings
from dataclasses import dataclass
from typing import Optional

from .protocol import Display
from .usb import DeviceError

SEQUENCES = {
    b"\x1b[A": "UP",
    b"\x1b[B": "DOWN",
    b"\x1b[C": "RIGHT",
    b"\x1b[D": "LEFT",
    b"\x1bOA": "UP",
    b"\x1bOB": "DOWN",
    b"\x1bOC": "RIGHT",
    b"\x1bOD": "LEFT",
    b"\x1b[Z": "BACKTAB",
}
SINGLE_KEYS = {9: "TAB", 32: "TOGGLE", 10: "TOGGLE", 13: "TOGGLE", 113: "QUIT", 81: "QUIT"}


def require_terminal(stdin=None, stdout=None):
    stdin = sys.stdin if stdin is None else stdin
    stdout = sys.stdout if stdout is None else stdout
    if (
        os.name != "posix"
        or stdin is None
        or stdout is None
        or not stdin.isatty()
        or not stdout.isatty()
        or os.environ.get("TERM") == "dumb"
    ):
        raise ValueError("debug --outputs needs an interactive terminal for keyboard controls")


class KeyDecoder:
    """Accept split ANSI/SS3 arrow sequences; ignore unknown keys and terminal escapes."""

    def __init__(self):
        self.buffer = b""

    def feed(self, data):
        self.buffer += data
        keys = []
        while self.buffer:
            matched = next((seq for seq in SEQUENCES if self.buffer.startswith(seq)), None)
            if matched is not None:
                keys.append(SEQUENCES[matched])
                self.buffer = self.buffer[len(matched) :]
            elif self.buffer[0] == 27:
                if any(seq.startswith(self.buffer) for seq in SEQUENCES):
                    break
                if self.buffer.startswith(b"\x1b["):
                    end = next(
                        (i for i in range(2, len(self.buffer)) if 0x40 <= self.buffer[i] <= 0x7E),
                        None,
                    )
                    if end is None:
                        break
                    self.buffer = self.buffer[end + 1 :]
                else:
                    self.buffer = self.buffer[1:]
            else:
                key = SINGLE_KEYS.get(self.buffer[0])
                if key:
                    keys.append(key)
                self.buffer = self.buffer[1:]
        if len(self.buffer) > 32:
            self.buffer = b""
        return keys


class TerminalKeys:
    """Read only this process's terminal; preserve Ctrl-C and restore tty settings."""

    def __init__(self, stream=None):
        self.stream = sys.stdin if stream is None else stream
        self.fd = None
        self.saved = None
        self.decoder = KeyDecoder()

    def __enter__(self):
        import termios
        import tty

        self.fd = self.stream.fileno()
        self.saved = termios.tcgetattr(self.fd)
        try:
            tty.setcbreak(self.fd, termios.TCSANOW)
        except BaseException:
            self.close()
            raise
        return self

    def read(self):
        ready, _, _ = select.select([self.fd], [], [], 0)
        if not ready:
            return []
        data = os.read(self.fd, 1024)
        return self.decoder.feed(data) if data else ["QUIT"]

    def close(self):
        if self.saved is not None:
            import termios

            try:
                termios.tcsetattr(self.fd, termios.TCSANOW, self.saved)
            finally:
                self.saved = None

    def __exit__(self, *args):
        self.close()


@dataclass
class DisplayControls:
    speed: int = 0
    atc: int = 0
    door: bool = False
    focus: int = 0
    dirty: bool = True
    quit: bool = False
    writes: int = 0
    reset_ok: Optional[bool] = None

    @property
    def display(self):
        return Display(speed=self.speed, limit=self.atc, door=self.door)

    @property
    def signature(self):
        return self.speed, self.atc, self.door, self.focus, self.writes

    def handle(self, key):
        if key == "QUIT":
            self.quit = True
        elif key in ("TAB", "BACKTAB"):
            self.focus = (self.focus + (1 if key == "TAB" else -1)) % 3
        elif self.focus == 2:
            door = self.door
            if key == "TOGGLE":
                door = not door
            elif key in ("UP", "RIGHT"):
                door = True
            elif key in ("DOWN", "LEFT"):
                door = False
            if door != self.door:
                self.door, self.dirty = door, True
        else:
            delta = {"UP": 1, "DOWN": -1, "RIGHT": 10, "LEFT": -10}.get(key, 0)
            name = "speed" if self.focus == 0 else "atc"
            old = getattr(self, name)
            new = min(999, max(0, old + delta))
            if new != old:
                setattr(self, name, new)
                self.dirty = True

    def selection(self, compact=False):
        fields = (
            f"SPEED {self.speed:03}",
            f"ATC {self.atc:03}",
            f"DOOR {'ON' if self.door else 'OFF'}",
        )
        if compact:
            return "Selected: " + fields[self.focus]
        return "Requested: " + "  ".join(
            f">{value}<" if i == self.focus else value for i, value in enumerate(fields)
        )

    def send(self, controller):
        if self.dirty:
            controller.write_display(self.display)
            self.writes += 1
            self.dirty = False

    def reset(self, controller):
        try:
            controller.write_display(Display())
            self.reset_ok = True
        except (OSError, DeviceError) as exc:
            self.reset_ok = False
            warnings.warn(f"Could not reset the controller displays; check the connection: {exc}")

    def summary(self):
        status = (
            "reset to 0/0, door OFF" if self.reset_ok else "reset not confirmed; check controller"
        )
        return f"Display tests: {self.writes} successful manual transfers; {status}. No game telemetry."
