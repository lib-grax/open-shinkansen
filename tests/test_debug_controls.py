import io
import os
import select
import signal
import struct
import subprocess
import sys
import time
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from open_shinkansen import cli, usb
from open_shinkansen.debug import CLOSE_SCREEN, DebugState, render
from open_shinkansen.debug_controls import (
    DisplayControls,
    KeyDecoder,
    TerminalKeys,
    require_terminal,
)
from open_shinkansen.protocol import Display


class TTY(io.StringIO):
    def isatty(self):
        return True


def test_tab_cycles_output_fields_without_sending_or_changing_values():
    controls = DisplayControls(dirty=False)
    for expected in (1, 2, 0):
        controls.handle("TAB")
        assert controls.focus == expected
        assert not controls.dirty
    controls.handle("BACKTAB")
    assert controls.focus == 2
    assert controls.display == Display()


def test_arrows_adjust_speed_and_atc_and_space_toggles_only_the_door():
    controls = DisplayControls()
    controls.handle("UP")
    controls.handle("RIGHT")
    assert controls.speed == 11
    controls.handle("LEFT")
    assert controls.speed == 1
    controls.handle("TOGGLE")
    assert not controls.door
    controls.handle("TAB")
    controls.handle("RIGHT")
    assert controls.atc == 10
    controls.handle("TAB")
    controls.handle("TOGGLE")
    assert controls.door
    controls.handle("DOWN")
    assert not controls.door
    controls.handle("RIGHT")
    assert controls.door


def test_numeric_values_are_clamped_and_never_send_rumble():
    controls = DisplayControls()
    for _ in range(200):
        controls.handle("RIGHT")
    assert controls.speed == 999
    controller = MagicMock()
    controls.send(controller)
    assert controls.display.encode()[:2] == b"\0\0"
    assert controls.display.encode()[4:6] == b"\x99\x09"
    controls.handle("UP")
    assert not controls.dirty
    for _ in range(200):
        controls.handle("LEFT")
    assert controls.speed == 0


def test_unchanged_values_do_not_write_repeatedly_and_exit_resets_all_outputs():
    controls = DisplayControls()
    controller = MagicMock()
    controls.send(controller)
    controls.send(controller)
    assert controls.writes == 1
    controller.write_display.assert_called_once_with(Display())
    controls.handle("RIGHT")
    controls.send(controller)
    assert controls.writes == 2
    controls.reset(controller)
    controller.write_display.assert_called_with(Display())
    assert controls.reset_ok
    assert "reset to 0/0, door OFF" in controls.summary()


def test_disconnected_reset_warns_without_masking_the_original_error():
    controls = DisplayControls()
    controller = MagicMock()
    controller.write_display.side_effect = OSError("Unplugged")
    with pytest.warns(UserWarning, match="Could not reset"):
        controls.reset(controller)
    assert controls.reset_ok is False
    assert "reset not confirmed" in controls.summary()


@pytest.mark.parametrize(
    "sequence,key",
    [
        (b"\x1b[A", "UP"),
        (b"\x1b[B", "DOWN"),
        (b"\x1b[C", "RIGHT"),
        (b"\x1b[D", "LEFT"),
        (b"\x1bOA", "UP"),
        (b"\x1b[Z", "BACKTAB"),
    ],
)
def test_decoder_accepts_fragmented_arrow_and_shift_tab_sequences(sequence, key):
    for split in range(len(sequence) + 1):
        decoder = KeyDecoder()
        keys = decoder.feed(sequence[:split]) + decoder.feed(sequence[split:])
        assert keys == [key]


def test_decoder_maps_keys_and_ignores_unknown_terminal_sequences():
    decoder = KeyDecoder()
    assert decoder.feed(b"\t \r\nqQ") == ["TAB", "TOGGLE", "TOGGLE", "TOGGLE", "QUIT", "QUIT"]
    assert decoder.feed(b"\x1b[1;5Axyz\x7f") == []
    assert decoder.feed(b"\x1b[" + b"1" * 100) == []
    assert len(decoder.buffer) <= 32


@pytest.mark.parametrize("width,height", [(80, 24), (72, 24), (40, 13), (20, 4)])
def test_output_panel_fits_terminal_and_labels_values_as_manual(width, height):
    frame = render(DebugState(), 0, controls=DisplayControls(), width=width, height=height)
    assert len(frame.splitlines()) <= height
    assert max(map(len, frame.splitlines())) <= width - 1
    if width >= 40:
        assert "MANUAL" in frame
        assert "INPUT ONLY" not in frame
    assert all(ord(char) < 128 for char in frame)


