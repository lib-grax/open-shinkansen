# Set-and-forget background service — systemd-based Linux

The deployment is a **systemd user service**, running as an ordinary user, not
root. It uses the same code and setup on systemd-based Linux distributions, with
no Steam, particular hardware platform, desktop environment or package-manager
dependency. The supported environment is defined by capabilities: Python 3.9+,
udev, kernel uinput, USB access and an available systemd user manager.

The unit is **`open-shinkansen.service`**. If upgrading from the earlier name,
follow [renaming.md](renaming.md) to avoid running two services or conflicting
device permission rules.

For ordinary installation, use **`./setup.sh`** in the cloned project. It performs
the setup described below, enabling the service without starting it prematurely
when a reboot is needed for group permissions. The manual commands here are for
troubleshooting or administrator-managed installations.

After one-time device permissions, installation and game calibration:

- Starts automatically when the configured user logs in.
- Sits quietly when there is no controller; checks USB once per second.
- Attaches on plug-in, waits for real handle readings, then creates the virtual joystick.
- Removes/releases the virtual joystick on USB errors/unplug and waits to reconnect.
- Starts each attachment with fresh input state, not cached buttons from last time.
- Treats idle input timeouts normally; no heartbeat is required.
- Cleans up on service stop, logout or SIGTERM. Unexpected failures are restarted
  by systemd after 10 seconds, with a start limit to prevent endless rapid crashes.
- Prevents a second daemon for the same user from starting.
- Never automatically injects keyboard input, activates rumble, changes displays,
  launches games, downloads mods or installs a root service.

**Still to validate on Linux hardware:** real uinput/joystick discovery,
suspend/resume, user-service lifecycle and game-specific integration.
The worker's plug/unplug/reconnect and cleanup paths have hardware-free tests.

## 1. Install the Linux copy

Place the project in a stable directory, for example `~/Projects/open-shinkansen`.
Create the venv on the Linux host: **do not copy a venv from another system**.
See [Linux setup](linux-setup.md) for the common setup and dependency checks.

```sh
cd ~/Projects/open-shinkansen
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -e .
```

No development dependencies are needed for ordinary use. Installation includes
PyUSB, bundled libusb and Linux input bindings. Supported x86-64 CPython versions
use prebuilt `evdev-binary` wheels (the import remains `evdev`); other platforms
can require source-build dependencies. See `linux-setup.md` for the exact selection.
Supply any required build tools using the host's supported administration tools; the
installer never selects a package manager, replaces system Python or disables
OS protections. See optional [platform notes](platform-notes.md) for exceptions.

Keep this project and venv in place after service installation. The unit records
the exact venv Python path. A future system Python upgrade can require rebuilding
the venv and reinstalling the service. Installing the Python package does not
change system device permissions.

## 2. One-time permissions (review before running)

The supplied script installs only these host changes:

- The two supplied `/etc/udev/rules.d/70-*.rules` files.
- The opt-in `open-shinkansen` group and membership for the named user.
- `/etc/modules-load.d/open-shinkansen.conf` to load the existing `uinput`
  module at boot.

**Security:** group membership permits arbitrary `/dev/uinput` input injection,
not just train commands. The rules do not grant read access to all physical
keyboards, do not use world-writable permissions and do not install a new kernel
module. USB access is restricted to `0ae4:0005`. Access to read input nodes is
restricted to this driver's named virtual joystick. Group permissions do not
require an active graphical seat, a desktop or logind `uaccess` ACLs.

From the project root, while logged in as the intended normal user:

```sh
bash linux/setup-permissions.sh --check "$USER"
sudo bash linux/setup-permissions.sh "$USER"
```

The script refuses to overwrite differing existing configuration, never installs
system packages and does not change OS read-only settings. It isn't a
transactional OS package manager: if a command fails, inspect the error before
rerunning. Existing matching rules can be reused.

**Reboot or fully log out and in before continuing**, so the user manager receives
the new group membership. Starting a new terminal alone may not be enough.
Then reconnect the USB controller. If you have already performed the equivalent
setup in `linux-setup.md`, you can reuse it; verify uinput module loading at boot.

## 3. Enable automatic startup — no sudo

```sh
cd ~/Projects/open-shinkansen
.venv/bin/open-shinkansen service install
.venv/bin/open-shinkansen service status
```

The automatic setup uses `service install --no-start` internally to enable the
unit for next login, then starts/restarts it only when current-session permissions
are ready. Manual installation can use that flag for the same deferred startup.

