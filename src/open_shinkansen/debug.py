"""ASCII input dashboard with optional explicit manual display tests; no game input."""

import math
import os
import sys
from dataclasses import dataclass, field
from typing import Optional

from .protocol import BRAKE_CODES, HATS, POWER_CODES, State, decode

BUTTONS = ("a", "b", "c", "d", "select", "start")
HAT_NAMES = (
    "UP",
    "UP-RIGHT",
    "RIGHT",
    "DOWN-RIGHT",
    "DOWN",
    "DOWN-LEFT",
    "LEFT",
    "UP-LEFT",
    "CENTER",
)
HAT_SHORT = ("U", "UR", "R", "DR", "D", "DL", "L", "UL", "C")
OPEN_SCREEN = "\x1b[?1049h\x1b[?25l"
CLOSE_SCREEN = "\x1b[?25h\x1b[?1049l"


@dataclass
class DebugState:
    state: Optional[State] = None
    raw: Optional[bytes] = None
    reports: int = 0
    changes: int = 0
    transitions: int = 0
    unknown: int = 0
    last_report: Optional[float] = None
    powers: set = field(default_factory=set)
    brakes: set = field(default_factory=set)
    hats: set = field(default_factory=set)
    pedals: set = field(default_factory=set)
    buttons: set = field(default_factory=set)
    presses: dict = field(default_factory=lambda: dict.fromkeys(BUTTONS, 0))

    def observe(self, elapsed: float, raw: bytes):
        previous = self.state
        state = decode(raw, previous)
        self.changes += int(state != previous)
        self.reports += 1
        self.transitions += int(raw[0] == 0xFF or raw[1] == 0xFF)
        self.unknown += int(
            raw[0] not in (*BRAKE_CODES, 0xFF)
            or raw[1] not in (*POWER_CODES, 0xFF)
            or raw[2] not in (0, 0xFF)
            or raw[3] > 8
        )
        if raw[0] in BRAKE_CODES:
            self.brakes.add(BRAKE_CODES.index(raw[0]))
        if raw[1] in POWER_CODES:
            self.powers.add(POWER_CODES.index(raw[1]))
        # Startup packets with unknown handle codes must not count as tested buttons/pedal.
        if state.ready:
            if raw[3] <= 8:
                self.hats.add(raw[3])
            if raw[2] in (0, 0xFF):
                self.pedals.add(state.pedal)
            self.buttons.update(state.buttons)
            previous_buttons = previous.buttons if previous and previous.ready else frozenset()
            for name in state.buttons - previous_buttons:
                self.presses[name] += 1
        self.state, self.raw, self.last_report = state, bytes(raw), elapsed


def _mark(active, known=True):
    return ("*" if active else ".") if known else "?"


def _bar(position, maximum):
    return "?" * maximum if position is None else "#" * position + "." * (maximum - position)


def _raw_notch(raw, codes):
    if raw is None:
        return "-- (waiting)"
    if raw == 0xFF:
        return "ff TRANSITION (last valid notch held)"
    return f"{raw:02x} " + ("OK" if raw in codes else "UNKNOWN (last valid notch held)")


def _seen(labels, observed):
    return " ".join(label + ("+" if i in observed else ".") for i, label in enumerate(labels))


def summary(model):
    return (
        f"Debug summary: reports={model.reports}; observed power={len(model.powers)}/14, "
        f"brake={len(model.brakes)}/9, buttons={len(model.buttons)}/6, "
        f"hat={len(model.hats)}/9, pedal={len(model.pedals)}/2; "
        f"transitions={model.transitions}, unknown={model.unknown}"
    )


