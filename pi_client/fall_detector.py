"""Raspberry Pi fall detector, MJPEG stream, and alert delivery service.

Run this on the Pi, not on the Flask server. The dashboard reads /stream.mjpg
from this process while alerts are POSTed to Flask's /api/fall-alerts endpoint.
"""
from __future__ import annotations

import argparse
import os
import sys
import threading
import time
import traceback
from collections import deque
from datetime import datetime, timezone
from pathlib import Path

import cv2
import requests
from flask import Flask, Response, jsonify, request

sys.path.insert(0, str(Path(__file__).resolve().parent))
from pose_run import YOLOPoseFallModel, draw_pose_result  # noqa: E402

app = Flask(__name__)
state = {
    "frame": None,
    "confidence": 0.0,
    "fall": False,
    "last_frame_at": None,
    "last_alert_at": None,
    "last_alert_status": None,
    "last_error": None,
    "people": 0,
}
state_lock = threading.Lock()
TARGET_FPS = max(1.0, float(os.getenv("FALL_TARGET_FPS", "10")))
FRAME_INTERVAL = 1.0 / TARGET_FPS
FALL_CONFIRM_FRAMES = max(1, int(os.getenv("FALL_CONFIRM_FRAMES", "2")))
FALL_CONFIRM_WINDOW = max(FALL_CONFIRM_FRAMES, int(os.getenv("FALL_CONFIRM_WINDOW", "5")))


@app.after_request
def allow_dashboard_status(response):
    """Allow the Flask dashboard to read the Pi status across the LAN."""
    if request.path == "/status":
        response.headers["Access-Control-Allow-Origin"] = os.getenv("FALL_DASHBOARD_ORIGIN", "*")
        response.headers["Cache-Control"] = "no-store"
    return response


def _authorized() -> bool:
    expected = os.getenv("FALL_STREAM_TOKEN", "").strip()
    return not expected or request.args.get("token", "") == expected


def _multipart_frame():
    next_frame_at = time.monotonic()
    while True:
        now = time.monotonic()
        if now < next_frame_at:
            time.sleep(next_frame_at - now)
        next_frame_at = max(next_frame_at + FRAME_INTERVAL, time.monotonic())
        with state_lock:
            frame = state["frame"]
        if frame is not None:
            yield b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + frame + b"\r\n"


@app.get("/stream.mjpg")
def stream():
    if not _authorized():
        return jsonify(error="stream authentication required"), 401
    return Response(_multipart_frame(), mimetype="multipart/x-mixed-replace; boundary=frame")


@app.get("/status")
def status():
    with state_lock:
        return jsonify({key: value for key, value in state.items() if key != "frame"})


def _send_alert(session: requests.Session, backend_url: str, token: str, payload: dict) -> None:
    try:
        response = session.post(
            backend_url,
            json={"event_type": "fall_detection", "timestamp": payload["detected_at"], "data": payload},
            headers={"X-Fall-Alert-Token": token},
            timeout=8,
        )
        response.raise_for_status()
        with state_lock:
            state["last_alert_at"] = payload["detected_at"]
            state["last_alert_status"] = response.status_code
            state["last_error"] = None
        print(f"Fall alert delivered: HTTP {response.status_code} confidence={payload.get('detection_confidence')}", flush=True)
    except requests.RequestException as exc:
        with state_lock:
            state["last_error"] = f"alert delivery failed: {exc}"
            state["last_alert_status"] = getattr(getattr(exc, "response", None), "status_code", None)
        print(state["last_error"], file=sys.stderr)


def _detect_people(frame, detector, frame_number: int):
    """Run the optional built-in OpenCV people detector every few frames."""
    if detector is None or frame_number % 5:
        return []
    boxes, weights = detector.detectMultiScale(
        frame, winStride=(8, 8), padding=(8, 8), scale=1.05
    )
    return [(*box, float(weight)) for box, weight in zip(boxes, weights) if float(weight) >= 0.35]


