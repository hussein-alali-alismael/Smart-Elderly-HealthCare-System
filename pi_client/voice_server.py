"""Small Raspberry Pi HTTP service for centralized SEHCS announcements."""
from __future__ import annotations

import hmac
import json
import os
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

from voice import speak


def _speak_async(message: str) -> None:
    """Play speech without keeping the HTTP request open during playback."""
    def speak_safely() -> None:
        try:
            speak(message, enabled=True)
        except Exception:
            pass

    threading.Thread(target=speak_safely, daemon=True).start()


def process_speech_request(supplied_token: str, payload: object) -> tuple[int, dict[str, object]]:
    expected = _device_token()
    if not expected or not supplied_token or not hmac.compare_digest(supplied_token, expected):
        return 401, {"error": "Voice device authentication required."}

    message = payload.get("message") if isinstance(payload, dict) else None
    if not isinstance(message, str) or not message.strip():
        return 400, {"error": "A non-empty message is required."}

    _speak_async(message)
    return 202, {"ok": True}


def process_health_request(supplied_token: str) -> tuple[int, dict[str, object]]:
    expected = _device_token()
    if not expected or not supplied_token or not hmac.compare_digest(supplied_token, expected):
        return 401, {"error": "Voice device authentication required."}
    return 200, {"ok": True, "service": "sehcs-pi-voice"}


def _device_token() -> str:
    """Return the one shared Pi token."""
    return os.getenv("SEHCS_DEVICE_TOKEN", "").strip()


class VoiceRequestHandler(BaseHTTPRequestHandler):
    def do_POST(self):  # noqa: N802 - required by BaseHTTPRequestHandler
        if self.path != "/speak":
            self._send_json(404, {"error": "Not found."})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length))
        except (ValueError, json.JSONDecodeError):
            self._send_json(400, {"error": "Invalid JSON payload."})
            return
        status, body = process_speech_request(self.headers.get("X-Voice-Token", ""), payload)
        self._send_json(status, body)

    def do_GET(self):  # noqa: N802 - required by BaseHTTPRequestHandler
        if self.path != "/health":
            self._send_json(404, {"error": "Not found."})
            return
        status, body = process_health_request(self.headers.get("X-Voice-Token", ""))
        self._send_json(status, body)

    def _send_json(self, status: int, body: dict[str, object]) -> None:
        encoded = json.dumps(body).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def log_message(self, format, *args):
        return


if __name__ == "__main__":
    server = HTTPServer(
        (os.getenv("SEHCS_VOICE_BIND_HOST", "0.0.0.0"), int(os.getenv("SEHCS_VOICE_PORT", "5051"))),
        VoiceRequestHandler,
    )
    print(f"SEHCS Pi voice service listening on port {server.server_port}")
    server.serve_forever()