def render(
    model: DebugState,
    elapsed: float,
    source="LIVE USB",
    recording=False,
    width=80,
    height=24,
    controls=None,
):
    """Pure ASCII frame; fit the terminal without wrapping at its right/bottom edges."""
    # Leave the last terminal column unused to avoid automatic line wrapping.
    width = min(80, max(1, width - 1))
    height = max(1, height)
    if width < 39 or height < 13:
        lines = [
            "Terminal too small for controller debug.",
            "Resize to at least 40 columns x 13 rows.",
            "Recommended: 80 columns x 24 rows. Ctrl-C quits.",
        ]
        return "\n".join(line[:width] for line in lines[:height])
    state = model.state or State()
    raw = model.raw
    known = state.ready
    power = "?" if state.power is None else ("N" if state.power == 0 else f"P{state.power}")
    brake = (
        "?"
        if state.brake is None
        else ("EB" if state.emergency else ("REL" if state.brake == 0 else f"B{state.brake}"))
    )
    status = "READY" if known else "WAITING FOR VALID HANDLE READINGS"
    pedal = ("PRESSED" if state.pedal else "released") if known else "?"
    emergency = ("ACTIVE" if state.emergency else "off") if known else "?"
    buttons = " ".join(
        f"[{name.upper()}:{_mark(name in state.buttons, known)}]" for name in BUTTONS
    )
    age = "--" if model.last_report is None else f"{max(0, elapsed - model.last_report):.1f}s"
    raw_text = raw.hex(" ") if raw is not None else "waiting for first report; move a handle"
    coverage = (
        f"Observed: power {len(model.powers)}/14  brake {len(model.brakes)}/9  "
        f"buttons {len(model.buttons)}/6"
    )
    dpad = HAT_NAMES[state.hat] if known else "?"
    if width < 71 or height < 24:
        content = [
            "OPEN-SHINKANSEN - INPUT DEBUG",
            f"{source} | INPUT ONLY | {status}",
            f"POWER {power:>3} [{_bar(state.power, 13)}]",
            f"BRAKE {brake:>3} [{_bar(state.brake, 8)}] EB={emergency}",
            f"D-pad: {dpad}  Pedal: {pedal}",
            " ".join(f"[{n.upper()}:{_mark(n in state.buttons, known)}]" for n in BUTTONS[:4]),
            " ".join(f"[{n.upper()}:{_mark(n in state.buttons, known)}]" for n in BUTTONS[4:]),
            f"Seen P:{len(model.powers)}/14 B:{len(model.brakes)}/9 hat:{len(model.hats)}/9 pedal:{len(model.pedals)}/2",
            f"Reports:{model.reports}  Last:{age} (idle is normal)",
            "Raw: " + raw_text,
            "Ctrl-C quits; --outputs tests LEDs",
        ]
    else:
        x, y = HATS[state.hat]
        content = [
            "OPEN-SHINKANSEN / TAITO TCPP-20011 - INPUT DEBUG",
            f"{source} | INPUT ONLY: no injected input, LEDs or rumble",
            f"Status: {status}   Elapsed: {elapsed:.1f}s",
            "",
            f"POWER {power:>3} [{_bar(state.power, 13)}]   raw: {_raw_notch(raw[1] if raw else None, POWER_CODES)}",
            "P seen: " + _seen(("N", *[f"{i:02}" for i in range(1, 14)]), model.powers),
            f"BRAKE {brake:>3} [{_bar(state.brake, 8)}]        raw: {_raw_notch(raw[0] if raw else None, BRAKE_CODES)}",
            "B seen: " + _seen(("R", *[f"{i:02}" for i in range(1, 8)], "EB"), model.brakes),
            "",
            buttons,
            "Press counts: " + " ".join(f"{n.upper()}={model.presses[n]}" for n in BUTTONS),
            f"Pedal: {pedal}   Emergency: {emergency}",
            "",
            f"D-pad: {dpad}       Hat seen: {_seen(HAT_SHORT, model.hats)}",
            f"        [U:{_mark(y < 0, known)}]        Pedal seen: {_seen(('up', 'down'), model.pedals)}",
            f" [L:{_mark(x < 0, known)}]  [C:{_mark(state.hat == 8, known)}]  [R:{_mark(x > 0, known)}]",
            f"        [D:{_mark(y > 0, known)}]",
            "Raw: " + raw_text,
            f"Reports:{model.reports}  Changes:{model.changes}  Transitions:{model.transitions}  Unknown:{model.unknown}",
            f"Last report: {age} ago (idle timeouts are normal)",
            coverage,
            f"Ctrl-C quits | --outputs: displays | +seen .unseen *active | Recording: {'YES' if recording else 'no'}",
        ]
    if controls is not None:
        if width < 71 or height < 24:
            content = [
                "OPEN-SHINKANSEN - DISPLAY TEST",
                "MANUAL VALUES; rumble always OFF",
                controls.selection(compact=True),
                "Tab field; U/D +/-1; L/R +/-10",
                f"Power:{power} Brake:{brake} Pedal:{pedal}",
                f"D-pad:{dpad} Emergency:{emergency}",
                " ".join(f"[{n.upper()}:{_mark(n in state.buttons, known)}]" for n in BUTTONS[:4]),
                " ".join(f"[{n.upper()}:{_mark(n in state.buttons, known)}]" for n in BUTTONS[4:]),
                f"USB writes:{controls.writes}; Space/Enter: door",
                "Raw: " + raw_text,
                "Q/Ctrl-C quits; resets 0/0 + lamp",
            ]
        else:
            content[1] = f"{source} | MANUAL DISPLAY TESTS; rumble always OFF"
            if recording:
                content[1] += " [REC]"
            content[2] = f"Input: {status}   Elapsed: {elapsed:.1f}s"
            content[3] = controls.selection()
            content[8] = "Tab field | Up/Down +/-1 | Left/Right +/-10 | Space/Enter door"
            content[12] = (
                f"Display USB writes: {controls.writes} (requested values; visually check hardware)"
            )
            content[-1] = "Q/Ctrl-C quits + resets displays | Manual tests, NOT game telemetry"
    inner = width - 4
    border = "+" + "-" * (width - 2) + "+"
    return "\n".join(
        [border, *("| " + line[:inner].ljust(inner) + " |" for line in content), border]
    )