def run_detector(model_path: str, camera: int, backend_url: str, token: str, threshold: float, cooldown: float) -> None:
    picamera = None
    capture = None
    capture_width = int(os.getenv("FALL_CAPTURE_WIDTH", "320"))
    capture_height = int(os.getenv("FALL_CAPTURE_HEIGHT", "240"))
    camera_backend = os.getenv("FALL_CAMERA_BACKEND", "auto").lower()
    if camera_backend in {"auto", "picamera2"}:
        try:
            from picamera2 import Picamera2
            picamera = Picamera2(camera)
            picamera.configure(picamera.create_preview_configuration(main={"size": (capture_width, capture_height), "format": "RGB888"}))
            picamera.start()
        except (ImportError, RuntimeError, IndexError) as exc:
            if camera_backend == "picamera2":
                raise RuntimeError(f"Picamera2 could not open camera: {exc}") from exc
            print(f"WARNING: Picamera2 unavailable ({exc}); trying OpenCV camera", file=sys.stderr)
            picamera = None
    if picamera is None:
        capture = cv2.VideoCapture(camera)
        capture.set(cv2.CAP_PROP_FRAME_WIDTH, capture_width)
        capture.set(cv2.CAP_PROP_FRAME_HEIGHT, capture_height)
        capture.set(cv2.CAP_PROP_FPS, 15)
        if not capture.isOpened():
            raise RuntimeError(f"cannot open camera {camera}")

    model_file = Path(model_path)
    if not model_file.is_file():
        # Recover from configs copied from the old nested project layout.
        candidates = [Path.cwd() / model_file.name, Path(__file__).resolve().parent / model_file.name]
        model_file = next((candidate for candidate in candidates if candidate.is_file()), model_file)
    if not model_file.is_file():
        raise FileNotFoundError(f"Fall model not found: {model_path}")
    velocity_scale = float(os.getenv("FALL_VELOCITY_SCALE", "180"))
    model = YOLOPoseFallModel(str(model_file), threshold=threshold, velocity_scale=velocity_scale)
    previous_fall = False
    fall_history = deque(maxlen=FALL_CONFIRM_WINDOW)
    previous_center_y = None
    previous_pose_time = None
    last_sent_monotonic = 0.0
    session = requests.Session()
    device_id = os.getenv("FALL_ALERT_DEVICE_ID", "main-camera")
    location = os.getenv("FALL_ALERT_LOCATION", "") or None
    resident_id = os.getenv("FALL_ALERT_DEFAULT_RESIDENT_ID", "") or None
    frame_number = 0
    consecutive_frame_failures = 0
    started = time.monotonic()
    next_frame_at = time.monotonic()

    try:
        while True:
            now = time.monotonic()
            if now < next_frame_at:
                time.sleep(next_frame_at - now)
            next_frame_at = max(next_frame_at + FRAME_INTERVAL, time.monotonic())
            if picamera is not None:
                frame = picamera.capture_array()
                ok = frame is not None
                if ok:
                    frame = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
            else:
                ok, frame = capture.read()
            if not ok or frame is None:
                consecutive_frame_failures += 1
                with state_lock:
                    state["last_error"] = (
                        f"camera frame unavailable ({consecutive_frame_failures} consecutive failures)"
                    )
                if consecutive_frame_failures >= 20:
                    raise RuntimeError(state["last_error"])
                time.sleep(0.25)
                continue
            consecutive_frame_failures = 0
            frame_number += 1
            now = time.monotonic()
            result = model.predict(frame, previous_center_y, previous_pose_time, now)
            probability = float(result["confidence"])
            # Require a small temporal consensus. This reduces false alarms
            # from one bad pose frame while accepting different fall shapes.
            fall_history.append(bool(result["fall"]))
            is_fall = sum(fall_history) >= FALL_CONFIRM_FRAMES
            result["fall"] = is_fall
            if is_fall:
                result["status"] = "FALL"
            previous_center_y = result.get("center_y")
            previous_pose_time = now if previous_center_y is not None else previous_pose_time
            people = result.get("detections", [])
            frame = draw_pose_result(frame, result)
            fps = frame_number / max(time.monotonic() - started, 0.001)
            cv2.putText(frame, f"FPS: {fps:.1f}", (10, frame.shape[0] - 12),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.52, (255, 255, 255), 1)
            ok, encoded = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 75])
            if ok:
                with state_lock:
                    state.update({"frame": encoded.tobytes(), "confidence": round(probability, 4), "fall": is_fall,
                                  "people": len(people),
                                  "last_frame_at": datetime.now(timezone.utc).isoformat(), "last_error": None})

            now = time.monotonic()
            if is_fall and (not previous_fall or now - last_sent_monotonic >= cooldown):
                payload = {
                    "gravity_level": "FALL",
                    "detection_confidence": round(probability, 4),
                    "confidence": round(probability, 4),
                    "status": result.get("status", "FALL"),
                    "confidence_window": len(fall_history),
                    "confirmed_frames": sum(fall_history),
                    "detected_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                    "device_id": device_id,
                    "location": location,
                }
                if resident_id:
                    payload["resident_id"] = resident_id
                _send_alert(session, backend_url, token, payload)
                last_sent_monotonic = now
            previous_fall = is_fall
    finally:
        if capture is not None:
            capture.release()
        if picamera is not None:
            picamera.stop()


def _run_detector_worker(args) -> None:
    """Run inference and terminate so systemd can restart on fatal errors."""
    try:
        run_detector(args.model, args.camera, args.backend, args.token, args.threshold, args.cooldown)
    except BaseException as exc:
        with state_lock:
            state["last_error"] = f"detector stopped: {exc}"
        print(f"FATAL: fall detector stopped: {exc}", file=sys.stderr, flush=True)
        traceback.print_exc()
        os._exit(1)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the Pi fall detector and MJPEG stream")
    parser.add_argument("--model", default=os.getenv("POSE_MODEL_PATH", os.getenv("FALL_MODEL_PATH", "yolov8n-pose.onnx")))
    parser.add_argument("--camera", type=int, default=int(os.getenv("FALL_CAMERA", "0")))
    parser.add_argument("--backend", default=os.getenv("BACKEND_API_URL", "http://127.0.0.1:5000/api/fall-alerts"))
    parser.add_argument("--token", default=os.getenv("SEHCS_DEVICE_TOKEN", ""))
    parser.add_argument("--threshold", type=float, default=float(os.getenv("FALL_THRESHOLD", "0.50")))
    parser.add_argument("--cooldown", type=float, default=float(os.getenv("FALL_ALERT_COOLDOWN_SECONDS", "45")))
    parser.add_argument("--host", default=os.getenv("FALL_STREAM_HOST", "0.0.0.0"))
    parser.add_argument("--port", type=int, default=int(os.getenv("FALL_STREAM_PORT", "8080")))
    args = parser.parse_args()
    if not args.token:
        parser.error("--token or SEHCS_DEVICE_TOKEN is required")
    worker = threading.Thread(target=_run_detector_worker, args=(args,), daemon=True)
    worker.start()
    app.run(host=args.host, port=args.port, threaded=True, use_reloader=False)


if __name__ == "__main__":
    main()
