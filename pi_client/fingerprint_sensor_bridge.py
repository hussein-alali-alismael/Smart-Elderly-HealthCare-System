"""AS608 bridge for Raspberry Pi.

Reads fingerprints from an AS608-compatible reader (via the PyFingerprint library),
exports the captured template as base64 and posts it to the Flask server using
the same send_payload function from `fingerprint_client.py`.

If `pyfingerprint` is not installed or the device is not connected, the script
can run in simulated mode (--simulate) to help with integration testing.

Example:
  python fingerprint_sensor_bridge.py --server http://192.168.43.100:5000 --device /dev/ttyUSB0

Requirements on the Pi:
  pip install requests pyfingerprint

"""
from __future__ import annotations

import argparse
import base64
from datetime import datetime
import json
import os
import select
import sys
import time
from typing import Any, Dict
import requests

try:
    from voice import enabled_from_environment, speak
except ImportError:
    enabled_from_environment = lambda: False
    speak = lambda text, enabled=True: False

# Local helper from the pi_client folder
try:
    from fingerprint_client import send_payload
except Exception:
    # If script is executed from another cwd, try to import with path hack
    import importlib.util
    import pathlib
    p = pathlib.Path(__file__).resolve().parent
    spec = importlib.util.spec_from_file_location("fingerprint_client", str(p / "fingerprint_client.py"))
    if spec is None or spec.loader is None:
        raise ImportError("Could not load fingerprint_client.py")
    fingerprint_client = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fingerprint_client)  # type: ignore
    send_payload = fingerprint_client.send_payload  # type: ignore


DEFAULT_DEVICE = "/dev/ttyUSB0"
DEFAULT_BAUDRATE = 57600
DEFAULT_JSON_FILE = "fingerprint_results.json"


def _quit_requested() -> bool:
    """Return True when the user typed q, without blocking sensor polling."""
    if not sys.stdin.isatty():
        return False
    ready, _, _ = select.select([sys.stdin], [], [], 0)
    if not ready:
        return False
    return sys.stdin.readline().strip().lower() in {"q", "quit"}


def _save_result_json(path: str, result: Dict[str, Any]) -> None:
    """Append one scan result to a human-readable JSON array."""
    record = {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "result": result,
    }
    records: list[Dict[str, Any]] = []
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as file:
                existing = json.load(file)
            if isinstance(existing, list):
                records = existing
        except (OSError, json.JSONDecodeError):
            # Keep the next result safe even if an old log was interrupted.
            records = []
    records.append(record)
    with open(path, "w", encoding="utf-8") as file:
        json.dump(records, file, ensure_ascii=False, indent=2)
        file.write("\n")


def _display_result(result: Dict[str, Any], json_file: str) -> None:
    """Display a compact, useful summary while preserving the full JSON log."""
    body = result.get("body") if isinstance(result, dict) else None
    if not isinstance(body, dict):
        body = result
    resident = body.get("resident") if isinstance(body, dict) else None
    resident_text = "unknown"
    if isinstance(resident, dict):
        resident_text = f"{resident.get('name', 'unknown')} (ID {resident.get('id', '?')})"
    print("\n" + "=" * 58)
    print("Fingerprint check-in result")
    print("-" * 58)
    print(f"Network: {'SUCCESS' if result.get('ok') else 'FAILED'}")
    if isinstance(body, dict):
        print(f"Resident: {resident_text}")
        print(f"Status:   {body.get('message', 'No message')}")
        print(f"Step:     {body.get('step', 'unknown')}")
    print(f"Saved:    {json_file}")
    print("Full JSON:")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    print("=" * 58)


def _post_with_retries(url: str, payload: Dict[str, Any], retries: int, timeout: int = 6) -> Dict[str, Any]:
    device_token = os.getenv("FINGERPRINT_DEVICE_TOKEN", "")
    headers = {"X-Fingerprint-Token": device_token} if device_token else {}
    attempt = 0
    while True:
        attempt += 1
        try:
            resp = requests.post(url, json=payload, headers=headers, timeout=timeout)
            try:
                body = resp.json()
            except Exception:
                body = {"status_code": resp.status_code, "text": resp.text}
            return {"ok": resp.ok, "status_code": resp.status_code, "body": body}
        except requests.RequestException as exc:
            print(f"Request failed (attempt {attempt}): {exc}")
            if attempt >= retries:
                return {"ok": False, "error": str(exc)}
            time.sleep(2)


