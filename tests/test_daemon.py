import logging
from threading import Event
from unittest.mock import MagicMock

import pytest
import usb.core

from open_shinkansen.daemon import AlreadyRunning, InstanceLock, run, serve_connection
from open_shinkansen.events import Event as InputEvent
from open_shinkansen.usb import DeviceError, DeviceNotFound

NEUTRAL = bytes.fromhex("1c 12 ff 08 00 00")
HELD = bytes.fromhex("38 24 00 01 08 00")


class Stop:
    """No real sleeps or polling in unit tests; every wait advances one attempt."""

    def __init__(self, attempts=1):
        self.stopped = False
        self.attempts = attempts
        self.waits = []

    def is_set(self):
        return self.stopped

    def set(self):
        self.stopped = True

    def wait(self, interval):
        self.waits.append(interval)
        if len(self.waits) >= self.attempts:
            self.set()
        return self.stopped


def source(rows, stop=None):
    controller = MagicMock()
    controller.__enter__.return_value = controller
    pending = iter(rows)

    def read(timeout):
        try:
            row = next(pending)
        except StopIteration:
            if stop is None:
                raise AssertionError("Unexpected extra read")
            stop.set()
            return None
        if isinstance(row, BaseException):
            raise row
        return row

    controller.read.side_effect = read
    return controller


def test_missing_controller_is_normal_and_not_logged_every_poll(caplog):
    stop = Stop(attempts=4)
    factory = MagicMock(side_effect=DeviceNotFound("Absent"))
    output = MagicMock()
    with caplog.at_level(logging.INFO):
        run(stop, controller_factory=factory, output_factory=output)
    assert factory.call_count == 4
    assert stop.waits == [1.0] * 4
    output.assert_not_called()
    assert caplog.text.count("Controller absent;") == 1


def test_idle_timeouts_do_not_disconnect_or_create_output():
    stop = Event()
    controller = source([None, None, bytes.fromhex("00 00 ff 08 00 00"), None], stop)
    output = MagicMock()
    serve_connection(controller, stop, output)
    output.assert_not_called()


def test_valid_state_creates_once_idle_keeps_it_and_shutdown_releases():
    stop = Event()
    controller = source([NEUTRAL, None, HELD, None, None], stop)
    factory = MagicMock()
    serve_connection(controller, stop, factory)
    factory.assert_called_once_with()
    factory.return_value.close.assert_called_once_with()
    batches = [call.args[0] for call in factory.return_value.emit.call_args_list]
    assert InputEvent("key", "BTN_0", 1) in batches[1]
    assert InputEvent("key", "BTN_6", 1) in batches[1]
    assert InputEvent("key", "BTN_0", 0) in batches[-1]
    assert InputEvent("key", "BTN_6", 0) in batches[-1]
    assert all(call.args == (100,) for call in controller.read.call_args_list)


def test_hot_unplug_removes_old_output_and_reconnect_gets_fresh_state():
    stop = Stop(attempts=10)
    first = source([HELD, usb.core.USBError("Unplugged", errno=19)])
    # Partial second reading must not inherit the previous power/brake/button state.
    second = source([bytes.fromhex("ff ff ff 08 00 00"), NEUTRAL], stop)
    factory = MagicMock(side_effect=[DeviceNotFound("Absent"), first, second])
    old_output, new_output = MagicMock(), MagicMock()
    outputs = MagicMock(side_effect=[old_output, new_output])
    run(stop, controller_factory=factory, output_factory=outputs)
    assert factory.call_count == 3
    assert outputs.call_count == 2
    old_output.close.assert_called_once()
    new_output.close.assert_called_once()
    assert InputEvent("key", "BTN_0", 0) in old_output.emit.call_args.args[0]
    assert InputEvent("key", "BTN_0", 0) in new_output.emit.call_args_list[0].args[0]
    first.__exit__.assert_called_once()
    second.__exit__.assert_called_once()


def test_uinput_permission_failure_is_fatal_not_retried():
    stop = Stop()
    controller = source([NEUTRAL])
    factory = MagicMock(return_value=controller)
    with pytest.raises(PermissionError):
        run(
            stop,
            controller_factory=factory,
            output_factory=MagicMock(side_effect=PermissionError("No uinput access")),
        )
    factory.assert_called_once()
    assert not stop.waits
    controller.__exit__.assert_called_once()


def test_invalid_device_layout_is_fatal():
    stop = Stop()
    with pytest.raises(DeviceError):
        run(stop, controller_factory=MagicMock(side_effect=DeviceError("Unexpected layout")))
    assert not stop.waits


def test_cleanup_still_closes_output_if_release_fails():
    stop = Event()
    controller = source([HELD], stop)
    output = MagicMock()
    output.emit.side_effect = [None, OSError("Device disappeared")]
    with pytest.raises(OSError):
        serve_connection(controller, stop, lambda: output)
    output.close.assert_called_once()


def test_repeated_usb_permission_errors_are_retried_without_log_spam(caplog):
    stop = Stop(attempts=4)
    factory = MagicMock(side_effect=usb.core.USBError("Access denied", errno=13))
    with caplog.at_level(logging.WARNING):
        run(stop, controller_factory=factory)
    assert factory.call_count == 4
    assert caplog.text.count("USB unavailable") == 1


@pytest.mark.parametrize("interval", [0, -1, 0.09, 61, float("nan"), float("inf")])
def test_poll_interval_bounds(interval):
    with pytest.raises(ValueError):
        run(Stop(), poll_interval=interval)


def test_lock_prevents_second_daemon_and_releases_on_exception(tmp_path):
    directory = tmp_path / "runtime"
    with pytest.raises(RuntimeError, match="forced"), InstanceLock(directory):
        with pytest.raises(AlreadyRunning), InstanceLock(directory):
            pass
        raise RuntimeError("forced")
    # Lock file is retained but the OS lock was released; no stale PID lockout.
    assert (directory / "daemon.lock").exists()
    with InstanceLock(directory):
        pass


def test_lock_rejects_symlink_and_world_accessible_directory(tmp_path):
    shared = tmp_path / "shared"
    shared.mkdir(mode=0o755)
    shared.chmod(0o755)
    with pytest.raises(RuntimeError, match="0700"), InstanceLock(shared):
        pass
    target = tmp_path / "private"
    target.mkdir(mode=0o700)
    link = tmp_path / "link"
    link.symlink_to(target, target_is_directory=True)
    with pytest.raises(RuntimeError), InstanceLock(link):
        pass
