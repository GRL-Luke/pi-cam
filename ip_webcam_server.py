#!/usr/bin/env python3
"""IP Webcam-compatible HTTP server for Raspberry Pi + Arducam.

This implements a practical compatibility layer for the most common
Android IP Webcam endpoints used by NVR and automation software.
"""

from __future__ import annotations

import argparse
import io
import json
import logging
import os
import socket
import threading
import time
from dataclasses import dataclass
from typing import Callable

from flask import Flask, Response, jsonify, request


LOG = logging.getLogger("ip-webcam")


@dataclass
class CameraConfig:
    width: int = 1280
    height: int = 720
    fps: int = 20
    jpeg_quality: int = 85


class CameraBackend:
    """Camera abstraction with Picamera2 primary + OpenCV fallback."""

    def __init__(self, cfg: CameraConfig) -> None:
        self.cfg = cfg
        self._lock = threading.Lock()
        self._last_frame: bytes | None = None
        self._picam2 = None
        self._cv2 = None
        self._cap = None
        self._running = True
        self._start_camera()

    def _start_camera(self) -> None:
        try:
            from picamera2 import Picamera2  # type: ignore

            picam2 = Picamera2()
            config = picam2.create_video_configuration(
                main={"size": (self.cfg.width, self.cfg.height), "format": "RGB888"}
            )
            picam2.configure(config)
            picam2.start()
            self._picam2 = picam2
            LOG.info("Using Picamera2 backend")
            return
        except Exception as exc:  # pragma: no cover
            LOG.warning("Picamera2 not available (%s), trying OpenCV", exc)

        try:
            import cv2  # type: ignore

            self._cv2 = cv2
            cap = cv2.VideoCapture(0)
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.cfg.width)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.cfg.height)
            cap.set(cv2.CAP_PROP_FPS, self.cfg.fps)
            if not cap.isOpened():
                raise RuntimeError("OpenCV camera could not be opened")
            self._cap = cap
            LOG.info("Using OpenCV backend")
            return
        except Exception as exc:  # pragma: no cover
            raise RuntimeError(
                "No camera backend available. Install picamera2 or opencv-python."
            ) from exc

    def frame_jpeg(self) -> bytes:
        with self._lock:
            if self._picam2 is not None:
                arr = self._picam2.capture_array()
                import cv2  # type: ignore

                ok, buf = cv2.imencode(
                    ".jpg",
                    arr,
                    [int(cv2.IMWRITE_JPEG_QUALITY), self.cfg.jpeg_quality],
                )
                if not ok:
                    raise RuntimeError("JPEG encoding failed")
                self._last_frame = buf.tobytes()
                return self._last_frame

            if self._cap is not None and self._cv2 is not None:
                ok, frame = self._cap.read()
                if not ok:
                    if self._last_frame is not None:
                        return self._last_frame
                    raise RuntimeError("Could not read camera frame")
                ok, buf = self._cv2.imencode(
                    ".jpg",
                    frame,
                    [int(self._cv2.IMWRITE_JPEG_QUALITY), self.cfg.jpeg_quality],
                )
                if not ok:
                    raise RuntimeError("JPEG encoding failed")
                self._last_frame = buf.tobytes()
                return self._last_frame

            raise RuntimeError("Camera backend unavailable")

    def stream(self):
        frame_interval = 1 / max(self.cfg.fps, 1)
        while self._running:
            try:
                frame = self.frame_jpeg()
            except Exception as exc:
                LOG.exception("Frame generation error: %s", exc)
                time.sleep(0.2)
                continue

            yield (
                b"--frame\r\n"
                b"Content-Type: image/jpeg\r\n"
                b"Content-Length: " + str(len(frame)).encode("ascii") + b"\r\n\r\n" + frame + b"\r\n"
            )
            time.sleep(frame_interval)

    def close(self) -> None:
        self._running = False
        with self._lock:
            if self._picam2 is not None:
                self._picam2.stop()
            if self._cap is not None:
                self._cap.release()


def get_local_ip() -> str:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


def create_app(camera: CameraBackend) -> Flask:
    app = Flask(__name__)
    started_at = time.time()

    @app.route("/")
    def index() -> str:
        host = request.host
        return (
            "<html><head><title>IP Webcam</title></head><body>"
            "<h2>IP Webcam (Raspberry Pi compatibility mode)</h2>"
            f"<p><a href='http://{host}/video'>/video</a> (mjpeg stream)</p>"
            f"<p><a href='http://{host}/shot.jpg'>/shot.jpg</a> (snapshot)</p>"
            "</body></html>"
        )

    @app.route("/video")
    @app.route("/videofeed")
    @app.route("/mjpeg")
    @app.route("/video.mjpg")
    def video() -> Response:
        return Response(
            camera.stream(),
            mimetype="multipart/x-mixed-replace; boundary=frame",
            headers={"Cache-Control": "no-store, no-cache, must-revalidate, max-age=0"},
        )

    @app.route("/shot.jpg")
    @app.route("/photo.jpg")
    @app.route("/photoaf.jpg")
    @app.route("/image.jpg")
    def shot() -> Response:
        jpeg = camera.frame_jpeg()
        return Response(
            jpeg,
            mimetype="image/jpeg",
            headers={"Cache-Control": "no-store, no-cache, must-revalidate, max-age=0"},
        )

    @app.route("/status.json")
    @app.route("/sensors.json")
    def status_json():
        uptime = int(time.time() - started_at)
        return jsonify(
            {
                "app": "IP Webcam",
                "version": "compat-pi-1.0",
                "name": "IPWebCam",
                "uptime": uptime,
                "stream": "/video",
                "snapshot": "/shot.jpg",
                "resolution": f"{camera.cfg.width}x{camera.cfg.height}",
                "fps": camera.cfg.fps,
            }
        )

    @app.route("/settings")
    def settings():
        return jsonify(
            {
                "quality": camera.cfg.jpeg_quality,
                "width": camera.cfg.width,
                "height": camera.cfg.height,
                "fps": camera.cfg.fps,
            }
        )

    @app.route("/focus")
    @app.route("/enabletorch")
    @app.route("/disabletorch")
    @app.route("/night_vision")
    def accepted_noop():
        return jsonify({"ok": True, "note": "Accepted for compatibility; not implemented."})

    return app


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="IP Webcam compatible server for Raspberry Pi")
    p.add_argument("--host", default="0.0.0.0")
    p.add_argument("--port", type=int, default=8080)
    p.add_argument("--width", type=int, default=int(os.getenv("CAM_WIDTH", "1280")))
    p.add_argument("--height", type=int, default=int(os.getenv("CAM_HEIGHT", "720")))
    p.add_argument("--fps", type=int, default=int(os.getenv("CAM_FPS", "20")))
    p.add_argument(
        "--jpeg-quality",
        type=int,
        default=int(os.getenv("JPEG_QUALITY", "85")),
    )
    return p.parse_args()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    args = parse_args()
    cfg = CameraConfig(
        width=args.width,
        height=args.height,
        fps=args.fps,
        jpeg_quality=args.jpeg_quality,
    )

    cam = CameraBackend(cfg)
    app = create_app(cam)

    local_ip = get_local_ip()
    LOG.info("IP Webcam compatibility server started")
    LOG.info("Open stream URL: http://%s:%s/video", local_ip, args.port)
    LOG.info("Open snapshot URL: http://%s:%s/shot.jpg", local_ip, args.port)

    try:
        app.run(host=args.host, port=args.port, threaded=True)
    finally:
        cam.close()


if __name__ == "__main__":
    main()