def run_once_sensor_mode(
    server: str,
    device: str,
    baudrate: int,
    retries: int,
    enroll_resident: int | None = None,
    test_resident: int | None = None,
    voice_enabled: bool = True,
):
    try:
        # Import here to allow graceful fallback when library is missing on dev machines
        from pyfingerprint.pyfingerprint import PyFingerprint  # type: ignore[reportMissingImports]
    except Exception as exc:  # pragma: no cover - runtime only on Pi
        print("pyfingerprint library is not available:", exc)
        return {"ok": False, "error": "pyfingerprint not installed"}

    try:
        f = PyFingerprint(device, baudrate, 0xFFFFFFFF, 0x00000000)
        if not f.verifyPassword():
            print("Fingerprint sensor password verification failed.")
            return {"ok": False, "error": "sensor auth failed"}
    except Exception as exc:
        print("Failed to init sensor:", exc)
        return {"ok": False, "error": str(exc)}

    print("Waiting for finger...")
    speak("Please place your finger on the sensor.", enabled=voice_enabled)
    try:
        # Wait for finger image
        while not f.readImage():
            if _quit_requested():
                return {"ok": False, "quit": True, "error": "Stopped by user."}
            time.sleep(0.2)

        # Convert to characteristics (buffer 1)
        f.convertImage(0x01)

        if enroll_resident is not None:
            # AS608 enrollment requires two images of the same finger. The
            # first image is already in buffer 1; wait for removal and capture
            # the second image into buffer 2 before creating the template.
            print("Remove your finger, then place the same finger again...")
            speak("Remove your finger, then place the same finger again.", enabled=voice_enabled)
            while f.readImage():
                if _quit_requested():
                    return {"ok": False, "quit": True, "error": "Stopped by user."}
                time.sleep(0.2)
            while not f.readImage():
                if _quit_requested():
                    return {"ok": False, "quit": True, "error": "Stopped by user."}
                time.sleep(0.2)
            f.convertImage(0x02)

            try:
                f.createTemplate()
            except Exception as exc:
                return {"ok": False, "error": f"Could not create sensor template from two scans: {exc}"}

        # Ask the AS608 to identify this finger from its internal storage.
        position_number = -1
        accuracy_score = 0
        try:
            result = f.searchTemplate()
            position_number = int(result[0])
            accuracy_score = int(result[1])
            print(f"AS608 search result: position={position_number}, accuracy={accuracy_score}")
        except Exception as exc:
            print(f"AS608 search failed: {exc}")
            position_number = -1
            accuracy_score = 0

        # Download characteristics (list of ints) and encode as base64
        chars = f.downloadCharacteristics(0x01)
        template_bytes = bytes(chars)
        template_b64 = base64.b64encode(template_bytes).decode("ascii")

        payload: Dict[str, Any] = {
            "fingerprintTemplate": template_b64,
            "sensor_position": position_number,
            "accuracy": accuracy_score,
        }

        print("Captured fingerprint.")

        if enroll_resident is not None:
            # Store the completed template in the AS608 itself. Using the
            # resident id as the sensor slot keeps this test mapping simple.
            try:
                try:
                    stored_position = f.storeTemplate(enroll_resident)
                except TypeError:
                    stored_position = f.storeTemplate()
                print(f"Sensor template stored at position {stored_position}.")
                speak("Fingerprint enrolled successfully.", enabled=voice_enabled)
            except Exception as exc:
                return {"ok": False, "error": f"Could not store template in sensor: {exc}"}

            enroll_url = server.rstrip("/") + f"/api/residents/{enroll_resident}/fingerprint"
            print(f"Enrolling template for resident {enroll_resident} -> {enroll_url}")
            return _post_with_retries(
                enroll_url,
                {
                    "fingerprintTemplate": template_b64,
                    "sensor_position": stored_position,
                },
                retries,
            )

        if position_number < 0:
            return {
                "ok": False,
                "error": "AS608 did not recognize this finger. Enroll it again or check the sensor memory.",
                "sensor_position": position_number,
                "accuracy": accuracy_score,
            }

        if test_resident is not None and position_number != test_resident:
            print(
                f"Rejected fingerprint: sensor position {position_number} "
                f"does not belong to resident {test_resident}."
            )
            speak("This fingerprint belongs to a different resident.", enabled=voice_enabled)
            return {
                "ok": False,
                "error": "Recognized fingerprint belongs to a different sensor slot.",
                "sensor_position": position_number,
                "accuracy": accuracy_score,
                "expected_position": test_resident,
            }

        print("Sending payload to fingerprint check-in endpoint...")
        # Do not send the raw template for normal check-in: each scan can
        # produce different characteristics. The AS608 search position is the
        # reliable identification result used by the Flask agent.
        # Enrollment stores the resident's template in the same AS608 slot as
        # the resident id, so the search position identifies the resident.
        resident_id = position_number
        result = send_payload(
            server,
            {
            "fingerprint_id": resident_id,
                "sensor_position": position_number,
                "accuracy": accuracy_score,
            },
            retries=retries,
        )
        body = result.get("body", {}) if isinstance(result, dict) else {}
        message = body.get("message") if isinstance(body, dict) else None
        speak(message or "Fingerprint check-in completed.", enabled=voice_enabled)
        return result
    except Exception as exc:
        print("Error during capture:", exc)
        return {"ok": False, "error": str(exc)}


