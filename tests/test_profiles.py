from pathlib import Path

import pytest

from open_shinkansen.profiles import load, validate


def test_bundled_profiles_load():
    for path in (Path(__file__).parents[1] / "profiles").glob("*.json"):
        load(path)


@pytest.mark.parametrize(
    "data",
    [
        [],
        {"typo": 1},
        {"pulse_ms": True},
        {"gap_ms": 0},
        {"buttons": {"unrecognized": "KEY_A"}},
        {"buttons": {"a": "not-a-key"}},
        {"power": []},
        {"power": {"mode": "absolute", "keys": []}},
        {"power": {"mode": "relative", "steps": 0}},
        {"power": {"mode": "relative", "steps": 3, "increase": "KEY_A", "decrease": "KEY_A"}},
        {"power": {"mode": "disabled", "steps": 3}},
        {"power": {"mode": "invalid"}},
    ],
)
def test_invalid_profiles_rejected(data):
    with pytest.raises(ValueError):
        validate(data)


def test_defaults_are_disabled():
    assert validate({})["power"] == {"mode": "disabled"}
