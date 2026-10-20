#!/usr/bin/env bash
# Run as your normal user. Only the device-permission step requests admin access.
set -euo pipefail

project_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
if ! command -v python3 >/dev/null; then
    echo 'open-shinkansen needs Python 3.9 or newer, with venv/pip support.' >&2
    echo 'Install Python using your operating system supported tools, then rerun ./setup.sh.' >&2
    exit 1
fi
if ! python3 -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 9) else 1)'; then
    echo 'open-shinkansen requires Python 3.9 or newer. Update Python using your OS supported tools.' >&2
    exit 1
fi
# A filename inside the package would add src/open_shinkansen to sys.path,
# allowing its usb.py to shadow the third-party PyUSB package named usb.
cd -- "$project_dir"
PYTHONPATH="$project_dir/src" exec python3 -m open_shinkansen.installer "$@"
