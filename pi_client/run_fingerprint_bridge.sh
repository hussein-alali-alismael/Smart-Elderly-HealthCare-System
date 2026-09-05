#!/usr/bin/env bash
set -Eeuo pipefail

# Raspberry Pi launcher for the SEHCS AS608 fingerprint bridge.
# Supports both layouts:
#   /home/raspi/Desktop/SEHCS/run_fingerprint_bridge.sh
#   /home/raspi/Desktop/SEHCS/run_fingerprint_bridge.sh

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
if [[ -f "$SCRIPT_DIR/.env" ]]; then
    PROJECT_DIR="$SCRIPT_DIR"
    BRIDGE_SCRIPT="$SCRIPT_DIR/fingerprint_sensor_bridge.py"
else
    PROJECT_DIR="$(cd -- "$SCRIPT_DIR/.." && pwd)"
    BRIDGE_SCRIPT="$SCRIPT_DIR/fingerprint_sensor_bridge.py"
fi
ENV_FILE="$PROJECT_DIR/.env"

if [[ ! -f "$ENV_FILE" ]]; then
    echo "Error: missing $ENV_FILE" >&2
    echo "Copy pi.env.example to $ENV_FILE and fill in the token/device." >&2
    exit 1
fi

# Remove Windows CRLF characters when dos2unix is available; otherwise strip
# them while loading the file so the script also works on a minimal Pi image.
if command -v dos2unix >/dev/null 2>&1; then
    dos2unix "$ENV_FILE" >/dev/null
fi

set -a
# shellcheck disable=SC1090
source <(sed 's/\r$//' "$ENV_FILE")
set +a

FLASK_SERVER_URL="${FLASK_SERVER_URL:-http://10.16.161.225:5000}"
FINGERPRINT_DEVICE="${FINGERPRINT_DEVICE:-/dev/serial0}"

if [[ -x "$PROJECT_DIR/bin/python" ]]; then
    PYTHON="$PROJECT_DIR/bin/python"
elif [[ -x "$PROJECT_DIR/bin/python3" ]]; then
    PYTHON="$PROJECT_DIR/bin/python3"
else
    echo "Error: Python virtual environment not found in $PROJECT_DIR/bin" >&2
    echo "Create it first, for example: python3 -m venv $PROJECT_DIR/bin" >&2
    exit 1
fi

cd "$PROJECT_DIR"
BRIDGE_ARGS=(
    --server "$FLASK_SERVER_URL"
    --device "$FINGERPRINT_DEVICE"
)
[[ -n "${FINGERPRINT_BAUDRATE:-}" ]] && BRIDGE_ARGS+=(--baudrate "$FINGERPRINT_BAUDRATE")
[[ -n "${FINGERPRINT_POLL_SECONDS:-}" ]] && BRIDGE_ARGS+=(--poll "$FINGERPRINT_POLL_SECONDS")
[[ -n "${FINGERPRINT_RETRIES:-}" ]] && BRIDGE_ARGS+=(--retries "$FINGERPRINT_RETRIES")

exec "$PYTHON" "$BRIDGE_SCRIPT" \
    "${BRIDGE_ARGS[@]}"
