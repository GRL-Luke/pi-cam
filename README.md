# Raspberry Pi IP Webcam Compatibility Server (Arducam)

This project provides a Raspberry Pi HTTP camera server on **port 8080** that mimics common endpoint patterns from the Android **IP Webcam** app so third-party software can discover it and pull snapshots/live feed.

> Important: a byte-for-byte, protocol-perfect clone of Android IP Webcam is not realistic on Raspberry Pi hardware/drivers, but this server is designed to be highly compatible with the endpoints most integrations expect.

## Features

- Binds to `0.0.0.0:8080` so devices on the same VLAN can reach it.
- MJPEG stream endpoints compatible with common IP Webcam clients:
  - `/video`
  - `/videofeed`
  - `/mjpeg`
  - `/video.mjpg`
- Snapshot endpoints:
  - `/shot.jpg`
  - `/photo.jpg`
  - `/photoaf.jpg`
  - `/image.jpg`
- Basic metadata/status endpoints:
  - `/status.json`
  - `/sensors.json`
  - `/settings`
- Compatibility no-op command endpoints (return success JSON):
  - `/focus`
  - `/enabletorch`
  - `/disabletorch`
  - `/night_vision`
- Camera backend priority:
  1. `picamera2` (recommended for Arducam/libcamera stack)
  2. OpenCV fallback (`cv2.VideoCapture`)

## Install

On Raspberry Pi OS:

```bash
sudo apt update
sudo apt install -y python3-pip python3-libcamera python3-kms++ libcap-dev avahi-daemon
cd /opt
sudo mkdir -p ip-webcam-pi
sudo chown "$USER":"$USER" ip-webcam-pi
cd ip-webcam-pi
# copy project files here
pip3 install -r requirements.txt
```

If `opencv-python` wheel is heavy for your model, you can remove it from `requirements.txt` and rely only on `picamera2`.

## Run manually

```bash
python3 ip_webcam_server.py --host 0.0.0.0 --port 8080 --width 1280 --height 720 --fps 20
```

Then from another device on the same VLAN:

- Stream: `http://<pi-ip>:8080/video`
- Snapshot: `http://<pi-ip>:8080/shot.jpg`
- Status: `http://<pi-ip>:8080/status.json`

## Systemd autostart

```bash
sudo cp systemd/ip-webcam-pi.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now ip-webcam-pi.service
sudo systemctl status ip-webcam-pi.service
```

## Network discovery (mDNS / Bonjour)

This helps many LAN discovery tools find your camera host name.

```bash
sudo cp avahi/ip-webcam.service /etc/avahi/services/
sudo systemctl restart avahi-daemon
```

Discoverable URL is typically:

- `http://<hostname>.local:8080/`

## VLAN and firewall checklist

- Pi and clients must be in the same VLAN/subnet, or inter-VLAN ACL must allow TCP/8080.
- Open firewall on Pi if enabled:

```bash
sudo ufw allow 8080/tcp
```

## Compatibility notes

To maximize compatibility with software expecting Android IP Webcam:

1. Keep server on port `8080`.
2. Use `/video` and `/shot.jpg` as primary URLs.
3. If software probes alternate paths, aliases are provided above.
4. Some Android-only controls (flashlight/sensors) are returned as accepted no-op responses.

## Quick test commands

```bash
curl -I http://127.0.0.1:8080/shot.jpg
curl -I http://127.0.0.1:8080/video
curl http://127.0.0.1:8080/status.json
```

## Disclaimer

This project provides **practical interoperability**, not a reverse-engineered full clone of the proprietary Android app internals.
