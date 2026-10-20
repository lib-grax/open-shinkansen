# open-shinkansen

Linux-first **userspace USB driver and translation layer** for the **Taito
Densha de GO! Shinkansen PS2 controller (TCPP-20011, USB `0ae4:0005`)**.
No custom kernel module, firmware flashing, or Windows driver is needed.

The automatic service targets **systemd-based Linux distributions**, not a
particular computer, desktop environment or Steam installation. The same initial
setup and service commands apply wherever the documented prerequisites are met.

Renamed from the earlier project/command names. For existing Linux installations,
see [rename and migration notes](docs/renaming.md) before enabling the new service.

## What it does

- Reads all 14 power positions (N + P1–P13), brake release/B1–B7/emergency,
  A/B/C/D, Select/Start, D-pad and horn pedal.
- Exposes a **Linux virtual joystick**, with separate power/brake axes,
  D-pad and eight buttons. Recommended for accurate lever positioning.
- Optional **Linux virtual keyboard** with configurable held-notch keys or
  timed increase/decrease pulses. Works through uinput under X11 and Wayland.
- Live monitoring, JSONL recording/replay and event dry-runs on **Linux and macOS**.
- A **terminal ASCII dashboard** (`debug`) for testing handles, buttons, D-pad and
  pedal, including raw bytes, press counts and observed-notch coverage.
- Explicit, temporary speedometer/ATC/LED output; rumble stays off.
- Ignores transitional and unknown lever codes rather than turning them into
  accidental full power/braking. Waits for valid readings before output starts.
- Releases generated input on Ctrl-C, SIGTERM, end of replay, or USB errors.
- **Set-and-forget joystick service**: starts at user login, waits for plug-in,
  releases on unplug, and automatically reconnects. No background keystrokes.

### Status / limits

This is an initial implementation, not a universal game driver. On the connected
controller, a live Mac capture verified all power/brake notches, the six buttons,
cardinal D-pad directions and the horn pedal. Display speed/ATC/lamp output was
also visually confirmed. **Real Linux uinput, systemd deployment and in-game
integration still need Linux validation.** The local test environment is
macOS/Python 3.9; CI configuration includes Python 3.9 and 3.13 on Linux and macOS.
macOS currently supports USB I/O, monitoring, replay and dry-runs, **not** virtual
joystick/keyboard injection. No automatic game telemetry/display integration is
included. `daemon` automatically reconnects; the manual `bridge` command still
stops on USB errors and must be restarted. Idle input
timeouts are normal and are not treated as disconnects. The device sends reports
on changes; there is no guaranteed heartbeat for detecting a stalled connection.

The first requested game integration is **Running Train**; see
[its integration plan](docs/running-train.md). No in-game compatibility has yet
been validated.

## Recommended game compatibility approach

