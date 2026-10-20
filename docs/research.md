# Research and design rationale

Sources consulted on 2026-10-20. Protocol facts are implemented independently;
no upstream driver code has been copied into this project.

## Existing work

1. **[Train Controller Database: TCPP-20011](https://traincontrollerdb.marcriera.cat/hardware/tcpp20011)**
   documents IDs, missing HID report descriptor, six-byte input reports, discrete
   notch tables, `0xff` transitions, buttons/pedal, and the eight-byte vendor
   control transfer for speedometer/ATC/LEDs/rumble. Primary wire-format reference.
   Although the interface says HID, it supplies no proper HID report descriptor;
   standard HID/gamepad drivers cannot simply use it.
2. **[sogono/TCPP-20011-BRIDGE](https://github.com/sogono/TCPP-20011-BRIDGE)**
   implements this exact device with PyUSB on Windows and offers vJoy axes,
   sequential buttons, XInput pulses and keyboard modes. Confirms that a
   userspace translation layer is practical. vJoy/ViGEm are Windows-specific and
   are not the Linux solution; we use the kernel's existing uinput interface.
3. **[Adorkable/DenshaDeGo](https://github.com/Adorkable/DenshaDeGo)**
   is another existing USB interface, using LibUsbDotNet/C#.
4. **[PCSX2's train controller implementation](https://github.com/PCSX2/pcsx2/blob/master/pcsx2/USB/usb-pad/usb-train.cpp)**
   and [header](https://github.com/PCSX2/pcsx2/blob/master/pcsx2/USB/usb-pad/usb-train.h)
   emulate this device, corroborating its report layout and power/brake tables.
   Emulation is not a physical USB driver; no GPL source was copied.
5. **[TSW Controller App](https://github.com/LiahMartens/tsw-controller-app)**
   supports Linux and joystick input, using game-specific integration for Train
   Sim World and Train Simulator Classic and offering keyboard fallback. Its
   README documents current Proton/mod requirements. Best first integration
   target for this driver's standard virtual joystick; needs an end-to-end test.
6. **[Dovetail: TSW Raildriver and Joystick Interface](https://forums.dovetailgames.com/threads/ts-world-raildriver-and-joystick-interface.61440/)**
   illustrates why simply exposing a joystick does not guarantee TSW support:
   existing solutions bridge it through RailDriver-specific game interfaces.
7. **[Trenino](https://github.com/albertorestifo/trenino)** shows an alternative:
   direct TSW6 External Interface HTTP API integration. Promising for precise
   control and speed/display feedback, but train/API discovery and credentials
   must be handled separately. Not claimed as implemented here.
8. **[Train Controller Database: adapters/plugins](https://traincontrollerdb.marcriera.cat/adapters/)**
   describes OpenBVE's built-in train-controller plugins and DenConv (game memory
   patching). Native OpenBVE support may be sufficient without our virtual-device
   layer on some platforms; do not run two USB consumers simultaneously.
9. **[Linux uinput documentation](https://docs.kernel.org/input/uinput.html)**
   and **[python-evdev tutorial](https://python-evdev.readthedocs.io/en/latest/tutorial.html#injecting-input)**
   describe creating virtual devices without a custom kernel driver.

## Chosen architecture

```
TCPP-20011 -> libusb/PyUSB -> strict state decoder -> Linux uinput joystick
                                                -> optional uinput keyboard
                                                -> JSON monitoring/capture
```

The joystick preserves physical absolute lever positions. Separate emergency
button avoids compressing emergency into ordinary service braking. A simulator
bridge can handle per-locomotive notch ranges, combined handles and direct APIs.
Keyboard output is a fallback, not a claim of absolute synchronization.

USB/decoding is OS-independent. Linux virtual devices work below X11/Wayland and
can be consumed by SDL, native games and suitable Wine/Proton setups. Individual
games, Wine versions, Steam Input settings and Flatpak permissions may still
require configuration. No blanket compatibility claim is made.

## Hardware evidence versus assumptions

The attached device reports `TAITO_DENSYA_CON_T02`, serial `TCPP20011`, VID/PID
`0ae4:0005`, `bcdUSB=0x0110` and low-speed 1.5 Mbit/s operation, even though its
hub supports USB 2.0. Endpoint `0x81` has 8-byte max packets and 20ms interval.
Reports observed on this Mac are six bytes. An initial `00 00 ff 08 00 00` packet
precedes a valid notch reading; zero is not a valid notch code and is ignored.
Read timeouts occur without input changes; they are not proof of a disconnection.
The subsequent operator sweep captured 327 reports and confirmed every documented
power/brake position, all six buttons, four cardinal D-pad directions and pedal
pressed/released states. Diagonals remain reference-based, not hardware-verified.
Display speed 120, ATC 160 and the door lamp were visually confirmed, followed by
zero-valued displays on reset. See `hardware-testing.md` for exact coverage.

## Deferred work

- Actual Linux uinput/game validation and game-specific profile presets.
- Automatic speed/ATC/door feedback via a selected simulator's telemetry API.
- macOS virtual HID output (requires an OS-specific design, not just PyUSB).
- Optional GUI, combined-axis profiles and multiple-device selection.
- GUI/distribution packaging. A systemd user-service installer and joystick-only
  hotplug worker are now implemented; target-machine validation is still pending.