def run_loop(
    server: str,
    device: str,
    baudrate: int,
    poll_seconds: float,
    retries: int,
    simulate: bool,
    enroll_resident: int | None = None,
    test_resident: int | None = None,
    json_file: str = DEFAULT_JSON_FILE,
    voice_enabled: bool = True,
):
    if simulate:
        import random

    while True:
        if simulate:
            # synthetic payload for testing
            fake_id = int(time.time()) % 1000
            payload = {"resident_id": fake_id}
            print("[simulate] sending resident_id", fake_id)
            if enroll_resident is not None:
                enroll_url = server.rstrip("/") + f"/api/residents/{enroll_resident}/fingerprint"
                res = _post_with_retries(enroll_url, {"fingerprintTemplate": "SIMULATED_BASE64=="}, retries)
            else:
                res = send_payload(server, payload, retries=retries)
            _display_result(res, json_file)
            _save_result_json(json_file, res)
        else:
            res = run_once_sensor_mode(
                server,
                device,
                baudrate,
                retries,
                enroll_resident=enroll_resident,
                test_resident=test_resident,
                voice_enabled=voice_enabled,
            )
            if res.get("quit"):
                break
            _display_result(res, json_file)
            _save_result_json(json_file, res)

        # Small debounce to avoid busy loop
        for _ in range(max(1, int(poll_seconds * 10))):
            if _quit_requested():
                return
            time.sleep(0.1)


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--server", required=True, help="Flask server base URL, e.g. http://192.168.0.10:5000")
    parser.add_argument("--device", default=DEFAULT_DEVICE, help=f"Serial device for AS608 (default: {DEFAULT_DEVICE})")
    parser.add_argument("--baudrate", type=int, default=DEFAULT_BAUDRATE)
    parser.add_argument("--once", action="store_true", help="Capture a single fingerprint and exit")
    parser.add_argument("--poll", type=float, default=2.0, help="Seconds between capture attempts in loop mode")
    parser.add_argument("--retries", type=int, default=5)
    parser.add_argument(
        "--json-file",
        default=DEFAULT_JSON_FILE,
        help=f"JSON history file for scan results (default: {DEFAULT_JSON_FILE})",
    )
    parser.add_argument("--simulate", action="store_true", help="Run in simulated mode (no sensor required)")
    parser.add_argument("--no-voice", action="store_true", help="Disable spoken prompts and results")
    parser.add_argument("--enroll-resident", type=int, default=None, help="If provided, enroll the captured template to this resident id")
    parser.add_argument(
        "--test-resident",
        type=int,
        default=None,
        help="Testing only: accept only the AS608 position equal to this resident id",
    )
    args = parser.parse_args(argv)

    if args.once and args.simulate:
        print("--once and --simulate are incompatible")
        sys.exit(2)

    if args.once:
        if args.simulate:
            print("Simulation single-shot not supported")
            sys.exit(2)
        result = run_once_sensor_mode(
            args.server,
            args.device,
            args.baudrate,
            args.retries,
            enroll_resident=args.enroll_resident,
            test_resident=args.test_resident,
            voice_enabled=not args.no_voice,
        )
        _display_result(result, args.json_file)
        _save_result_json(args.json_file, result)
        return

    try:
        run_loop(
            args.server,
            args.device,
            args.baudrate,
            args.poll,
            args.retries,
            args.simulate,
            enroll_resident=args.enroll_resident,
            test_resident=args.test_resident,
            json_file=args.json_file,
            voice_enabled=not args.no_voice,
        )
    except KeyboardInterrupt:
        print("Exiting on user request")


if __name__ == "__main__":
    main()