def test_terminal_controls_require_real_input_and_output_ttys(monkeypatch):
    monkeypatch.setenv("TERM", "xterm")
    require_terminal(TTY(), TTY())
    with pytest.raises(ValueError, match="interactive"):
        require_terminal(io.StringIO(), TTY())
    monkeypatch.setenv("TERM", "dumb")
    with pytest.raises(ValueError):
        require_terminal(TTY(), TTY())


@pytest.mark.parametrize("extra", [["--plain"], ["--replay", "anything.jsonl"]])
def test_cli_rejects_noninteractive_output_modes_before_usb_access(monkeypatch, extra):
    factory = MagicMock(side_effect=AssertionError("Must not claim USB"))
    monkeypatch.setattr(usb, "Controller", factory)
    assert cli.main(["debug", "--outputs", *extra]) == 1
    factory.assert_not_called()


def test_cli_rejects_redirected_keyboard_or_screen_before_usb_access(monkeypatch):
    monkeypatch.setattr(cli.sys, "stdin", io.StringIO())
    factory = MagicMock(side_effect=AssertionError("Must not claim USB"))
    monkeypatch.setattr(usb, "Controller", factory)
    assert cli.main(["debug", "--outputs"]) == 1
    factory.assert_not_called()


@pytest.fixture
def interactive(monkeypatch):
    monkeypatch.setenv("TERM", "xterm")
    stream = TTY()
    controller = MagicMock()
    controller.__enter__.return_value = controller
    monkeypatch.setattr(usb, "Controller", lambda: controller)
    keyboard = MagicMock()

    @contextmanager
    def keys():
        try:
            yield keyboard
        finally:
            keyboard.close()

    monkeypatch.setattr("open_shinkansen.debug_controls.TerminalKeys", keys)

    def activate():
        # Pytest replaces capture streams between fixture setup and test calls.
        # Activate the fake interactive streams inside the actual test body.
        monkeypatch.setattr(cli.sys, "stdin", TTY())
        monkeypatch.setattr(cli.sys, "stdout", stream)
        return controller, keyboard, stream

    return activate


def test_cli_sends_manual_output_while_idle_and_resets_on_quit(interactive, monkeypatch):
    controller, keyboard, stream = interactive()
    keyboard.read.side_effect = [["UP"], ["TAB", "RIGHT"], ["TAB", "TOGGLE"], ["QUIT"]]
    monkeypatch.setattr(cli, "samples", lambda **kwargs: iter([(i / 10, None) for i in range(4)]))
    assert cli.main(["debug", "--outputs"]) == 0
    values = [call.args[0] for call in controller.write_display.call_args_list]
    assert values == [
        Display(),
        Display(speed=1),
        Display(speed=1, limit=10),
        Display(speed=1, limit=10, door=True),
        Display(),
    ]
    assert all(value.encode()[:2] == b"\0\0" for value in values)
    assert "MANUAL DISPLAY TESTS" in stream.getvalue()
    assert "NOT game telemetry" in stream.getvalue()
    assert "reset to 0/0, door OFF" in stream.getvalue()
    assert CLOSE_SCREEN in stream.getvalue()
    keyboard.close.assert_called_once()
    controller.__exit__.assert_called_once()


@pytest.mark.parametrize("signum", [signal.SIGTERM, signal.SIGINT, signal.SIGHUP])
def test_cli_resets_outputs_and_keyboard_on_signals(interactive, monkeypatch, signum):
    controller, keyboard, stream = interactive()
    old_handler = signal.getsignal(signum)
    keyboard.read.return_value = ["UP"]

    def interrupted(**kwargs):
        yield 0.1, None
        signal.raise_signal(signum)

    monkeypatch.setattr(cli, "samples", interrupted)
    assert cli.main(["debug", "--outputs"]) == 130
    controller.write_display.assert_called_with(Display())
    keyboard.close.assert_called_once()
    assert CLOSE_SCREEN in stream.getvalue()
    assert signal.getsignal(signum) == old_handler


def test_initial_display_failure_still_restores_keyboard_and_attempts_reset(
    interactive, monkeypatch
):
    controller, keyboard, stream = interactive()
    controller.write_display.side_effect = [OSError("USB write failed"), None]
    assert cli.main(["debug", "--outputs"]) == 1
    assert controller.write_display.call_count == 2
    controller.write_display.assert_called_with(Display())
    keyboard.close.assert_called_once()
    controller.__exit__.assert_called_once()
    assert CLOSE_SCREEN in stream.getvalue()


