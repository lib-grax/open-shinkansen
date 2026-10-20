import json
import signal
from contextlib import nullcontext
from unittest.mock import MagicMock

import pytest

from open_shinkansen import daemon, service
from open_shinkansen.cli import main


@pytest.mark.parametrize("signum", [signal.SIGTERM, signal.SIGINT])
def test_signals_stop_daemon_cleanly_release_inputs_and_restore_handlers(
    monkeypatch, capsys, signum
):
    old_term, old_int = signal.getsignal(signal.SIGTERM), signal.getsignal(signal.SIGINT)
    monkeypatch.setattr(daemon, "InstanceLock", nullcontext)

    def fake_run(stop, **kwargs):
        controller = MagicMock()
        reads = 0

        def read(timeout):
            nonlocal reads
            reads += 1
            if reads == 1:
                return bytes.fromhex("38 24 00 01 08 00")
            signal.raise_signal(signum)
            return None

        controller.read.side_effect = read
        daemon.serve_connection(controller, stop, kwargs["output_factory"])
        assert stop.is_set()

    monkeypatch.setattr(daemon, "run", fake_run)
    assert main(["daemon", "--dry-run"]) == 0
    events = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert {"type": "key", "code": "BTN_0", "value": 1} in events
    assert {"type": "key", "code": "BTN_0", "value": 0} in events
    assert signal.getsignal(signal.SIGTERM) == old_term
    assert signal.getsignal(signal.SIGINT) == old_int


def test_daemon_duration_stops_wait_without_any_device(monkeypatch):
    monkeypatch.setattr(daemon, "InstanceLock", nullcontext)

    def fake_run(stop, **kwargs):
        assert stop.wait(2), "Diagnostic timer failed to stop the worker"

    monkeypatch.setattr(daemon, "run", fake_run)
    assert main(["daemon", "--dry-run", "--duration", "0.01"]) == 0


def test_daemon_does_not_offer_background_keyboard_profiles():
    with pytest.raises(SystemExit):
        main(["daemon", "--output", "keyboard"])
    with pytest.raises(SystemExit):
        main(["daemon", "--profile", "some-profile.json"])


def test_service_commands_dispatch_without_opening_usb(monkeypatch):
    manage = MagicMock()
    monkeypatch.setattr(service, "manage", manage)
    assert main(["service", "install", "--replace"]) == 0
    manage.assert_called_once_with("install", replace=True)