class Dashboard:
    """ANSI screen on a real terminal, plain snapshots when redirected or --plain."""

    def __init__(self, source="LIVE USB", recording=False, plain=False, stream=None, controls=None):
        self.stream = stream if stream is not None else sys.stdout
        self.source, self.recording = source, recording
        self.controls = controls
        self.interactive = self.stream.isatty() and os.environ.get("TERM") != "dumb" and not plain
        self.active = False
        self.last_draw = -math.inf
        self.last_signature = object()

    def __enter__(self):
        if self.interactive:
            self.active = True
            try:
                self.stream.write(OPEN_SCREEN)
                self.stream.flush()
            except BaseException:
                self.close()
                raise
        return self

    def draw(self, model, elapsed, force=False):
        signature = (
            model.state,
            model.raw,
            model.reports,
            self.controls.signature if self.controls is not None else None,
        )
        if not force and (
            elapsed - self.last_draw < 0.1
            or (not self.interactive and signature == self.last_signature)
        ):
            return
        try:
            size = os.get_terminal_size(self.stream.fileno()) if self.interactive else (81, 24)
        except (OSError, ValueError):
            size = (81, 24)
        if size[0] <= 0 or size[1] <= 0:
            size = (81, 24)
        frame = render(model, elapsed, self.source, self.recording, *size, controls=self.controls)
        self.stream.write(
            ("\x1b[H" + frame.replace("\n", "\x1b[K\r\n") + "\x1b[K\x1b[J")
            if self.interactive
            else frame + "\n\n"
        )
        self.stream.flush()
        self.last_draw, self.last_signature = elapsed, signature

    def close(self):
        if self.active:
            try:
                self.stream.write(CLOSE_SCREEN)
                self.stream.flush()
            finally:
                self.active = False

    def __exit__(self, *args):
        self.close()
