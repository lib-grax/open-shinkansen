import io
import json
import os
import select
import signal
import struct
import subprocess
import sys
import time
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from open_shinkansen import cli, usb
from open_shinkansen.debug import CLOSE_SCREEN, OPEN_SCREEN, Dashboard, DebugState, render
from open_shinkansen.protocol import BRAKE_CODES, BUTTON_BITS, POWER_CODES

NEUTRAL = bytes.fromhex("1c 12 ff 08 00 00")
HELD = bytes.fromhex("38 48 00 01 08 00")


class TTY(io.StringIO):
    def isatty(self):
        return True


def test_initial_screen_does_not_invent_neutral_or_test_coverage():
    frame = render(DebugState(), 0)
    assert "WAITING FOR VALID HANDLE READINGS" in frame
    assert "POWER   ? [?????????????]" in frame
    assert "BRAKE   ? [????????]" in frame
    assert "buttons 0/6" in frame
    assert "N+" not in frame
    assert all(ord(char) < 128 for char in frame)


def test_dashboard_shows_handles_buttons_hat_pedal_and_raw():
    model = DebugState()
    model.observe(0, HELD)
    frame = render(model, 1)
    for text in (
        "POWER  P3 [###..........]",
        "BRAKE  B1 [#.......]",
        "[A:*]",
        "[B:.]",
        "UP-RIGHT",
        "[U:*]",
        "[R:*]",
        "Pedal: PRESSED",
        "Emergency: off",
        "38 48 00 01 08 00",
        "A=1",
        "1.0s ago",
    ):
        assert text in frame


def test_emergency_and_transition_values_are_visible_but_not_added_to_coverage():
    model = DebugState()
    model.observe(0, bytes.fromhex("fb 12 ff 08 00 00"))
    assert "Emergency: ACTIVE" in render(model, 0)
    model.observe(0.2, bytes.fromhex("ff ff ff 08 00 00"))
    frame = render(model, 0.2)
    assert "BRAKE  EB [########]" in frame
    assert "TRANSITION (last valid notch held)" in frame
    assert model.transitions == 1
    assert model.unknown == 0
    assert model.powers == {0}
    assert model.brakes == {8}


def test_unknown_startup_and_corrupt_codes_are_not_counted_as_tested_controls():
    model = DebugState()
    model.observe(0, bytes.fromhex("00 00 00 08 3f 00"))
    assert not model.powers and not model.brakes
    assert not model.buttons and not model.pedals and not model.hats
    assert all(count == 0 for count in model.presses.values())
    assert model.unknown == 1
    assert "UNKNOWN" in render(model, 0)


def test_full_sweep_records_notches_buttons_hat_states_and_pedal_states():
    model = DebugState()
    for code in POWER_CODES:
        model.observe(0, bytes([0x1C, code, 0xFF, 8, 0, 0]))
    for code in BRAKE_CODES:
        model.observe(0, bytes([code, 0x12, 0xFF, 8, 0, 0]))
    for mask in BUTTON_BITS.values():
        model.observe(0, bytes([0x1C, 0x12, 0, 8, mask, 0]))
        model.observe(0, NEUTRAL)
    for hat in range(9):
        model.observe(0, bytes([0x1C, 0x12, 0xFF, hat, 0, 0]))
    assert model.powers == set(range(14))
    assert model.brakes == set(range(9))
    assert model.hats == set(range(9))
    assert model.pedals == {False, True}
    assert model.buttons == set(BUTTON_BITS)
    assert all(count == 1 for count in model.presses.values())
    assert "power 14/14  brake 9/9  buttons 6/6" in render(model, 0)


def test_press_counts_use_edges_not_number_of_packets():
    model = DebugState()
    for raw in (NEUTRAL, HELD, HELD, HELD, NEUTRAL, HELD, NEUTRAL):
        model.observe(0, raw)
    assert model.presses["a"] == 2
    assert model.reports == 7
    assert model.changes == 5


@pytest.mark.parametrize("width,height", [(80, 24), (72, 24), (60, 18), (40, 13), (20, 4), (5, 1)])
def test_render_fits_small_and_standard_terminals(width, height):
    model = DebugState()
    model.observe(0, HELD)
    frame = render(model, 1, width=width, height=height)
    assert len(frame.splitlines()) <= height
    assert max(map(len, frame.splitlines())) <= width - 1
    assert all(ord(char) < 128 for char in frame)


def test_interactive_screen_restored_after_error(monkeypatch):
    monkeypatch.setenv("TERM", "xterm-256color")
    stream = TTY()
    with pytest.raises(RuntimeError), Dashboard(stream=stream) as screen:
        screen.draw(DebugState(), 0)
        raise RuntimeError("USB failure")
    assert stream.getvalue().startswith(OPEN_SCREEN)
    assert stream.getvalue().endswith(CLOSE_SCREEN)


@pytest.mark.parametrize(
    "plain,dumb,tty", [(True, False, True), (False, True, True), (False, False, False)]
)
def test_plain_dumb_and_redirected_outputs_contain_no_escape_sequences(
    monkeypatch, plain, dumb, tty
):
    monkeypatch.setenv("TERM", "dumb" if dumb else "xterm")
    stream = TTY() if tty else io.StringIO()
    with Dashboard(plain=plain, stream=stream) as screen:
        screen.draw(DebugState(), 0)
    assert "\x1b" not in stream.getvalue()
    assert "OPEN-SHINKANSEN" in stream.getvalue()


