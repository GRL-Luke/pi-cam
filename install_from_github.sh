#!/usr/bin/env bash
set -euo pipefail

REPO_URL="${1:-https://github.com/REPLACE_ME/pi-cam.git}"
INSTALL_DIR="${INSTALL_DIR:-/opt/ip-webcam-pi}"
SERVICE_USER="${SERVICE_USER:-pi}"
SERVICE_GROUP="${SERVICE_GROUP:-$SERVICE_USER}"
PYTHON_BIN="${PYTHON_BIN:-python3}"

if [[ "$REPO_URL" == *"REPLACE_ME"* ]]; then
  echo "ERROR: pass your real GitHub repo URL as the first argument."
  echo "Example: sudo bash install_from_github.sh https://github.com/your-user/pi-cam.git"
  exit 1
fi

if ! command -v git >/dev/null 2>&1; then
  echo "Installing git..."
  apt-get update
  apt-get install -y git
fi

echo "Installing system packages..."
apt-get update
apt-get install -y \
  python3-pip \
  python3-venv \
  python3-libcamera \
  python3-kms++ \
  avahi-daemon

mkdir -p "$INSTALL_DIR"
if [[ -d "$INSTALL_DIR/.git" ]]; then
  echo "Updating existing checkout in $INSTALL_DIR"
  git -C "$INSTALL_DIR" fetch --all --prune
  git -C "$INSTALL_DIR" reset --hard origin/$(git -C "$INSTALL_DIR" rev-parse --abbrev-ref HEAD || echo main)
else
  echo "Cloning $REPO_URL to $INSTALL_DIR"
  rm -rf "$INSTALL_DIR"
  git clone "$REPO_URL" "$INSTALL_DIR"
fi

chown -R "$SERVICE_USER":"$SERVICE_GROUP" "$INSTALL_DIR"

if [[ ! -d "$INSTALL_DIR/.venv" ]]; then
  sudo -u "$SERVICE_USER" "$PYTHON_BIN" -m venv "$INSTALL_DIR/.venv"
fi

sudo -u "$SERVICE_USER" "$INSTALL_DIR/.venv/bin/pip" install --upgrade pip
sudo -u "$SERVICE_USER" "$INSTALL_DIR/.venv/bin/pip" install -r "$INSTALL_DIR/requirements.txt"

install -m 0644 "$INSTALL_DIR/systemd/ip-webcam-pi.service" /etc/systemd/system/ip-webcam-pi.service
sed -i "s#^User=.*#User=$SERVICE_USER#" /etc/systemd/system/ip-webcam-pi.service
sed -i "s#^Group=.*#Group=$SERVICE_GROUP#" /etc/systemd/system/ip-webcam-pi.service
sed -i "s#^WorkingDirectory=.*#WorkingDirectory=$INSTALL_DIR#" /etc/systemd/system/ip-webcam-pi.service
sed -i "s#^ExecStart=.*#ExecStart=$INSTALL_DIR/.venv/bin/python $INSTALL_DIR/ip_webcam_server.py --host 0.0.0.0 --port 8080#" /etc/systemd/system/ip-webcam-pi.service

mkdir -p /etc/avahi/services
install -m 0644 "$INSTALL_DIR/avahi/ip-webcam.service" /etc/avahi/services/ip-webcam.service

systemctl daemon-reload
systemctl enable --now ip-webcam-pi.service
systemctl restart avahi-daemon

HOSTNAME_LOCAL="$(hostname).local"
IP_ADDR="$(hostname -I | awk '{print $1}')"

echo
echo "Done."
echo "Stream URL:   http://$IP_ADDR:8080/video"
echo "Snapshot URL: http://$IP_ADDR:8080/shot.jpg"
echo "mDNS URL:     http://$HOSTNAME_LOCAL:8080/"
echo
echo "Service status: systemctl status ip-webcam-pi.service"
