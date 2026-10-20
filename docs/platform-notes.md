# Optional platform considerations

These are exceptions to the [common systemd Linux setup](linux-setup.md), not
separate driver variants. Runtime and service behavior are identical across
distributions; there is no OS-release or Steam-specific branch in the code.

## Immutable / declaratively managed systems

On immutable systems (including SteamOS-based devices), do not disable read-only
protection or replace system Python just to install this driver. `./setup.sh`
uses prebuilt input-library wheels on supported x86-64 CPython versions, including
3.13, to avoid the missing-kernel-header build error. Keep the project
and its Linux-created venv in a writable user directory. Use the OS's supported
approach for Python development dependencies if evdev needs to be built.

If `/etc` rules, group membership or module configuration are managed
declaratively, have the administrator express the supplied udev rules, opt-in
group membership and uinput module requirement in the host configuration instead
of running the imperative helper. The driver does not install distro-specific
configuration modules or change the host's update policy. `doctor` checks the
standard installed file paths; equivalent declarative permissions may need manual
verification.

After OS/Python upgrades, check device access and rebuild the venv if necessary.
An installed service references the venv's interpreter path; keep it in place.

## Containers, sandboxes and virtual machines

Having systemd inside a container is not sufficient. The process needs access to
the physical USB device, the host's uinput interface, and its virtual event device.
Host-side udev permissions and kernel support still apply. Do not solve this by
making all devices world-writable or running a fully privileged container.
For normal use, run the service directly on the Linux host.

A sandboxed game or simulator companion app may need permission to read the
virtual joystick. That application consumes `/dev/input/event*`, not the raw USB
controller. Keep its device permissions narrow. A VM needs USB passthrough and
guest kernel support before the ordinary setup can work.

## Headless / SSH sessions

The explicit `open-shinkansen` group permissions do not depend on a graphical
desktop, a logind seat or active-session ACLs. The systemd **user manager** must
still be reachable. If `systemctl --user` cannot connect, configure an appropriate
user session or deliberate lingering using the host's supported tools; do not
install the Python service as root. See [login versus boot](background-service.md#login-versus-boot).

## Host security policy

SELinux, AppArmor or device-cgroup policies may deny operations even when Unix
group permissions are correct. Review the host's audit logs and grant the minimum
required access using its supported policy mechanisms. The installer does not
disable security modules or write broad policy exceptions.

## Steam / Proton / alternate gaming sessions

Steam is optional and is not used to start or stop the driver. If present, avoid
duplicate Steam Input mappings on the external virtual joystick. A generic
joystick is not automatically an Xbox/XInput device. Game-specific bridges,
Proton compatibility and application autostart are separate from the USB driver.
Test game and session transitions on the actual host; no distribution-wide game
compatibility claim is made.