def test_redraw_is_rate_limited_but_observation_is_not():
    stream = io.StringIO()
    model = DebugState()
    with Dashboard(stream=stream) as screen:
        screen.draw(model, 0)
        length = len(stream.getvalue())
        model.observe(0.01, HELD)
        model.observe(0.02, NEUTRAL)
        screen.draw(model, 0.02)
        assert len(stream.getvalue()) == length
        # Even when current state returns to a previous value, press counts are not lost.
        screen.draw(model, 0.2)
        assert "A=1" in stream.getvalue()
        length = len(stream.getvalue())
        screen.draw(model, 1)
        assert len(stream.getvalue()) == length  # No plain idle snapshot spam.


def capture(tmp_path, rows):
    path = tmp_path / "input.jsonl"
    path.write_text("".join(json.dumps({"t": 0, "raw": raw.hex()}) + "\n" for raw in rows))
    return path


def test_cli_replay_has_no_usb_or_virtual_input_access_and_can_record(
    tmp_path, monkeypatch, capsys
):
    path = capture(tmp_path, [NEUTRAL, HELD])
    controller = MagicMock(side_effect=AssertionError("Replay must not claim USB"))
    output = MagicMock(side_effect=AssertionError("Debug must not inject input"))
    monkeypatch.setattr(usb, "Controller", controller)
    monkeypatch.setattr(cli, "UInputOutput", output)
    recorded = tmp_path / "recorded.jsonl"
    assert cli.main(["debug", "--plain", "--replay", str(path), "--record", str(recorded)]) == 0
    text = capsys.readouterr().out
    assert "REPLAY FILE (no USB access)" in text
    assert "Recording: YES" in text
    assert "POWER  P3" in text
    assert "\x1b" not in text
    assert len(recorded.read_text().splitlines()) == 2
    controller.assert_not_called()
    output.assert_not_called()


def test_cli_live_debug_reads_input_only(monkeypatch, capsys):
    controller = MagicMock()
    controller.__enter__.return_value = controller
    controller.read.return_value = HELD
    monkeypatch.setattr(usb, "Controller", lambda: controller)
    monkeypatch.setattr(cli, "samples", lambda **kw: iter([(0.1, kw["read"]())]))
    assert cli.main(["debug", "--plain"]) == 0
    assert "LIVE USB 0ae4:0005" in capsys.readouterr().out
    controller.read.assert_called_once_with(20)
    controller.write_display.assert_not_called()
    controller.__exit__.assert_called_once()


def test_cli_error_restores_terminal_and_reports_capture_error(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("TERM", "xterm")
    path = capture(tmp_path, [HELD])
    with path.open("a") as handle:
        handle.write("invalid capture line\n")
    stream = TTY()
    monkeypatch.setattr(cli.sys, "stdout", stream)
    assert cli.main(["debug", "--replay", str(path)]) == 1
    assert stream.getvalue().index(CLOSE_SCREEN) < stream.getvalue().index("Debug summary:")
    assert "Invalid capture" in capsys.readouterr().err


def test_cli_sigterm_restores_terminal_and_closes_usb(monkeypatch, capsys):
    monkeypatch.setenv("TERM", "xterm")
    controller = MagicMock()
    controller.__enter__.return_value = controller
    monkeypatch.setattr(usb, "Controller", lambda: controller)
    stream = TTY()
    monkeypatch.setattr(cli.sys, "stdout", stream)

    def interrupted(**kwargs):
        yield 0.1, HELD
        signal.raise_signal(signal.SIGTERM)

    monkeypatch.setattr(cli, "samples", interrupted)
    assert cli.main(["debug"]) == 130
    assert stream.getvalue().index(CLOSE_SCREEN) < stream.getvalue().index("Debug summary:")
    controller.__exit__.assert_called_once()
    assert "no input injected" in capsys.readouterr().err


def test_cli_refuses_overwriting_existing_capture_before_opening_usb(tmp_path, monkeypatch):
    path = capture(tmp_path, [NEUTRAL])
    controller = MagicMock(side_effect=AssertionError("Must not open USB"))
    monkeypatch.setattr(usb, "Controller", controller)
    assert cli.main(["debug", "--record", str(path)]) == 1
    controller.assert_not_called()


@pytest.mark.skipif(os.name != "posix", reason="Pseudo-terminal test requires a POSIX terminal")
def test_real_terminal_replay_restores_screen_without_changing_terminal_settings(tmp_path):
    import fcntl
    import pty
    import termios

    path = capture(tmp_path, [HELD])
    root = Path(__file__).parents[1]
    master, slave = pty.openpty()
    process = None
    try:
        fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 24, 80, 0, 0))
        before = termios.tcgetattr(slave)
        process = subprocess.Popen(
            [sys.executable, "-m", "open_shinkansen", "debug", "--replay", str(path)],
            stdout=slave,
            stderr=slave,
            stdin=subprocess.DEVNULL,
            cwd=root,
            env={**os.environ, "TERM": "xterm-256color", "PYTHONPATH": str(root / "src")},
        )
        received = b""
        deadline = time.monotonic() + 10
        while b"Debug summary:" not in received:
            remaining = deadline - time.monotonic()
            assert remaining > 0, "Terminal dashboard did not finish"
            ready, _, _ = select.select([master], [], [], remaining)
            assert ready, "No terminal output before timeout"
            received += os.read(master, 16384)
        assert process.wait(timeout=5) == 0
        assert OPEN_SCREEN.encode() in received
        assert CLOSE_SCREEN.encode() in received
        assert received.index(CLOSE_SCREEN.encode()) < received.index(b"Debug summary:")
        assert b"POWER  P3" in received
        assert b"[A:*]" in received
        assert termios.tcgetattr(slave) == before
    finally:
        if process is not None and process.poll() is None:
            process.kill()
            process.wait(timeout=5)
        os.close(master)
        os.close(slave)