Use the virtual joystick for games supporting configurable joystick axes, such as
OpenBVE. For Train Sim World / Train Simulator Classic, **a generic joystick is
not sufficient in every version**: feed this virtual device into a game-specific
bridge such as [TSW Controller App](https://github.com/LiahMartens/tsw-controller-app),
which supports Linux and offers direct simulator integration. This combination is
an integration target, **not yet verified with this driver**. Check the bridge's
current game-version, mod and Proton requirements.

Use keyboard profiles as the compatibility fallback. Relative keystrokes are
inherently open-loop: train-specific notches, key timing, focus and in-game
changes can cause drift. Prefer axes/direct game APIs for exact control. See
[research and rationale](docs/research.md) for sources and alternatives.

## Install on systemd-based Linux

Prerequisites: **Python 3.9+** with venv/pip, **systemd user services**, **udev**,
kernel **uinput** support, and USB access. No Steam, graphical desktop, distribution
detection or particular package manager is required. The runtime uses PyUSB,
libusb and Linux evdev. Follow [the common Linux setup](docs/linux-setup.md) once:

```sh
cd ~/Projects/open-shinkansen
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -e .
bash linux/setup-permissions.sh --check "$USER"
sudo bash linux/setup-permissions.sh "$USER"
```

Fully log out/in (or reboot) for group membership, and reconnect the controller.
Then, as the normal user, **without sudo**:

```sh
.venv/bin/open-shinkansen doctor
.venv/bin/open-shinkansen service install
```

After setup the service runs in the background and handles plug/unplug/reconnect.
It starts with the user's login; optional boot-without-login operation is described
in [service lifecycle](docs/background-service.md). SteamOS, immutable systems,
containers and security-policy considerations are isolated in
[optional platform notes](docs/platform-notes.md).

### Manual monitoring / macOS development

Create/install the venv as above (add `'.[dev]'` for tests/lint), but skip the Linux
permission/service steps on macOS. Bundled libusb normally suffices; Homebrew
`libusb` is an alternative. For manual commands, stop any running service first:

```sh
.venv/bin/open-shinkansen discover
.venv/bin/open-shinkansen monitor
.venv/bin/open-shinkansen monitor --json --duration 30 --record captures/session.jsonl
```

Capture paths must be new files; existing captures are never overwritten. You can
also use `.venv/bin/python -m open_shinkansen` instead of the installed command.

### ASCII controller test (macOS and Linux)

```sh
cd ~/Projects/open-shinkansen
.venv/bin/open-shinkansen debug
```

This opens a live terminal dashboard, with no keyboard/joystick injection and no
display or rumble commands. Sweep the handles and press the controls: `*` means
active, `+` means observed during this run, and `.` means inactive/not yet observed.
Press **Ctrl-C** to stop; the terminal is restored and a coverage summary remains.
Use a terminal about **80 columns x 24 rows** for the full view.

```sh
.venv/bin/open-shinkansen debug --duration 90 --record captures/debug-session.jsonl
.venv/bin/open-shinkansen debug --replay tests/fixtures/demo.jsonl
```

`--plain` disables in-place screen updates; redirected output and `TERM=dumb`
automatically use plain snapshots. Stop any background USB consumer first.
See [the debug guide](docs/debug.md) for the checklist and counter meanings.

### Linux virtual joystick (recommended)

For normal use, install the [background service](docs/background-service.md)
once. It starts at user login (including auto-login), handles controller
plug/unplug/reconnect, and needs no open terminal:

```sh
# On the Linux machine, after the one-time permissions/reboot setup:
.venv/bin/open-shinkansen service install
.venv/bin/open-shinkansen service status
```

For a foreground hotplug worker instead, run `open-shinkansen daemon`. Automatic
mode is intentionally joystick-only; keyboard profiles remain opt-in foreground
commands. The service does not install/autostart Running Train's external bridge.

For a one-off foreground session without reconnect:

```sh
open-shinkansen bridge
```

Configure the device named **open-shinkansen Virtual Joystick** in your game or
joystick-to-simulator bridge:

Stop the background service first if using `bridge`, `monitor` or `discover`;
these also require exclusive USB access. Restart it afterward with `service start`.

| Input | Output |
| --- | --- |
| Power N–P13 | X axis, 0–32767 |
| Brake released–B7 | Y axis, 0–32767 |
| Emergency | Full Y axis **and** button 8 |
| A, B, C, D | Buttons 1–4 |
| Select, Start | Buttons 5–6 |
| Horn pedal | Button 7 |
| D-pad | Hat X/Y, each −1/0/+1 |

Emergency is deliberately separate from service braking. Bind button 8 to the
game's emergency action. Some tools number buttons from zero (A=0, emergency=7).
There is no train-specific combined-handle axis; combine the independent axes in
your game's bridge if needed. The driver does not suppress simultaneous brake and
power; train interlocks are the simulator's responsibility.

### Keyboard fallback

**Inspect a dry-run first. Generated keys go to whichever application has focus.**
Both bundled profiles are examples, not tested game presets. Copy one and edit it
for your game/locomotive; use Linux `KEY_*` names. See [profile details](docs/profiles.md).

```sh
open-shinkansen bridge --output keyboard --profile profiles/relative-template.json --dry-run
open-shinkansen bridge --output keyboard --profile profiles/relative-template.json
```

Relative mode emits scaled notch-change pulses, including every step of a large
jump. On startup, it sends **no** lever keystrokes: first synchronize both the
in-game and physical controls (usually zero power/released brake), then start the
bridge. To re-synchronize, stop, match the game to the handles, and restart.
The example relative brake's eight steps include emergency only if the game does;
configure an explicit `emergency` button binding if your game uses a separate key.

### Hardware-free tests and replay

```sh
.venv/bin/python -m pip install -e '.[dev]'
source .venv/bin/activate
python -m pytest
open-shinkansen monitor --replay tests/fixtures/demo.jsonl
open-shinkansen bridge --replay tests/fixtures/demo.jsonl --dry-run
open-shinkansen bridge --output keyboard --profile profiles/relative-template.json --replay tests/fixtures/demo.jsonl --dry-run
```

`--replay` alone **does not disable injection**. Use `--dry-run` to avoid creating
a virtual device. A live dry-run still opens and reads the USB controller.

### Display test (explicit output only)

```sh
open-shinkansen display --speed 120 --limit 160 --door --hold 3
```

Sets the display for three seconds, then clears it even on normal interruption.
Resetting the numeric displays means showing **0 / 0**, not blank digits.
No rumble motors are activated. Automatic feedback from games is not implemented;
the `Display` class / `Controller.write_display()` API can support that later.

## Hardware validation

See [docs/hardware-testing.md](docs/hardware-testing.md) for a lever/button/pedal
checklist and capture workflow. Tested cases and raw observed reports are recorded
there separately from inferred protocol behavior.

## Layout

`src/open_shinkansen/`: protocol, USB transport, event mappers, uinput and CLI.
`profiles/`: editable JSON examples. `linux/`: narrowly scoped permission rules.
`tests/`: hardware-free tests and a synthetic replay. `captures/`: ignored local logs.