This writes `~/.config/systemd/user/open-shinkansen.service` (or the
corresponding `$XDG_CONFIG_HOME` path), reloads the user manager and runs
`systemctl --user enable --now`. **Do not run this as root.** No terminal window
or application launcher needs to remain open.

An existing differing unit is not silently overwritten. Review it, then use
`service install --replace` if you want it backed up and replaced. Moving to a
different venv path requires that explicit replacement. An already running service
can be refreshed with `service restart` after updating code/dependencies.

Start without the controller connected: the status should still be **active
(running)**. Plug it in; the logs should show **Virtual joystick ready**. If it was
already connected and hasn't sent an initial report, move a handle once.

### Login versus boot

By default the unit starts with the configured user's **login session**, not before
login. Systems with auto-login will start it automatically after boot.

For an intentionally headless or boot-without-login deployment, an administrator
can explicitly enable user lingering, where supported:

```sh
sudo loginctl enable-linger "$USER"
```

This keeps that user's systemd manager running without a login; it applies to all
of the user's enabled services, not only this driver. The group-based USB/uinput
rules work without an active seat. Run initial service management from a working
user-manager session, and verify boot behavior on the host. The installer **does
not** enable lingering, install a root boot daemon or configure passwordless sudo.

## Everyday use

The service loads the saved joystick profile at startup. `profile show` displays
it; `profile set generic` or `profile set pcsx2-shinkansen` changes the next-start
selection without editing systemd or emulator files. Run `service restart` to
apply, outside gameplay. `daemon --joystick-profile NAME` is a temporary override.
The one-command installer preserves this per-user preference across updates.

Plug in the controller and start a configured game. Nothing needs to be typed.
Bindings should be saved in the game or companion bridge; device name/capabilities
are stable, but `/dev/input/eventN` and SDL instance IDs can change on reconnect.
Never bind by a fixed event-node number. Some games/bridges only enumerate devices
at startup; in that case, **plug in before launching the game**. An app that lacks
hotplug support may need restarting after a disconnect even though this driver
reconnects automatically.

On disconnect the service releases inputs and removes the device; this is **not
a guarantee the game will stop/brake the train**. Game behavior on device removal
depends on the simulator. Reconnecting deliberately applies the current physical
handle positions once valid, which may differ from the game's current position.

If used, Steam Input and sandbox permissions still apply. This service exposes a
joystick, not an Xbox controller or a game-specific API. Running Train needs its own
saved profile and a compatible simulator bridge/mod; see `running-train.md`.
**Autostart of that external app is not installed or managed here.** A Python
background service alone cannot make an unconfigured game accept joystick axes.

## Diagnostics / maintenance

```sh
.venv/bin/open-shinkansen service logs
.venv/bin/open-shinkansen service restart
.venv/bin/open-shinkansen service stop
.venv/bin/open-shinkansen service start
```

Logs go to the systemd journal, not a growing project log file. Plain absence is
logged once per state change, not every poll. Busy/access-denied USB errors are
retried (useful for the brief udev permission race on plug-in); repeated identical
errors are not spammed. Use `open-shinkansen doctor` for read-only checks of
dependencies, the user-manager connection and configured permissions. It does
not claim USB or inject events, and does not require a connected controller.
Missing uinput access or invalid device layouts are not
hidden: the worker exits with an error and systemd applies its restart policy.
After fixing a persistent failure/start limit:

```sh
systemctl --user reset-failed open-shinkansen.service
.venv/bin/open-shinkansen service start
```

`discover`, `monitor` and manual `bridge` need exclusive USB access. **Stop the
service first** to use them, and start it again afterward. Do not start a native
USB plugin in another app while this service owns the controller.

For a foreground diagnostic without installing systemd:

```sh
.venv/bin/open-shinkansen daemon
```

`daemon --dry-run --duration 10` is also available on macOS and prints events
without injecting input. It still reads real USB; it is not a simulated source.
The hotplug delay can be changed with `--poll-interval` (0.1..60 seconds).

## Remove the background task

```sh
.venv/bin/open-shinkansen service uninstall
```

This stops/disables and removes this project's user unit only. It preserves the
source, captures, backups and host permission/group/module configuration. Remove
those host changes separately if no longer needed; do not remove a shared uinput
rule/group without checking for other applications. SIGKILL/power loss cannot run
Python cleanup; games can retain a stale command even when the virtual device has
gone away. Normal service stop is the supported shutdown path.
