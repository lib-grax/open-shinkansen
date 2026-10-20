"""Opt-in Linux smoke test: creates only a joystick, never a keyboard.

After reviewing/granting /dev/uinput access, run on Linux with:
TRAIN_CONTROLLER_UINPUT_TEST=1 .venv/bin/python -m pytest tests/test_uinput_integration.py
"""

import os
import select
import sys

import pytest

from open_shinkansen.events import Event
from open_shinkansen.output import UInputOutput

pytestmark = pytest.mark.skipif(
    sys.platform != "linux" or os.environ.get("TRAIN_CONTROLLER_UINPUT_TEST") != "1",
    reason="Real Linux uinput smoke test requires explicit opt-in and device permissions",
)


def test_real_virtual_joystick_loopback():
    from evdev import ecodes

    sink = UInputOutput("joystick")
    try:
        reader = sink.device.device
        # Open through evdev before emitting; don't depend on a game/SDL being present.
        sink.emit([Event("abs", "ABS_X", 12345), Event("key", "BTN_7", 1)])
        ready, _, _ = select.select([reader.fd], [], [], 2)
        assert ready, "No loopback events received from the virtual joystick"
        received = {(event.type, event.code, event.value) for event in reader.read()}
        assert (ecodes.EV_ABS, ecodes.ABS_X, 12345) in received
        assert (ecodes.EV_KEY, ecodes.BTN_JOYSTICK + 7, 1) in received
    finally:
        sink.emit([Event("key", "BTN_7", 0), Event("abs", "ABS_X", 0)])
        sink.close()
