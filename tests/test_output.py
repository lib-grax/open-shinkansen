"""Exercise the evdev adapter without creating or injecting any real input."""

import sys
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from open_shinkansen import output
from open_shinkansen.events import Event
from open_shinkansen.profiles import KEY_NAMES


@pytest.fixture
def evdev(monkeypatch):
    constants = {name: i for i, name in enumerate(sorted(KEY_NAMES), 1)}
    constants.update(
        EV_KEY=1,
        EV_ABS=3,
        ABS_X=0,
        ABS_Y=1,
        ABS_HAT0X=16,
        ABS_HAT0Y=17,
        BUS_VIRTUAL=6,
        BTN_JOYSTICK=288,
    )
    codes = SimpleNamespace(**constants)
    factory = MagicMock()
    module = SimpleNamespace(ecodes=codes, UInput=factory, AbsInfo=lambda *args: args)
    monkeypatch.setitem(sys.modules, "evdev", module)
    monkeypatch.setattr(output.sys, "platform", "linux")
    return factory, codes


def test_joystick_capabilities_and_frame_sync(evdev):
    factory, codes = evdev
    sink = output.UInputOutput("joystick")
    capabilities = factory.call_args.args[0]
    assert capabilities[codes.EV_KEY] == list(range(288, 296))
    assert capabilities[codes.EV_ABS] == [
        (0, (0, 0, 32767, 0, 0, 0)),
        (1, (0, 0, 32767, 0, 0, 0)),
        (16, (0, -1, 1, 0, 0, 0)),
        (17, (0, -1, 1, 0, 0, 0)),
    ]
    assert factory.call_args.kwargs["name"] == output.DEVICE_NAME
    assert factory.call_args.kwargs["bustype"] == 6
    sink.emit([Event("abs", "ABS_X", 32767), Event("key", "BTN_7", 1)])
    assert factory.return_value.write.call_args_list[0].args == (3, 0, 32767)
    assert factory.return_value.write.call_args_list[1].args == (1, 295, 1)
    factory.return_value.syn.assert_called_once()
    sink.emit([])
    factory.return_value.syn.assert_called_once()
    sink.close()
    factory.return_value.close.assert_called_once()


def test_keyboard_capabilities(evdev):
    factory, codes = evdev
    sink = output.UInputOutput("keyboard")
    assert codes.EV_ABS not in factory.call_args.args[0]
    assert codes.KEY_SPACE in factory.call_args.args[0][codes.EV_KEY]
    sink.emit([Event("key", "KEY_SPACE", 1), Event("key", "KEY_SPACE", 0)])
    assert factory.return_value.write.call_args_list[0].args == (1, codes.KEY_SPACE, 1)
    assert factory.return_value.write.call_args_list[1].args == (1, codes.KEY_SPACE, 0)


def test_non_linux_output_fails_before_import(monkeypatch):
    monkeypatch.setattr(output.sys, "platform", "darwin")
    with pytest.raises(RuntimeError, match="Linux"):
        output.UInputOutput("joystick")