def test_cli_preserves_input_only_mode_without_any_display_transfer(monkeypatch):
    controller = MagicMock()
    controller.__enter__.return_value = controller
    monkeypatch.setattr(usb, "Controller", lambda: controller)
    monkeypatch.setattr(cli, "samples", lambda **kwargs: iter([(0, None)]))
    assert cli.main(["debug", "--plain"]) == 0
    controller.write_display.assert_not_called()


def tty_settings_without_pending_reprint(settings):
    import termios

    # BSD/macOS can set PENDIN when canonical mode is restored, requesting a
    # reprint of queued input. It is transient kernel state, not a mode leak.
    normalized = list(settings)
    normalized[3] &= ~getattr(termios, "PENDIN", 0)
    return normalized


@pytest.mark.skipif(os.name != "posix", reason="Requires a POSIX pseudo-terminal")
def test_real_terminal_keyboard_preserves_signals_and_restores_settings_after_error():
    import pty
    import termios

    master, slave = pty.openpty()
    stream = os.fdopen(os.dup(slave), "r")
    try:
        before = termios.tcgetattr(slave)
        with pytest.raises(RuntimeError), TerminalKeys(stream) as keyboard:
            during = termios.tcgetattr(slave)
            assert not during[3] & termios.ICANON
            assert not during[3] & termios.ECHO
            assert during[3] & termios.ISIG == before[3] & termios.ISIG
            os.write(master, b"\t\x1b[A q")
            assert select.select([keyboard.fd], [], [], 1)[0]
            assert keyboard.read() == ["TAB", "UP", "TOGGLE", "QUIT"]
            raise RuntimeError("USB failed")
        assert tty_settings_without_pending_reprint(
            termios.tcgetattr(slave)
        ) == tty_settings_without_pending_reprint(before)
    finally:
        stream.close()
        os.close(master)
        os.close(slave)


@pytest.mark.skipif(os.name != "posix", reason="Requires a POSIX pseudo-terminal")
def test_full_terminal_cli_edits_displays_and_resets_with_only_usb_mocked(tmp_path):
    import fcntl
    import pty
    import termios

    root = Path(__file__).parents[1]
    log = tmp_path / "display-writes.txt"
    code = """
import sys, time
from pathlib import Path
from open_shinkansen import usb
class Controller:
    def __enter__(self): return self
    def __exit__(self, *args): pass
    def read(self, timeout): time.sleep(timeout / 1000); return None
    def write_display(self, display):
        with Path(sys.argv[1]).open('a') as output:
            output.write(display.encode().hex() + '\\n')
usb.Controller = Controller
from open_shinkansen.cli import main
raise SystemExit(main(['debug', '--outputs']))
"""
    master, slave = pty.openpty()
    process = None
    received = b""
    try:
        fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 24, 80, 0, 0))
        before = termios.tcgetattr(slave)
        process = subprocess.Popen(
            [sys.executable, "-c", code, str(log)],
            stdin=slave,
            stdout=slave,
            stderr=slave,
            cwd=root,
            env={**os.environ, "TERM": "xterm-256color", "PYTHONPATH": str(root / "src")},
        )

        def wait_for(text):
            nonlocal received
            deadline = time.monotonic() + 10
            while text not in received:
                remaining = deadline - time.monotonic()
                assert remaining > 0, "No expected terminal output: " + repr(text)
                ready, _, _ = select.select([master], [], [], remaining)
                assert ready, "Timed out waiting for terminal output"
                received += os.read(master, 16384)

        wait_for(b"MANUAL DISPLAY TESTS")
        os.write(master, b"\x1b[C")
        wait_for(b">SPEED 010<")
        os.write(master, b"\t\x1b[C")
        wait_for(b">ATC 010<")
        os.write(master, b"\t ")
        wait_for(b">DOOR ON<")
        os.write(master, b"q")
        wait_for(b"Display tests:")
        assert process.wait(timeout=5) == 0
        assert tty_settings_without_pending_reprint(
            termios.tcgetattr(slave)
        ) == tty_settings_without_pending_reprint(before)
        assert CLOSE_SCREEN.encode() in received
        payloads = [bytes.fromhex(line) for line in log.read_text().splitlines()]
        assert payloads == [
            Display().encode(),
            Display(speed=10).encode(),
            Display(speed=10, limit=10).encode(),
            Display(speed=10, limit=10, door=True).encode(),
            Display().encode(),
        ]
        assert all(payload[:2] == b"\0\0" for payload in payloads)
    finally:
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
        os.close(master)
        os.close(slave)
