#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"
if [[ $EUID == 0 ]]; then
    echo 'Rulează ca utilizatorul desktop (toni), fără sudo în fața scriptului.' >&2
    exit 1
fi
sudo apt-get update
sudo apt-get install -y python3-venv python3-tk libglib2.0-0 libgl1 v4l-utils
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements.txt
sudo usermod -aG dialout,video "$USER"
sudo install -m 0644 linux/70-dobot-magician.rules /etc/udev/rules.d/70-dobot-magician.rules
sudo modprobe cp210x
sudo udevadm control --reload-rules
sudo udevadm trigger --subsystem-match=tty --attr-match=idVendor=10c4 || true
systemctl --user enable --now hermes-comfyui.service
.venv/bin/python tools/install_desktop.py
echo 'Instalare completă. Reconectează USB-ul robotului. După schimbarea grupurilor, ieși și reintră în sesiunea desktop.'
