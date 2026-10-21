"""Platform-neutral event generation, shared by real uinput and dry-run outputs."""

from dataclasses import dataclass
from typing import Optional

from .protocol import BRAKE_CODES, HATS, POWER_CODES, State
from .settings import DEFAULT_PROFILE, validate_profile

JOYSTICK_BUTTONS = ("a", "b", "c", "d", "select", "start", "pedal", "emergency")
AXIS_MAX = 32767


@dataclass(frozen=True)
class Event:
    kind: str
    code: str
    value: int


def joystick_values(state: State, profile=DEFAULT_PROFILE) -> dict:
    validate_profile(profile)
    if not state.ready:
        return {}
    x, y = HATS[state.hat]
    if profile == "pcsx2-shinkansen":
        # Preserve the original report bytes through PCSX2 FullAxis+inversion
        # bindings with Axes Passthrough enabled. Positive-at-rest transport
        # lets PCSX2's pedal-style GUI capture detect the entire handle range.
        power = round((255 - POWER_CODES[state.power]) * AXIS_MAX / 255)
        brake = round((255 - BRAKE_CODES[state.brake]) * AXIS_MAX / 255)
    else:
        # Generic games get full service brake at B7, with a separate EB button.
        power = round(state.power * AXIS_MAX / 13)
        brake = round(min(state.brake, 7) * AXIS_MAX / 7)
    values = {
        ("abs", "ABS_X"): power,
        ("abs", "ABS_Y"): brake,
        ("abs", "ABS_HAT0X"): x,
        ("abs", "ABS_HAT0Y"): y,
    }
    for index, name in enumerate(JOYSTICK_BUTTONS):
        pressed = name in state.controls
        if profile == "pcsx2-shinkansen":
            if name == "c":
                pressed = pressed or state.pedal  # PCSX2 exposes C as horn, not a pedal binding.
            elif name in ("pedal", "emergency"):
                # Avoid extra button events forming a chord during axis capture.
                # Emergency is represented faithfully by its own brake-axis code.
                pressed = False
        values[("key", f"BTN_{index}")] = int(pressed)
    return values


class JoystickMapper:
    def __init__(self, profile=DEFAULT_PROFILE):
        self.profile = validate_profile(profile)
        self.previous = {}

    def update(self, state: State) -> list:
        values = joystick_values(state, self.profile)
        events = [
            Event(kind, code, value)
            for (kind, code), value in values.items()
            if self.previous.get((kind, code)) != value
        ]
        self.previous.update(values)
        return events

    def close(self) -> list:
        # Reset semantic controls before destroying the device. In the raw-byte
        # profile, neutral/released are encoded nonzero values, not axis zero.
        neutral = joystick_values(State(power=0, brake=0), self.profile)
        events = [
            Event(kind, code, neutral[(kind, code)])
            for (kind, code), value in self.previous.items()
            if value != neutral[(kind, code)]
        ]
        self.previous.clear()
        return events


class KeyboardMapper:
    """Held buttons + edge-triggered absolute keys or relative notch pulses.

    Relative mode assumes the first observed lever position matches the game.
    This is intentionally NOT an absolute-position guarantee without telemetry.
    Pending pulses for a lever are replaced on a new target, using emitted steps
    as the reference, rather than the previous physical position.
    """

    def __init__(self, profile: dict):
        self.profile = profile
        self.held = set()
        self.pulse: Optional[str] = None
        self.deadline = 0.0
        self.positions = {}
        self.targets = {}
        self.cursor = 0
        self.available = {}
        self.pulse_keys = {
            config[direction]
            for axis in ("power", "brake")
            for config in (profile[axis],)
            if config["mode"] == "relative"
            for direction in ("increase", "decrease")
        }

    def update(self, state: State):
        if not state.ready:
            return
        held = {
            key for control, key in self.profile["buttons"].items() if control in state.controls
        }
        for axis in ("power", "brake"):
            config = self.profile[axis]
            raw = getattr(state, axis)
            if config["mode"] == "absolute":
                key = config["keys"][raw]
                if key:
                    held.add(key)
            elif config["mode"] == "relative":
                target = (raw * config["steps"] + (13 if axis == "power" else 8) // 2) // (
                    13 if axis == "power" else 8
                )
                self.positions.setdefault(axis, target)
                self.targets[axis] = target
        self.desired = held

    def tick(self, now: float) -> list:
        before = self.held | ({self.pulse} if self.pulse else set())
        desired = getattr(self, "desired", set())
        pulse_ms = self.profile["pulse_ms"] / 1000
        gap_ms = self.profile["gap_ms"] / 1000
        for key in (self.held - desired) & self.pulse_keys:
            # A released shared button must produce a real key-up and a gap
            # before reusing that key for a lever pulse. Otherwise the logical
            # step would be counted without any new key-down event.
            self.available[key] = now + gap_ms
        if self.pulse is not None and now >= self.deadline:
            self.pulse = None
            self.deadline = now + gap_ms
        self.held = set(desired)
        if self.pulse is None and now >= self.deadline:
            axes = ("power", "brake")
            for offset in range(2):
                index = (self.cursor + offset) % 2
                axis = axes[index]
                if axis not in self.targets or self.targets[axis] == self.positions[axis]:
                    continue
                delta = 1 if self.targets[axis] > self.positions[axis] else -1
                key = self.profile[axis]["increase" if delta > 0 else "decrease"]
                if key in desired or now < self.available.get(key, 0):
                    continue
                self.positions[axis] += delta
                self.pulse = key
                self.deadline = now + pulse_ms
                self.cursor = (index + 1) % 2
                break
        after = self.held | ({self.pulse} if self.pulse else set())
        return [Event("key", key, 0) for key in sorted(before - after)] + [
            Event("key", key, 1) for key in sorted(after - before)
        ]

    def close(self) -> list:
        keys = self.held | ({self.pulse} if self.pulse else set())
        self.held.clear()
        self.pulse = None
        self.positions.clear()
        self.targets.clear()
        self.available.clear()
        self.desired = set()
        return [Event("key", key, 0) for key in sorted(keys)]
