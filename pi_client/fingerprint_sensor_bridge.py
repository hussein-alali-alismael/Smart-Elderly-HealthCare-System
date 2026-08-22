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
import sys
import time
from typing import Any, Dict
import requests

# Local helper from the pi_client folder
try:
    from fingerprint_client import send_payload
except Exception:
    # If script is executed from another cwd, try to import with path hack
    import importlib.util
    import pathlib
    p = pathlib.Path(__file__).resolve().parent
    spec = importlib.util.spec_from_file_location("fingerprint_client", str(p / "fingerprint_client.py"))
    fingerprint_client = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fingerprint_client)  # type: ignore
    send_payload = fingerprint_client.send_payload  # type: ignore


DEFAULT_DEVICE = "/dev/ttyUSB0"
DEFAULT_BAUDRATE = 57600


def _post_with_retries(url: str, payload: Dict[str, Any], retries: int, timeout: int = 6) -> Dict[str, Any]:
    attempt = 0
    while True:
        attempt += 1
        try:
            resp = requests.post(url, json=payload, timeout=timeout)
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
):
    try:
        # Import here to allow graceful fallback when library is missing on dev machines
        from pyfingerprint.pyfingerprint import PyFingerprint
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
    try:
        # Wait for finger image
        while not f.readImage():
            time.sleep(0.2)

        # Convert to characteristics (buffer 1)
        f.convertImage(0x01)

        if enroll_resident is not None:
            # AS608 enrollment requires two images of the same finger. The
            # first image is already in buffer 1; wait for removal and capture
            # the second image into buffer 2 before creating the template.
            print("Remove your finger, then place the same finger again...")
            while f.readImage():
                time.sleep(0.2)
            while not f.readImage():
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

        print("Sending payload to fingerprint check-in endpoint...")
        # Do not send the raw template for normal check-in: each scan can
        # produce different characteristics. The AS608 search position is the
        # reliable identification result used by the Flask agent.
        resident_id = test_resident if test_resident is not None else position_number
        return send_payload(
            server,
            {
            "fingerprint_id": resident_id,
                "sensor_position": position_number,
                "accuracy": accuracy_score,
            },
            retries=retries,
        )
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
            print(res)
        else:
            res = run_once_sensor_mode(
                server,
                device,
                baudrate,
                retries,
                enroll_resident=enroll_resident,
                test_resident=test_resident,
            )
            print(res)

        # Small debounce to avoid busy loop
        time.sleep(poll_seconds)


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--server", required=True, help="Flask server base URL, e.g. http://192.168.0.10:5000")
    parser.add_argument("--device", default=DEFAULT_DEVICE, help=f"Serial device for AS608 (default: {DEFAULT_DEVICE})")
    parser.add_argument("--baudrate", type=int, default=DEFAULT_BAUDRATE)
    parser.add_argument("--once", action="store_true", help="Capture a single fingerprint and exit")
    parser.add_argument("--poll", type=float, default=2.0, help="Seconds between capture attempts in loop mode")
    parser.add_argument("--retries", type=int, default=5)
    parser.add_argument("--simulate", action="store_true", help="Run in simulated mode (no sensor required)")
    parser.add_argument("--enroll-resident", type=int, default=None, help="If provided, enroll the captured template to this resident id")
    parser.add_argument(
        "--test-resident",
        type=int,
        default=None,
        help="Testing only: map any recognized AS608 position to this resident id; unrecognized scans are still rejected",
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
        )
        print(result)
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
        )
    except KeyboardInterrupt:
        print("Exiting on user request")


if __name__ == "__main__":
    main()
