#!/usr/bin/env bash
# Linux setup helper for Openwater Open-Motion.
# Installs libusb, the udev rule, and the openmotion-tools Python package.
set -euo pipefail

if [[ $EUID -eq 0 ]]; then
  echo "Run as a regular user — the script will sudo where needed." >&2
  exit 1
fi

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$HERE/.." && pwd)"

echo "==> Installing libusb + python3-venv (Debian/Ubuntu)"
if command -v apt-get >/dev/null 2>&1; then
  sudo apt-get update
  sudo apt-get install -y libusb-1.0-0 python3-venv python3-pip
elif command -v dnf >/dev/null 2>&1; then
  sudo dnf install -y libusbx python3-pip python3-virtualenv
elif command -v pacman >/dev/null 2>&1; then
  sudo pacman -S --needed --noconfirm libusb python-pip python-virtualenv
else
  echo "Unknown package manager — install libusb-1.0 manually, then re-run." >&2
fi

echo "==> Installing udev rule for VID 0483 (Open-Motion sensors)"
sudo install -m 0644 "$HERE/99-openmotion.rules" /etc/udev/rules.d/99-openmotion.rules
sudo udevadm control --reload-rules
sudo udevadm trigger

echo "==> Creating venv at $REPO/.venv"
python3 -m venv "$REPO/.venv"
# shellcheck disable=SC1091
source "$REPO/.venv/bin/activate"
pip install --upgrade pip
pip install -e "$REPO"

cat <<EOF

==> Done.

Next steps:
  1. Unplug / replug the Open-Motion console, wait ~10 s for enumeration.
  2. Verify:  lsusb | grep 0483
  3. Clone the SDK alongside this repo:
       git clone https://github.com/OpenwaterHealth/openmotion-sdk
  4. From the SDK: follow its README to run multicam_setup.py then capture_data.py.
  5. Feed the resulting CSVs into this package (see README.md > Analyzing a scan).
EOF
