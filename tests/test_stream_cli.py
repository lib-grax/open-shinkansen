import json
from pathlib import Path

import pytest

from open_shinkansen.cli import main
from open_shinkansen.stream import recorder, replay_records

FIXTURE = Path(__file__).parent / "fixtures" / "demo.jsonl"


def test_capture_roundtrip_and_no_overwrite(tmp_path):
    path = tmp_path / "session.jsonl"
    raw = bytes.fromhex("1c 12 ff 08 00 00")
    with recorder(path) as record:
        record(0, raw)
        record(0.1, None)
        record(0.2, raw)
    assert list(replay_records(path)) == [(0, raw), (0.2, raw)]
    with pytest.raises(FileExistsError):
        with recorder(path):
            pass


@pytest.mark.parametrize(
    "text",
    [
        "{}",
        '{"t": -1, "raw": "000000000000"}',
        '{"t": NaN, "raw": "000000000000"}',
        '{"t": true, "raw": "000000000000"}',
        '{"t": 0, "raw": "ff"}',
        '{"t": 0, "raw": "zz"}',
        '{"t": 1, "raw": "000000000000"}\n{"t": 0, "raw": "000000000000"}',
    ],
)
def test_malformed_capture(tmp_path, text):
    path = tmp_path / "bad.jsonl"
    path.write_text(text)
    with pytest.raises(ValueError, match="line"):
        list(replay_records(path))


def test_monitor_replay_no_usb(capsys):
    assert main(["monitor", "--json", "--replay", str(FIXTURE), "--duration", "0.05"]) == 0
    lines = capsys.readouterr().out.splitlines()
    assert json.loads(lines[0])["ready"]


def test_bridge_dry_run_releases_on_completion(capsys):
    assert main(["bridge", "--dry-run", "--replay", str(FIXTURE)]) == 0
    events = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    values = {}
    for event in events:
        values[event["code"]] = event["value"]
    assert all(value == 0 for value in values.values())


def test_keyboard_requires_profile(capsys):
    assert main(["bridge", "--output", "keyboard", "--dry-run"]) == 1
    assert "requires --profile" in capsys.readouterr().err


def test_bad_capture_releases_keys(tmp_path, capsys):
    path = tmp_path / "bad.jsonl"
    path.write_text('{"t": 0, "raw": "1c 12 ff 08 08 00"}\ninvalid')
    assert main(["bridge", "--dry-run", "--replay", str(path)]) == 1
    events = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert {"type": "key", "code": "BTN_0", "value": 1} in events
    assert {"type": "key", "code": "BTN_0", "value": 0} in events


@pytest.mark.parametrize("duration", ["0", "-1", "nan", "inf"])
def test_invalid_duration(duration):
    with pytest.raises(SystemExit):
        main(["monitor", "--duration", duration])
