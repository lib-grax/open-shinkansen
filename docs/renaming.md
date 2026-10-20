# Project rename: open-shinkansen

The project is now **open-shinkansen** throughout:

| Component | Name |
| --- | --- |
| Project directory | `~/Projects/open-shinkansen` |
| Python distribution / executable | `open-shinkansen` |
| Python import / module entry point | `open_shinkansen` |
| systemd user unit | `open-shinkansen.service` |
| Device-access group / runtime directory | `open-shinkansen` |
| Virtual joystick | `open-shinkansen Virtual Joystick` |
| Virtual keyboard (manual only) | `open-shinkansen Virtual Keyboard` |
| udev rules | `70-open-shinkansen.rules`, `70-open-shinkansen-uinput.rules` |
| Module-load configuration | `open-shinkansen.conf` |

The physical Taito VID/PID, protocol, captures and profile formats are unchanged.
Upstream project names and links in the research/game documentation are not renamed.

## Local Mac project

The original project folder was moved, keeping captures and other files in place.
A fresh venv was built at the new path because executable scripts and editable
installs embed absolute paths. The previous venv and generated metadata/caches
were preserved in the ignored `.rename-backup/` directory, not discarded.

Use the renamed executable, not scripts in that old backup:

```sh
cd ~/Projects/open-shinkansen
.venv/bin/open-shinkansen debug
```

## Previously installed Linux versions only

Fresh installations follow [linux-setup.md](linux-setup.md) and need no migration.
The source-tree rename does **not** alter an installed Linux service, root-owned
udev files, group memberships or saved game calibration.

If the old service was installed, stop and disable it **on that Linux host** before
enabling the new service:

```sh
systemctl --user disable --now taito-train-controller.service
```

Do not run the old and new services against the same physical controller.
Retain/review the old unit file and any local edits rather than deleting it blindly.

Review and back up the earlier udev files, if present:

- `/etc/udev/rules.d/70-taito-train-controller.rules`
- `/etc/udev/rules.d/70-train-controller-uinput.rules`

Move reviewed legacy rules out of the active udev rule directory before running
the renamed permission helper. They refer to the old `train-controller` group and
can override the new rules. The helper deliberately refuses this overlap and
does not remove or overwrite those files automatically. The old module-load file
only requests the same `uinput` module; review it separately if cleaning up.

Create/reinstall the Linux venv at the new project path, run the renamed permission
setup, fully log out/in or reboot, reconnect USB, then enable the new service:

```sh
.venv/bin/open-shinkansen doctor
.venv/bin/open-shinkansen service install
```

The virtual device's name has changed. Games and companion apps may identify it
as a new joystick: reselect/recalibrate the named device and save its bindings.
Old permission-group membership is not removed automatically; an administrator
can review it after migration.
