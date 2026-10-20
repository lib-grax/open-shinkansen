"""Linux uinput backend, or a JSON dry-run sink that works on any platform."""

import json
import sys

from .profiles import KEY_NAMES

DEVICE_NAME = "open-shinkansen Virtual Joystick"


class DryRun:
    def emit(self, events):
        for event in events:
            print(
                json.dumps({"type": event.kind, "code": event.code, "value": event.value}),
                flush=True,
            )

    def close(self):
        pass


class UInputOutput:
    def __init__(self, mode: str):
        if not sys.platform.startswith("linux"):
            raise RuntimeError("Virtual input requires Linux /dev/uinput. Use --dry-run on macOS.")
        from evdev import AbsInfo, UInput, ecodes

        self.ecodes = ecodes
        self.codes = {name: getattr(ecodes, name) for name in KEY_NAMES}
        self.codes.update({f"BTN_{i}": ecodes.BTN_JOYSTICK + i for i in range(8)})
        if mode == "joystick":
            capabilities = {
                ecodes.EV_KEY: [self.codes[f"BTN_{i}"] for i in range(8)],
                ecodes.EV_ABS: [
                    (ecodes.ABS_X, AbsInfo(0, 0, 32767, 0, 0, 0)),
                    (ecodes.ABS_Y, AbsInfo(0, 0, 32767, 0, 0, 0)),
                    (ecodes.ABS_HAT0X, AbsInfo(0, -1, 1, 0, 0, 0)),
                    (ecodes.ABS_HAT0Y, AbsInfo(0, -1, 1, 0, 0, 0)),
                ],
            }
            self.codes.update(
                {
                    name: getattr(ecodes, name)
                    for name in ("ABS_X", "ABS_Y", "ABS_HAT0X", "ABS_HAT0Y")
                }
            )
            name = DEVICE_NAME
        else:
            capabilities = {ecodes.EV_KEY: [self.codes[name] for name in sorted(KEY_NAMES)]}
            name = "open-shinkansen Virtual Keyboard"
        self.device = UInput(
            capabilities, name=name, bustype=ecodes.BUS_VIRTUAL, vendor=0, product=0, version=1
        )

    def emit(self, events):
        for event in events:
            kind = self.ecodes.EV_ABS if event.kind == "abs" else self.ecodes.EV_KEY
            self.device.write(kind, self.codes[event.code], event.value)
        if events:
            self.device.syn()

    def close(self):
        self.device.close()
