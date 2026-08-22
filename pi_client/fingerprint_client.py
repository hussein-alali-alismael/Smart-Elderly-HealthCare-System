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
import sys
import time
from typing import Any, Dict

import requests

DEFAULT_RETRY_SECONDS = 5
DEFAULT_TIMEOUT = 6


def send_payload(server: str, payload: Dict[str, Any], retries: int = 5) -> Dict[str, Any]:
    url = server.rstrip("/") + "/api/fingerprint-checkin"
    attempt = 0
    while True:
        attempt += 1
        try:
            resp = requests.post(url, json=payload, timeout=DEFAULT_TIMEOUT)
            try:
                body = resp.json()
            except Exception:
                body = {"status_code": resp.status_code, "text": resp.text}
            return {"ok": resp.ok, "status_code": resp.status_code, "body": body}
        except requests.RequestException as exc:
            print(f"Request failed (attempt {attempt}): {exc}")
            if attempt >= retries:
                return {"ok": False, "error": str(exc)}
            time.sleep(DEFAULT_RETRY_SECONDS)


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--server", required=True, help="Flask server base URL, e.g. http://192.168.0.10:5000")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--id", type=int, help="Resident numeric id to simulate (fingerprint matched to this id)")
    group.add_argument("--file", help="Path to a JSON file to send as payload")
    parser.add_argument("--retries", type=int, default=5)
    args = parser.parse_args(argv)

    if args.file:
        with open(args.file, "r", encoding="utf-8") as fh:
            payload = json.load(fh)
    else:
        payload = {"resident_id": args.id}

    print(f"Sending payload to {args.server}: {payload}")
    result = send_payload(args.server, payload, retries=args.retries)
    print("Result:", json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
