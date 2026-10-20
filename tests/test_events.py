from open_shinkansen.events import AXIS_MAX, Event, JoystickMapper, KeyboardMapper
from open_shinkansen.profiles import validate
from open_shinkansen.protocol import State


def profile(**updates):
    data = {
        "pulse_ms": 50,
        "gap_ms": 50,
        "power": {"mode": "relative", "steps": 13, "increase": "KEY_A", "decrease": "KEY_D"},
        "brake": {"mode": "relative", "steps": 8, "increase": "KEY_DOT", "decrease": "KEY_COMMA"},
        "buttons": {"a": "KEY_SPACE", "pedal": "KEY_SPACE"},
    }
    data.update(updates)
    return validate(data)


def test_joystick_waits_for_known_notches_and_suppresses_duplicates():
    mapper = JoystickMapper()
    assert mapper.update(State()) == []
    assert mapper.update(State(power=0)) == []
    first = mapper.update(State(power=0, brake=0))
    assert len(first) == 12  # 4 axes + 8 buttons, explicitly initialized
    assert mapper.update(State(power=0, brake=0)) == []
    assert mapper.update(State(power=13, brake=7)) == [
        Event("abs", "ABS_X", AXIS_MAX),
        Event("abs", "ABS_Y", AXIS_MAX),
    ]
    assert mapper.update(State(power=13, brake=8)) == [Event("key", "BTN_7", 1)]
    assert Event("key", "BTN_7", 0) in mapper.close()
    assert mapper.close() == []


def test_joystick_buttons_and_diagonal_hat():
    events = JoystickMapper().update(
        State(power=0, brake=0, hat=7, pedal=True, buttons=frozenset({"a", "start"}))
    )
    for event in [
        Event("abs", "ABS_HAT0X", -1),
        Event("abs", "ABS_HAT0Y", -1),
        Event("key", "BTN_0", 1),
        Event("key", "BTN_5", 1),
        Event("key", "BTN_6", 1),
    ]:
        assert event in events


def test_relative_large_jump_emits_all_steps_and_does_not_repeat_at_rest():
    mapper = KeyboardMapper(profile())
    mapper.update(State(power=0, brake=0))
    assert mapper.tick(0) == []
    mapper.update(State(power=13, brake=0))
    events = []
    for i in range(1000):
        events += mapper.tick(i / 100)
    assert sum(e.code == "KEY_A" and e.value == 1 for e in events) == 13
    assert sum(e.code == "KEY_A" and e.value == 0 for e in events) == 13
    assert mapper.tick(100) == []


def test_new_target_cancels_obsolete_pulses():
    mapper = KeyboardMapper(profile())
    mapper.update(State(power=0, brake=0))
    mapper.update(State(power=13, brake=0))
    assert mapper.tick(0) == [Event("key", "KEY_A", 1)]
    mapper.update(State(power=0, brake=0))
    assert mapper.tick(0.06) == [Event("key", "KEY_A", 0)]
    assert mapper.tick(0.12) == [Event("key", "KEY_D", 1)]
    assert mapper.tick(0.18) == [Event("key", "KEY_D", 0)]
    assert mapper.tick(0.24) == []


def test_shared_held_key_not_released_prematurely():
    mapper = KeyboardMapper(profile())
    mapper.update(State(power=0, brake=0, pedal=True, buttons=frozenset({"a"})))
    assert mapper.tick(0) == [Event("key", "KEY_SPACE", 1)]
    mapper.update(State(power=0, brake=0, pedal=True))
    assert mapper.tick(0.1) == []
    mapper.update(State(power=0, brake=0))
    assert mapper.tick(0.2) == [Event("key", "KEY_SPACE", 0)]


def test_held_pulse_overlap_never_double_releases():
    mapper = KeyboardMapper(profile(buttons={"a": "KEY_A"}))
    mapper.update(State(power=0, brake=0))
    mapper.update(State(power=1, brake=0))
    assert mapper.tick(0) == [Event("key", "KEY_A", 1)]
    mapper.update(State(power=1, brake=0, buttons=frozenset({"a"})))
    assert mapper.tick(0.02) == []
    mapper.update(State(power=1, brake=0))
    assert mapper.tick(0.06) == [Event("key", "KEY_A", 0)]
    assert mapper.close() == []


def test_close_releases_everything_and_cancels_pending_steps():
    mapper = KeyboardMapper(profile())
    mapper.update(State(power=0, brake=0, pedal=True))
    mapper.update(State(power=13, brake=8, pedal=True))
    down = mapper.tick(0)
    assert Event("key", "KEY_SPACE", 1) in down
    assert set(mapper.close()) == {Event("key", e.code, 0) for e in down}
    assert mapper.tick(20) == []


def test_pending_pulse_waits_for_shared_held_key_release_and_gap():
    mapper = KeyboardMapper(profile(buttons={"a": "KEY_A"}))
    mapper.update(State(power=0, brake=0, buttons=frozenset({"a"})))
    assert mapper.tick(0) == [Event("key", "KEY_A", 1)]
    mapper.update(State(power=1, brake=0, buttons=frozenset({"a"})))
    assert mapper.tick(0.02) == []
    assert mapper.positions["power"] == 0
    mapper.update(State(power=1, brake=0))
    assert mapper.tick(0.03) == [Event("key", "KEY_A", 0)]
    assert mapper.tick(0.06) == []
    assert mapper.tick(0.09) == [Event("key", "KEY_A", 1)]
    assert mapper.positions["power"] == 1


def test_relative_axes_are_fair_and_first_position_is_baseline():
    mapper = KeyboardMapper(profile())
    mapper.update(State(power=5, brake=5))
    assert mapper.tick(0) == []
    mapper.update(State(power=13, brake=8))
    assert mapper.tick(0) == [Event("key", "KEY_A", 1)]
    mapper.tick(0.06)
    assert mapper.tick(0.12) == [Event("key", "KEY_DOT", 1)]


def test_absolute_keys_change_without_spurious_pulses():
    mapper = KeyboardMapper(
        profile(power={"mode": "absolute", "keys": [None, "KEY_F1", "KEY_F2"] + [None] * 11})
    )
    mapper.update(State(power=1, brake=0))
    assert mapper.tick(0) == [Event("key", "KEY_F1", 1)]
    mapper.update(State(power=2, brake=0))
    assert mapper.tick(0.01) == [Event("key", "KEY_F1", 0), Event("key", "KEY_F2", 1)]
    assert mapper.close() == [Event("key", "KEY_F2", 0)]
