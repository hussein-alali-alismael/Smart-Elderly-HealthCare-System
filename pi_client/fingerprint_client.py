"""Pi-side fingerprint client for testing and forwarding sensor data to the Flask server.

Usage examples:
  # send a test numeric resident id
  python fingerprint_client.py --server http://192.168.43.100:5000 --id 7

  # send a JSON payload read from a file
  python fingerprint_client.py --server http://192.168.43.100:5000 --file payload.json

This script retries on network errors and logs basic info to stdout. It's intended
as a simple test client and as a reference for the final Pi sensor integration.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from typing import Any, Dict

import requests

try:
    from voice import enabled_from_environment, speak
except ImportError:
    enabled_from_environment = lambda: False
    speak = lambda text, enabled=True: False

DEFAULT_RETRY_SECONDS = 5
DEFAULT_TIMEOUT = 6


def speak_result(result: Dict[str, Any], enabled: bool | None = None) -> None:
    """Speak the useful message from a fingerprint server result."""
    if not isinstance(result, dict):
        return

    body = result.get("body")
    message = None
    if isinstance(body, dict):
        message = body.get("message") or body.get("error") or body.get("text")
    if not message:
        message = result.get("error")
    if not message:
        message = "Fingerprint check-in completed." if result.get("ok") else "Fingerprint check-in failed."

    speak_message(
        str(message),
        enabled=enabled_from_environment() if enabled is None else enabled,
    )


def speak_message(message: str, enabled: bool = True) -> None:
    """Use the central Pi voice service, matching scheduler speech."""
    if not enabled or not message:
        return

    voice_url = os.getenv("SEHCS_VOICE_DEVICE_URL", "http://127.0.0.1:5051").strip()
    token = os.getenv("SEHCS_DEVICE_TOKEN", "")
    try:
        response = requests.post(
            voice_url.rstrip("/") + "/speak",
            json={"message": " ".join(str(message).split())[:500]},
            headers={"X-Voice-Token": token},
            timeout=3,
        )
        if response.status_code == 202:
            return
    except requests.RequestException:
        pass

    # Keep local speech as a fallback if the voice service is unavailable.
    speak(str(message), enabled=True)


def send_payload(
    server: str,
    payload: Dict[str, Any],
    retries: int = 5,
    device_token: str | None = None,
    voice_enabled: bool | None = None,
) -> Dict[str, Any]:
    url = server.rstrip("/") + "/api/fingerprint-checkin"
    token = device_token or os.getenv("SEHCS_DEVICE_TOKEN", "")
    headers = {"X-Fingerprint-Token": token} if token else {}
    attempt = 0
    while True:
        attempt += 1
        try:
            resp = requests.post(url, json=payload, headers=headers, timeout=DEFAULT_TIMEOUT)
            try:
                body = resp.json()
            except Exception:
                body = {"status_code": resp.status_code, "text": resp.text}
            result = {"ok": resp.ok, "status_code": resp.status_code, "body": body}
            speak_result(result, enabled=voice_enabled)
            return result
        except requests.RequestException as exc:
            print(f"Request failed (attempt {attempt}): {exc}")
            if attempt >= retries:
                result = {"ok": False, "error": str(exc)}
                speak_result(result, enabled=voice_enabled)
                return result
            time.sleep(DEFAULT_RETRY_SECONDS)


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--server", required=True, help="Flask server base URL, e.g. http://192.168.0.10:5000")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--id", type=int, help="Resident numeric id to simulate (fingerprint matched to this id)")
    group.add_argument("--file", help="Path to a JSON file to send as payload")
    parser.add_argument("--retries", type=int, default=5)
    parser.add_argument(
        "--token",
        default=os.getenv("SEHCS_DEVICE_TOKEN", ""),
        help="Shared token configured as SEHCS_DEVICE_TOKEN",
    )
    args = parser.parse_args(argv)

    if args.file:
        with open(args.file, "r", encoding="utf-8") as fh:
            payload = json.load(fh)
    else:
        payload = {"resident_id": args.id}

    print(f"Sending payload to {args.server}: {payload}")
    result = send_payload(args.server, payload, retries=args.retries, device_token=args.token)
    print("Result:", json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
