from unittest.mock import MagicMock

import pytest
import usb.core
import usb.util

from open_shinkansen import usb as transport
from open_shinkansen.protocol import Display


@pytest.fixture
def fake(monkeypatch):
    device = MagicMock()
    cfg = MagicMock()
    cfg.bConfigurationValue = 1
    device.get_active_configuration.return_value = cfg
    device.is_kernel_driver_active.return_value = False
    endpoint = MagicMock()
    endpoint.bmAttributes = 3
    endpoint.wMaxPacketSize = 8
    monkeypatch.setattr(transport, "backend", lambda: None)
    monkeypatch.setattr(usb.core, "find", lambda **kw: iter([device]))
    monkeypatch.setattr(usb.util, "find_descriptor", lambda *a, **kw: endpoint)
    claim = MagicMock()
    release = MagicMock()
    dispose = MagicMock()
    monkeypatch.setattr(usb.util, "claim_interface", claim)
    monkeypatch.setattr(usb.util, "release_interface", release)
    monkeypatch.setattr(usb.util, "dispose_resources", dispose)
    return device, cfg, endpoint, claim, release, dispose


def test_open_close_does_not_reset_configured_device(fake):
    device, cfg, ep, claim, release, dispose = fake
    with transport.Controller() as controller:
        assert controller.device is device
        device.set_configuration.assert_not_called()
        claim.assert_called_once_with(device, 0)
    release.assert_called_once_with(device, 0)
    dispose.assert_called_once_with(device)


def test_permission_error_is_not_swallowed(fake):
    device, cfg, ep, claim, release, dispose = fake
    device.get_active_configuration.side_effect = usb.core.USBError("Access denied", errno=13)
    with pytest.raises(usb.core.USBError):
        with transport.Controller():
            pass
    device.set_configuration.assert_not_called()
    claim.assert_not_called()
    dispose.assert_called_once_with(device)


def test_unconfigured_device_is_configured_once(fake):
    device, cfg, ep, claim, release, dispose = fake
    device.get_active_configuration.side_effect = [usb.core.USBError("Configuration not set"), cfg]
    with transport.Controller():
        device.set_configuration.assert_called_once_with(1)


def test_backend_error_without_errno_is_not_mistaken_for_unconfigured(fake):
    device, cfg, ep, claim, release, dispose = fake
    device.get_active_configuration.side_effect = usb.core.USBError("Backend failure")
    with pytest.raises(usb.core.USBError), transport.Controller():
        pass
    device.set_configuration.assert_not_called()


def test_interrupt_during_claim_restores_detached_driver(fake, monkeypatch):
    device, cfg, ep, claim, release, dispose = fake
    monkeypatch.setattr(transport.sys, "platform", "linux")
    device.is_kernel_driver_active.return_value = True
    claim.side_effect = KeyboardInterrupt
    with pytest.raises(KeyboardInterrupt), transport.Controller():
        pass
    device.attach_kernel_driver.assert_called_once_with(0)
    dispose.assert_called_once_with(device)


def test_only_timeouts_are_ignored(fake):
    device, cfg, ep, claim, release, dispose = fake
    with transport.Controller() as controller:
        ep.read.side_effect = usb.core.USBTimeoutError("Timeout")
        assert controller.read() is None
        ep.read.side_effect = usb.core.USBError("Disconnected", errno=19)
        with pytest.raises(usb.core.USBError):
            controller.read()


def test_detached_kernel_driver_restored_on_claim_failure(fake, monkeypatch):
    device, cfg, ep, claim, release, dispose = fake
    monkeypatch.setattr(transport.sys, "platform", "linux")
    device.is_kernel_driver_active.return_value = True
    claim.side_effect = usb.core.USBError("Busy", errno=16)
    with pytest.raises(usb.core.USBError):
        with transport.Controller():
            pass
    device.detach_kernel_driver.assert_called_once_with(0)
    device.attach_kernel_driver.assert_called_once_with(0)
    release.assert_not_called()


def test_display_request_and_short_write(fake):
    device, cfg, ep, claim, release, dispose = fake
    with transport.Controller() as controller:
        device.ctrl_transfer.return_value = 8
        controller.write_display(Display(120, 160))
        device.ctrl_transfer.assert_called_once_with(
            0x40, 0x09, 0x0301, 0, Display(120, 160).encode(), timeout=1000
        )
        device.ctrl_transfer.return_value = 4
        with pytest.raises(transport.DeviceError, match="Short"):
            controller.write_display(Display())
