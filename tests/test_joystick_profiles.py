import json
import math
import struct
from threading import Event as Stop
from unittest.mock import MagicMock

import pytest

from open_shinkansen import cli, daemon, settings, usb
from open_shinkansen.events import AXIS_MAX, Event, JoystickMapper, joystick_values
from open_shinkansen.protocol import BRAKE_CODES, POWER_CODES, State, decode

PROFILE = "pcsx2-shinkansen"


def f32(value):
    return struct.unpack("f", struct.pack("f", value))[0]


def pcsx2_axis_byte(axis, invert=True, full=True, symmetric=False):
    """Model evdev -> SDL signed axis -> PCSX2 binding -> original report byte.

    PCSX2 normalizes S16 by 32768/32767, maps FullAxis to 0..1, applies
    inversion, then rounds value*255. No upstream implementation is copied.
    """
    signed = (
        round((axis * 2 / AXIS_MAX - 1) * 32767)
        if symmetric
        else round(axis * 65535 / AXIS_MAX - 32768)
    )
    normalized = f32(signed / (32768 if signed < 0 else 32767))
    value = f32(f32(normalized * 0.5) + 0.5) if full else max(0, normalized)
    value = f32(1 - value) if invert else value
    return min(255, max(0, math.floor(f32(value * 255) + 0.5)))


@pytest.mark.parametrize("power", range(14))
@pytest.mark.parametrize("brake", range(9))
@pytest.mark.parametrize("symmetric", [False, True])
def test_pcsx2_profile_recovers_every_original_notch_byte(power, brake, symmetric):
    values = joystick_values(State(power=power, brake=brake), PROFILE)
    assert pcsx2_axis_byte(values[("abs", "ABS_X")], symmetric=symmetric) == POWER_CODES[power]
    assert pcsx2_axis_byte(values[("abs", "ABS_Y")], symmetric=symmetric) == BRAKE_CODES[brake]


def test_b7_and_emergency_are_different_axes_without_a_capture_button_chord():
    b7 = joystick_values(State(power=0, brake=7), PROFILE)
    eb = joystick_values(State(power=0, brake=8), PROFILE)
    assert b7[("abs", "ABS_Y")] != eb[("abs", "ABS_Y")]
    assert pcsx2_axis_byte(b7[("abs", "ABS_Y")]) == 0xDF
    assert pcsx2_axis_byte(eb[("abs", "ABS_Y")]) == 0xFB
    assert eb[("key", "BTN_7")] == 0


@pytest.mark.parametrize("axis,maximum,code", [("power", 13, "ABS_X"), ("brake", 8, "ABS_Y")])
def test_standard_pcsx2_gui_can_capture_full_sweeps_without_extra_buttons(axis, maximum, code):
    mapper = JoystickMapper(PROFILE)
    mapper.update(State(power=0, brake=0))
    events = []
    for notch in (*range(1, maximum + 1), *range(maximum - 1, -1, -1)):
        state = State(power=notch if axis == "power" else 0, brake=notch if axis == "brake" else 0)
        events.extend(mapper.update(state))
    assert all(event.kind == "abs" and event.code == code for event in events)
    # Released-positive, full-applied-negative travel is the range PCSX2's
    # binding capture recognizes as a full/inverted pedal-style axis.
    first = events[0].value * 2 / AXIS_MAX - 1
    minimum = min(event.value * 2 / AXIS_MAX - 1 for event in events)
    final = events[-1].value * 2 / AXIS_MAX - 1
    assert first > 0.5 and minimum < -0.5 and first - final <= 0.25


def test_generic_mapping_remains_unchanged():
    b7 = joystick_values(State(power=13, brake=7))
    eb = joystick_values(State(power=13, brake=8))
    assert b7[("abs", "ABS_X")] == AXIS_MAX
    assert b7[("abs", "ABS_Y")] == eb[("abs", "ABS_Y")] == AXIS_MAX
    assert b7[("key", "BTN_7")] == 0 and eb[("key", "BTN_7")] == 1


def test_pedal_routes_to_c_horn_without_releasing_a_held_c():
    mapper = JoystickMapper(PROFILE)
    mapper.update(State(power=0, brake=0))
    assert mapper.update(State(power=0, brake=0, pedal=True)) == [Event("key", "BTN_2", 1)]
    assert mapper.update(State(power=0, brake=0, buttons=frozenset({"c"}))) == []
    assert mapper.update(State(power=0, brake=0)) == [Event("key", "BTN_2", 0)]


def test_transition_packets_hold_the_last_emulated_notch_and_close_resets_semantically():
    state = decode(bytes.fromhex("fb fb ff 08 00 00"))
    mapper = JoystickMapper(PROFILE)
    mapper.update(state)
    assert mapper.update(decode(bytes.fromhex("ff ff ff 08 00 00"), state)) == []
    reset = {(event.kind, event.code): event.value for event in mapper.close()}
    assert pcsx2_axis_byte(reset[("abs", "ABS_X")]) == 0x12
    assert pcsx2_axis_byte(reset[("abs", "ABS_Y")]) == 0x1C
    assert mapper.close() == []


