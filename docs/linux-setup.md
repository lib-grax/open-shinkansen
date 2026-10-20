# Linux setup

This is the common setup for **systemd-based Linux distributions**. The bridge
is a normal user process; root is needed only for initial device permissions.
No distribution name, Steam installation, desktop environment or package manager
is selected by the driver. See [service management](background-service.md) for
normal operation after setup, and [optional platform notes](platform-notes.md)
for immutable systems, containers and host security policies.

## 1. Dependencies

Provide these capabilities using your host's supported administration tools:

- Python **3.9+**, `venv` and `pip`.
- A running systemd user manager (`systemctl --user`), plus `journalctl` for logs.
- udev (`udevadm`) and Linux kernel **uinput** support (built-in or a module).
- For initial group setup, either `getent`/`groupadd`/`usermod` or
  `systemd-sysusers`; the helper chooses the available implementation.
- Bash and standard `id`, `install` and `cmp` utilities for the setup helper.
- If uinput is not already present, `modprobe` and a working uinput module.

The installer never runs `apt`, `dnf`, `pacman`, `zypper` or another package
manager. Systemd alone cannot provide missing kernel features, USB passthrough,
Python build dependencies or permission overrides in a restricted container.

Create the Linux virtual environment in a stable project directory:

```sh
cd ~/Projects/open-shinkansen
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -e .
```

PyUSB, bundled libusb and evdev are installed in that environment. If wheels are
unavailable for the host's Python/architecture, supply a compiler, matching Python
development headers and Linux input headers before building evdev. A system
libusb 1.0 installation is an alternative to the bundled library. Do not copy a
virtual environment between operating systems or replace system Python.

## 2. One-time USB and virtual-input permissions

First run the helper's read-only preflight as the normal user. Then review and
run the same helper as an administrator, naming the intended normal account:

```sh
bash linux/setup-permissions.sh --check "$USER"
sudo bash linux/setup-permissions.sh "$USER"
```

Use an equivalent root administration method if sudo is not installed; it is not
a runtime dependency. The helper creates the opt-in `open-shinkansen` group,
adds the specified account, installs the two supplied udev rules, and configures
the existing uinput module to load at boot. It supports built-in uinput without
requiring `modprobe` when the device already exists. The preflight changes no
files, groups, kernel modules or permissions.

The rules grant configured group members access to:

- The physical controller, **USB `0ae4:0005` only**.
- `/dev/uinput`, for creating virtual input.
- The named **open-shinkansen Virtual Joystick** event node only, not arbitrary
  physical keyboards or the whole `/dev/input` tree.

No active graphical seat or `uaccess` ACL is required. Permissions work for local
desktop and non-graphical user-manager sessions alike. Do not use `chmod 666` on
USB, uinput or event devices.

**Security:** membership in this group permits arbitrary input injection through
`/dev/uinput`, not just train commands. Only add trusted users. Existing differing
host files are not overwritten. If upgrading from earlier ACL-only project rules,
review/update those two specific files manually before rerunning; do not overwrite
unfamiliar changes. An equivalent administrator-managed permission setup is also
possible; keep the same ownership/access restrictions.

**Fully log out/in or reboot** before continuing so both the login and systemd
user manager receive the new group membership. Then unplug/replug the controller.

## 3. Check and enable the background service

```sh
.venv/bin/open-shinkansen doctor
.venv/bin/open-shinkansen service install
.venv/bin/open-shinkansen service status
```

Run these commands **without sudo**. `doctor` is read-only and needs no controller
connected: it checks Python dependencies, a loadable libusb backend, access to the
systemd user manager, uinput access, current-session group membership, and installed
rule files. `doctor --json` produces machine-readable results. It does not claim
USB, create a virtual device or prove a game works; real hardware tests remain
necessary. Administrator-managed rules in other locations can require manual
verification even if `doctor` reports the supplied rule files as missing.

The service starts at user login, waits while no controller is connected, and
handles plug/unplug/reconnect automatically. It does not need an open terminal.
For explicitly configured headless boot operation, see the optional user-lingering
section in [background-service.md](background-service.md).

## 4. Manual verification

Stop the service before using another USB consumer:

```sh
.venv/bin/open-shinkansen service stop
.venv/bin/open-shinkansen discover
.venv/bin/open-shinkansen monitor
# Stop monitor with Ctrl-C, then test a manual virtual joystick if wanted:
.venv/bin/open-shinkansen bridge
```

The joystick rule marks the event device for joystick discovery and group access.
Test using `jstest-gtk`, `evtest` or an SDL joystick utility.
`/dev/input/js*` additionally requires `joydev` on systems using that legacy API;
SDL applications generally use `/dev/input/event*` instead.

An optional loopback test creates a real virtual joystick and checks that emitted
axis/button events can be read back (no USB controller or game is needed):

```sh
TRAIN_CONTROLLER_UINPUT_TEST=1 .venv/bin/python -m pytest tests/test_uinput_integration.py
```

This is skipped by default, including on macOS. It requires permission both to
create the uinput device and to read its new event node. SDL can report normalized
axes as −32768..32767 even though the raw evdev range is 0..32767; calibrate by
the physical lever endpoints rather than assuming the API's numeric range.

## Steam / Proton / Flatpak

- Start the bridge before opening the game's controller configuration.
- Bind both axes and emergency button explicitly. Do not assume XInput support.
- If native mappings conflict, try disabling Steam Input **for that game**.
- Flatpak bridges may require access to the virtual `/dev/input/event*` node.
  Review the app's device permissions; do not grant blanket filesystem/root
  permissions. USB ownership remains with this driver, not the simulator bridge.
- A second program (including OpenBVE's native USB plugin) cannot claim the
  controller at the same time. Use either native USB input or our bridge.
- On USB errors/unplug the manual `bridge` stops and releases output. The
  joystick-only `daemon`/user service releases and reconnects automatically.
  Relative keyboard mode still requires deliberate restart/re-synchronization.
- SIGKILL or power loss cannot run cleanup. Avoid forcibly killing keyboard
  mode; if a game retains input, refocus/release that key or restart the game.
