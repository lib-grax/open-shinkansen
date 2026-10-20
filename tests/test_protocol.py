import pytest

from open_shinkansen.protocol import (
    BRAKE_CODES,
    BUTTON_BITS,
    HATS,
    POWER_CODES,
    Display,
    State,
    bcd,
    decode,
)


def report(brake=0x1C, power=0x12, pedal=0xFF, hat=8, buttons=0):
    return bytes([brake, power, pedal, hat, buttons, 0])


@pytest.mark.parametrize("brake,code", enumerate(BRAKE_CODES))
@pytest.mark.parametrize("power,pcode", enumerate(POWER_CODES))
def test_all_notch_combinations(brake, code, power, pcode):
    state = decode(report(brake=code, power=pcode))
    assert state.brake == brake
    assert state.power == power
    assert state.ready
    assert state.emergency == (brake == 8)


def test_unknown_codes_preserve_previous_instead_of_rounding():
    old = State(power=3, brake=2)
    for code in range(256):
        state = decode(report(power=code, brake=code), old)
        assert state.power == (POWER_CODES.index(code) if code in POWER_CODES else 3)
        assert state.brake == (BRAKE_CODES.index(code) if code in BRAKE_CODES else 2)


def test_unknown_startup_has_no_invented_neutral():
    initial = decode(bytes.fromhex("00 00 ff 08 00 00"))
    assert not initial.ready
    assert initial.power is initial.brake is None
    partial = decode(report(power=0xFF), initial)
    assert partial.brake == 0 and partial.power is None
    assert decode(report(), partial).ready


@pytest.mark.parametrize("name,mask", BUTTON_BITS.items())
def test_buttons_active_high(name, mask):
    assert decode(report(buttons=mask)).buttons == frozenset({name})


@pytest.mark.parametrize("hat,xy", enumerate(HATS))
def test_hat(hat, xy):
    state = decode(report(hat=hat))
    x, y = xy
    expected = set()
    if x:
        expected.add("right" if x > 0 else "left")
    if y:
        expected.add("down" if y > 0 else "up")
    assert state.controls == expected


def test_pedal_transition_and_padding():
    assert decode(report(pedal=0)).pedal
    assert not decode(report()).pedal
    assert decode(report() + b"\0\0") == decode(report())
    assert decode(report(hat=0xFF), State(hat=4)).hat == 4


@pytest.mark.parametrize("length", [0, 1, 5, 7, 9, 16])
def test_bad_length(length):
    with pytest.raises(ValueError):
        decode(bytes(length))


def test_display_bcd_and_motors_off():
    assert bcd(120) == b"\x20\x01"
    assert bcd(999) == b"\x99\x09"
    assert Display(120, 160, True, 10).encode() == bytes.fromhex("00 00 8a 08 20 01 60 01")
    assert Display().encode() == bytes(8)
    assert Display(999).encode()[3] == 22
    assert Display(1).encode()[3] == 1
    assert Display(15).encode()[3] == 1
    assert Display(16).encode()[3] == 2


@pytest.mark.parametrize(
    "kwargs",
    [
        {"speed": -1},
        {"speed": 1000},
        {"limit": 1000},
        {"speed": 1.5},
        {"speed": True},
        {"approach": 11},
        {"gauge": 23},
        {"gauge": -1},
    ],
)
def test_display_rejects_out_of_range(kwargs):
    with pytest.raises(ValueError):
        Display(**kwargs).encode()