def test_wrong_half_axis_or_noninverted_binding_does_not_roundtrip_eb():
    value = joystick_values(State(power=0, brake=8), PROFILE)[("abs", "ABS_Y")]
    assert pcsx2_axis_byte(value) == 0xFB
    assert pcsx2_axis_byte(value, full=False) != 0xFB
    assert pcsx2_axis_byte(value, invert=False) != 0xFB


def test_daemon_uses_the_selected_profile_with_fresh_state(monkeypatch):
    stop = Stop()
    controller = MagicMock()

    def read(timeout):
        if controller.read.call_count == 1:
            return bytes.fromhex("fb 12 ff 08 00 00")
        stop.set()
        return None

    controller.read.side_effect = read
    output = MagicMock()
    daemon.serve_connection(controller, stop, lambda: output, joystick_profile=PROFILE)
    initial = {
        (event.kind, event.code): event.value for event in output.emit.call_args_list[0].args[0]
    }
    assert pcsx2_axis_byte(initial[("abs", "ABS_Y")]) == 0xFB
    assert initial[("key", "BTN_7")] == 0
    output.close.assert_called_once()


def test_daemon_loads_the_saved_profile_at_startup(monkeypatch):
    monkeypatch.setattr(settings, "load_profile", lambda: PROFILE)
    stop = Stop()
    controller = MagicMock()
    controller.__enter__.return_value = controller

    def read(timeout):
        if controller.read.call_count == 1:
            return bytes.fromhex("fb 12 ff 08 00 00")
        stop.set()
        return None

    controller.read.side_effect = read
    output = MagicMock()
    daemon.run(stop, controller_factory=lambda: controller, output_factory=lambda: output)
    values = {
        (event.kind, event.code): event.value for event in output.emit.call_args_list[0].args[0]
    }
    assert pcsx2_axis_byte(values[("abs", "ABS_Y")]) == 0xFB
    assert values[("key", "BTN_7")] == 0


@pytest.fixture
def config(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    return settings.settings_path()


def test_profile_selection_is_persistent_atomic_and_private(config):
    assert settings.load_profile() == "generic"
    assert settings.save_profile(PROFILE) == config
    assert settings.load_profile() == PROFILE
    assert config.stat().st_mode & 0o077 == 0
    assert not list(config.parent.glob(".settings-*"))
    settings.save_profile("generic")
    assert settings.load_profile() == "generic"


@pytest.mark.parametrize(
    "content", ["invalid", "[]", '{"unknown":"preserve"}', '{"joystick_profile":"not-real"}']
)
def test_bad_or_unfamiliar_settings_are_not_silently_discarded(config, content):
    config.parent.mkdir(parents=True)
    config.write_text(content)
    with pytest.raises(ValueError):
        settings.save_profile(PROFILE)
    assert config.read_text() == content


def test_symlinked_settings_can_be_read_but_not_overwritten(config, tmp_path):
    target = tmp_path / "managed.json"
    target.write_text(json.dumps({"joystick_profile": PROFILE}))
    config.parent.mkdir(parents=True)
    config.symlink_to(target)
    assert settings.load_profile() == PROFILE
    with pytest.raises(ValueError, match="symlink"):
        settings.save_profile("generic")
    assert json.loads(target.read_text())["joystick_profile"] == PROFILE


def test_profile_commands_do_not_touch_usb_or_emulator_files(config, monkeypatch, capsys):
    controller = MagicMock(side_effect=AssertionError("Must not claim USB"))
    monkeypatch.setattr(usb, "Controller", controller)
    assert cli.main(["profile", "set", PROFILE]) == 0
    assert "Restart" in capsys.readouterr().out
    assert cli.main(["profile", "show"]) == 0
    assert capsys.readouterr().out.strip() == PROFILE
    assert json.loads(config.read_text()) == {"joystick_profile": PROFILE}
    controller.assert_not_called()


def test_cli_refuses_a_joystick_profile_with_keyboard_output(capsys):
    assert cli.main(["bridge", "--output", "keyboard", "--joystick-profile", PROFILE]) == 1
    assert "cannot be used" in capsys.readouterr().err


def test_bridge_replay_can_override_the_saved_generic_profile(config, tmp_path, capsys):
    path = tmp_path / "sweep.jsonl"
    path.write_text('{"t":0,"raw":"1c 12 ff 08 00 00"}\n{"t":0,"raw":"fb 12 ff 08 00 00"}\n')
    assert (
        cli.main(["bridge", "--dry-run", "--replay", str(path), "--joystick-profile", PROFILE]) == 0
    )
    events = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    brake = [event["value"] for event in events if event["code"] == "ABS_Y"]
    assert [pcsx2_axis_byte(value) for value in brake] == [0x1C, 0xFB, 0x1C]
    assert not any(event["code"] == "BTN_7" and event["value"] == 1 for event in events)
    assert settings.load_profile() == "generic"  # One-run override does not persist.


def test_invalid_saved_profile_fails_before_daemon_usb_access(monkeypatch):
    monkeypatch.setattr(settings, "load_profile", MagicMock(side_effect=ValueError("Bad config")))
    controller = MagicMock()
    with pytest.raises(ValueError, match="Bad config"):
        daemon.run(Stop(), controller_factory=controller)
    controller.assert_not_called()
