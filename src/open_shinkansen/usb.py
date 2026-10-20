"""Small, exclusive PyUSB transport. Timeouts are normal for change-only reports."""

import sys
import warnings

from .protocol import PID, VID, Display


class DeviceError(RuntimeError):
    pass


class DeviceNotFound(DeviceError):
    """Normal hotplug state, distinct from an incompatible device or setup failure."""


def backend():
    import usb.backend.libusb1

    result = usb.backend.libusb1.get_backend()
    if result is None:
        import libusb_package

        result = libusb_package.get_libusb1_backend()
    if result is None:
        raise DeviceError("libusb is unavailable. Install libusb-1.0 (Linux) or libusb (Homebrew).")
    return result


class Controller:
    def __init__(self):
        self.device = None
        self.claimed = False
        self.detached = False
        self.endpoint = None

    def __enter__(self):
        import usb.core
        import usb.util

        try:
            devices = list(
                usb.core.find(idVendor=VID, idProduct=PID, find_all=True, backend=backend())
            )
            if not devices:
                raise DeviceNotFound("TCPP-20011 (0ae4:0005) not found. Check the USB cable/hub.")
            if len(devices) != 1:
                raise DeviceError(
                    "Multiple TCPP-20011 controllers found; connect only one for now."
                )
            self.device = devices[0]
            if sys.platform.startswith("linux") and self.device.is_kernel_driver_active(0):
                self.device.detach_kernel_driver(0)
                self.detached = True
            try:
                cfg = self.device.get_active_configuration()
            except usb.core.USBError as exc:
                # Only this PyUSB sentinel means unconfigured. Other errors must
                # propagate even when the backend did not populate errno.
                if exc.errno is not None or exc.strerror != "Configuration not set":
                    raise
                self.device.set_configuration(1)
                cfg = self.device.get_active_configuration()
            if cfg.bConfigurationValue != 1:
                raise DeviceError("Unexpected USB configuration; refusing to reset the device.")
            interface = cfg[(0, 0)]
            endpoint = usb.util.find_descriptor(interface, bEndpointAddress=0x81)
            if endpoint is None or endpoint.bmAttributes & 3 != 3 or endpoint.wMaxPacketSize != 8:
                raise DeviceError(
                    "Unexpected USB endpoint layout; expected interrupt IN 0x81/8 bytes."
                )
            usb.util.claim_interface(self.device, 0)
            self.claimed = True
            self.endpoint = endpoint
            return self
        except BaseException:
            self.close()
            raise

    def read(self, timeout_ms: int = 100):
        import usb.core

        try:
            return bytes(self.endpoint.read(8, timeout=timeout_ms))
        except usb.core.USBTimeoutError:
            return None

    def write_display(self, display: Display):
        payload = display.encode()
        count = self.device.ctrl_transfer(0x40, 0x09, 0x0301, 0, payload, timeout=1000)
        if count != len(payload):
            raise DeviceError(f"Short display write: {count}/{len(payload)} bytes")

    def describe(self) -> dict:
        import usb.util

        d = self.device
        return {
            "vendor_id": f"{d.idVendor:04x}",
            "product_id": f"{d.idProduct:04x}",
            "manufacturer": usb.util.get_string(d, d.iManufacturer),
            "product": usb.util.get_string(d, d.iProduct),
            "serial": usb.util.get_string(d, d.iSerialNumber),
            "usb_bcd": f"0x{d.bcdUSB:04x}",
            "endpoint": "0x81",
            "packet_size": self.endpoint.wMaxPacketSize,
            "interval_ms": self.endpoint.bInterval,
        }

    def close(self):
        import usb.core
        import usb.util

        if self.device is None:
            return
        try:
            if self.claimed:
                usb.util.release_interface(self.device, 0)
        except usb.core.USBError as exc:
            warnings.warn(f"Could not release USB interface: {exc}")
        finally:
            try:
                if self.detached:
                    self.device.attach_kernel_driver(0)
            except usb.core.USBError as exc:
                warnings.warn(f"Could not reattach kernel driver: {exc}")
            finally:
                usb.util.dispose_resources(self.device)
                self.device = None
                self.claimed = self.detached = False
                self.endpoint = None

    def __exit__(self, *args):
        self.close()
