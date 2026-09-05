"""Send one authenticated message through the configured SEHCS speaker."""
from __future__ import annotations

import argparse
import os
import sys

import requests
from dotenv import load_dotenv


def main() -> int:
    load_dotenv(os.path.join(os.path.dirname(__file__), ".env"), override=True)
    parser = argparse.ArgumentParser(description="Speak one SEHCS voice smoke-test message")
    parser.add_argument(
        "--url",
        default=os.getenv("SEHCS_VOICE_DEVICE_URL", "").strip(),
        help="Voice service base URL (defaults to SEHCS_VOICE_DEVICE_URL)",
    )
    parser.add_argument(
        "--token",
        default=os.getenv("SEHCS_VOICE_DEVICE_TOKEN", "").strip()
        or os.getenv("SEHCS_DEVICE_TOKEN", "").strip(),
        help="Voice token (defaults to SEHCS_VOICE_DEVICE_TOKEN or SEHCS_DEVICE_TOKEN)",
    )
    parser.add_argument(
        "--message",
        default="SEHCS fall alert speaker test.",
        help="One message to speak",
    )
    args = parser.parse_args()

    if not args.url:
        parser.error("--url or SEHCS_VOICE_DEVICE_URL is required")
    if not args.token:
        parser.error("--token, SEHCS_VOICE_DEVICE_TOKEN, or SEHCS_DEVICE_TOKEN is required")

    base_url = args.url.rstrip("/")
    headers = {"X-Voice-Token": args.token}
    try:
        health = requests.get(base_url + "/health", headers=headers, timeout=5)
        if health.status_code != 200:
            print(f"Voice health check failed: HTTP {health.status_code} {health.text[:200]}", file=sys.stderr)
            return 1

        response = requests.post(
            base_url + "/speak",
            json={"message": args.message},
            headers=headers,
            timeout=5,
        )
    except requests.RequestException as exc:
        print(f"Could not reach voice service: {exc}", file=sys.stderr)
        return 1

    if response.status_code != 202:
        print(f"Voice request failed: HTTP {response.status_code} {response.text[:200]}", file=sys.stderr)
        return 1

    print("Voice smoke test accepted; the speaker should speak once.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())