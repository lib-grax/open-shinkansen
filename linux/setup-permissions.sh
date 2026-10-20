#!/usr/bin/env bash
# Run explicitly once as root; the driver itself must remain unprivileged.
set -euo pipefail

check_only=false
if [[ "${1:-}" == --check ]]; then
    check_only=true
    shift
fi
if [[ "$(uname -s)" != Linux || "$#" -ne 1 ]]; then
    echo 'Usage, on Linux: sudo bash linux/setup-permissions.sh "$USER"' >&2
    echo 'Read-only preflight: bash linux/setup-permissions.sh --check "$USER"' >&2
    exit 1
fi
if [[ "$check_only" == false && "$EUID" -ne 0 ]]; then
    echo 'Permission setup needs administrator privileges; use sudo or an equivalent root session.' >&2
    exit 1
fi

target_user="$1"
target_uid="$(id -u -- "$target_user")"
if [[ "$target_uid" -eq 0 ]]; then
    echo 'Choose the normal controller-user account, not root.' >&2
    exit 1
fi

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
for name in 70-open-shinkansen.rules 70-open-shinkansen-uinput.rules open-shinkansen.conf; do
    if [[ ! -f "$script_dir/$name" || ! -r "$script_dir/$name" ]]; then
        echo "Missing setup asset: $script_dir/$name. Use the complete project, not just this helper." >&2
        exit 1
    fi
done
for command in systemctl udevadm install cmp; do
    if ! command -v "$command" >/dev/null; then
        echo "Missing host command: $command. No automatic system-package changes will be made." >&2
        exit 1
    fi
done
if command -v getent >/dev/null && command -v groupadd >/dev/null && command -v usermod >/dev/null; then
    account_tools=shadow
elif command -v systemd-sysusers >/dev/null; then
    account_tools=sysusers
    # The --inline syntax must not interpret a username as extra configuration.
    if [[ ! "$target_user" =~ ^[a-zA-Z_][a-zA-Z0-9_.-]*\$?$ ]]; then
        echo 'This account name needs manual group setup; see docs/linux-setup.md.' >&2
        exit 1
    fi
else
    echo 'Need groupadd/usermod or systemd-sysusers for initial group setup; no package manager is assumed.' >&2
    exit 1
fi
if [[ ! -c /dev/uinput ]] && ! command -v modprobe >/dev/null; then
    echo 'The uinput device is absent and modprobe is unavailable. Enable kernel uinput support first.' >&2
    exit 1
fi

# Preflight all destinations before changing groups or files. Never overwrite
# unfamiliar host configuration (including a locally modified previous rule).
# Legacy rules can override the renamed group's permissions later in udev order.
# Refuse overlap rather than silently removing administrator configuration.
for name in 70-taito-train-controller.rules 70-train-controller-uinput.rules; do
    legacy="/etc/udev/rules.d/$name"
    if [[ -e "$legacy" || -L "$legacy" ]]; then
        echo "Legacy permission rules require migration: $legacy. See docs/renaming.md; nothing was changed." >&2
        exit 1
    fi
done
for name in 70-open-shinkansen.rules 70-open-shinkansen-uinput.rules; do
    destination="/etc/udev/rules.d/$name"
    if [[ -L "$destination" ]] || { [[ -e "$destination" ]] && ! cmp -s -- "$script_dir/$name" "$destination"; }; then
        echo "Existing configuration differs or is a symlink; review it manually: $destination" >&2
        exit 1
    fi
done
module_destination=/etc/modules-load.d/open-shinkansen.conf
if [[ -L "$module_destination" ]] || { [[ -e "$module_destination" ]] && ! cmp -s -- "$script_dir/open-shinkansen.conf" "$module_destination"; }; then
    echo "Existing configuration differs or is a symlink; review it manually: $module_destination" >&2
    exit 1
fi

if [[ "$check_only" == true ]]; then
    echo "Setup preflight passed (account tools: $account_tools). No files, groups, permissions or kernel modules changed."
    exit 0
fi

echo "Granting $target_user access to this USB controller and opt-in /dev/uinput injection."
echo 'SECURITY: the open-shinkansen group can inject arbitrary keyboard/mouse input.'
echo 'The background service uses only joystick output; it is NOT installed as root.'

# Support both built-in uinput and loadable modules. Never unload a working module.
if [[ ! -c /dev/uinput ]]; then
    modprobe uinput
fi
if [[ "$account_tools" == shadow ]]; then
    if ! getent group open-shinkansen >/dev/null; then
        groupadd open-shinkansen
    fi
    usermod -aG open-shinkansen -- "$target_user"
else
    systemd-sysusers --inline 'g open-shinkansen -' "m $target_user open-shinkansen"
fi
install -d -m 0755 /etc/udev/rules.d /etc/modules-load.d
install -m 0644 "$script_dir/70-open-shinkansen.rules" /etc/udev/rules.d/
install -m 0644 "$script_dir/70-open-shinkansen-uinput.rules" /etc/udev/rules.d/
install -m 0644 "$script_dir/open-shinkansen.conf" "$module_destination"
udevadm control --reload-rules
udevadm trigger --subsystem-match=misc --sysname-match=uinput
udevadm trigger --subsystem-match=usb --attr-match=idVendor=0ae4 --attr-match=idProduct=0005
udevadm settle --timeout=10
echo 'Permission rules installed. New group membership requires a reboot or full logout/login.'
echo 'Do not run the Python service installer using sudo.'
