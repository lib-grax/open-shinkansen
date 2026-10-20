"""Wire format documented by the Train Controller Database (see docs/research.md).

Notches are discrete codes, not linear ADC readings. Unknown values, including
0xff between detents and the all-zero startup packet, must not become commands.
"""

from dataclasses import dataclass
from typing import FrozenSet, Optional

VID = 0x0AE4
PID = 0x0005
BRAKE_CODES = (0x1C, 0x38, 0x54, 0x70, 0x8B, 0xA7, 0xC3, 0xDF, 0xFB)
POWER_CODES = (
    0x12,
    0x24,
    0x36,
    0x48,
    0x5A,
    0x6C,
    0x7E,
    0x90,
    0xA2,
    0xB4,
    0xC6,
    0xD7,
    0xE9,
    0xFB,
)
BUTTON_BITS = {"d": 0x01, "c": 0x02, "b": 0x04, "a": 0x08, "select": 0x10, "start": 0x20}
HATS = ((0, -1), (1, -1), (1, 0), (1, 1), (0, 1), (-1, 1), (-1, 0), (-1, -1), (0, 0))


@dataclass(frozen=True)
class State:
    power: Optional[int] = None  # 0=N, 1..13=P1..P13; None until observed
    brake: Optional[int] = None  # 0=released, 1..7=service, 8=emergency
    pedal: bool = False
    hat: int = 8
    buttons: FrozenSet[str] = frozenset()

    @property
    def ready(self) -> bool:
        return self.power is not None and self.brake is not None

    @property
    def emergency(self) -> bool:
        return self.brake == 8

    @property
    def controls(self) -> FrozenSet[str]:
        x, y = HATS[self.hat]
        names = set(self.buttons)
        if self.pedal:
            names.add("pedal")
        if self.emergency:
            names.add("emergency")
        if x:
            names.add("right" if x > 0 else "left")
        if y:
            names.add("down" if y > 0 else "up")
        return frozenset(names)

    def to_dict(self) -> dict:
        return {
            "power": self.power,
            "brake": self.brake,
            "emergency": self.emergency,
            "pedal": self.pedal,
            "hat": self.hat,
            "buttons": sorted(self.buttons),
            "ready": self.ready,
        }


def _notch(raw: int, codes: tuple, previous: Optional[int]) -> Optional[int]:
    # Never round an unknown code to the closest notch: 0xff is NOT full power.
    return codes.index(raw) if raw in codes else previous


def decode(report: bytes, previous: Optional[State] = None) -> State:
    if len(report) not in (6, 8):
        raise ValueError(f"Expected a 6-byte report (or 8-byte padded report), got {len(report)}")
    old = previous or State()
    return State(
        power=_notch(report[1], POWER_CODES, old.power),
        brake=_notch(report[0], BRAKE_CODES, old.brake),
        pedal=report[2] == 0,
        hat=report[3] if report[3] <= 8 else old.hat,
        buttons=frozenset(name for name, bit in BUTTON_BITS.items() if report[4] & bit),
    )


def bcd(value: int) -> bytes:
    if type(value) is not int or not 0 <= value <= 999:
        raise ValueError("Display values must be integers between 0 and 999")
    return bytes([((value // 10 % 10) << 4) | (value % 10), value // 100])


@dataclass(frozen=True)
class Display:
    speed: int = 0
    limit: int = 0
    door: bool = False
    approach: int = 0
    gauge: Optional[int] = None  # None derives gauge from speed, in 15 km/h steps

    def encode(self) -> bytes:
        speed, limit = bcd(self.speed), bcd(self.limit)
        gauge = min(22, (self.speed + 14) // 15) if self.gauge is None else self.gauge
        if type(gauge) is not int or not 0 <= gauge <= 22:
            raise ValueError("Gauge must be between 0 and 22")
        if type(self.approach) is not int or not 0 <= self.approach <= 10:
            raise ValueError("Approach must be between 0 and 10")
        # Both rumble motors always OFF. No unbounded motor activation.
        return bytes([0, 0, (0x80 if self.door else 0) | self.approach, gauge]) + speed + limit
