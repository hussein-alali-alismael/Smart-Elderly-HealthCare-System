"""Small cross-platform text-to-speech helper for SEHCS server agents."""
from __future__ import annotations

import os
import platform
import subprocess
import logging
from typing import Optional

import requests

logger = logging.getLogger(__name__)


def _voice_device_token() -> str:
    """Return the dedicated voice token, falling back to the device token."""
    return os.getenv("SEHCS_VOICE_DEVICE_TOKEN", "").strip() or os.getenv("SEHCS_DEVICE_TOKEN", "").strip()


def voice_enabled(default: bool = False) -> bool:
    value = os.getenv("SEHCS_VOICE_ENABLED")
    if value is None:
        return default
    return value.lower() in {"1", "true", "yes", "on"}


def server_voice_enabled() -> bool:
    """Return whether speech from Flask-side agents is enabled."""
    value = os.getenv("SEHCS_SERVER_VOICE_ENABLED")
    if value is None:
        return voice_enabled(default=False)
    return value.lower() in {"1", "true", "yes", "on"}


def speak(text: str, *, enabled: Optional[bool] = None) -> bool:
    """Speak short text and return whether a speech command was started."""
    if not text or not (voice_enabled() if enabled is None else enabled):
        return False

    message = " ".join(str(text).split())[:500]
    device_url = os.getenv("SEHCS_VOICE_DEVICE_URL", "").strip()
    if device_url:
        try:
            response = requests.post(
                device_url.rstrip("/") + "/speak",
                json={"message": message},
                headers={"X-Voice-Token": _voice_device_token()},
                timeout=3,
            )
            if response.status_code != 202:
                logger.warning(
                    "Raspberry Pi voice service rejected speech with HTTP %s: %s",
                    response.status_code,
                    response.text[:200],
                )
            elif response.status_code == 202:
                return True
        except requests.RequestException as exc:
            logger.warning("Could not reach Raspberry Pi voice service at %s: %s", device_url, exc)
        # Continue to the local platform speaker as a safety fallback. This
        # keeps a fall announcement audible if the Pi voice service is down
        # or its token/configuration is temporarily wrong.

    system = platform.system()
    try:
        if system == "Windows":
            escaped = message.replace("'", "''")
            command = (
                "Add-Type -AssemblyName System.Speech; "
                "$s=New-Object System.Speech.Synthesis.SpeechSynthesizer; "
                f"$s.Speak('{escaped}')"
            )
            subprocess.Popen(["powershell", "-NoProfile", "-Command", command])
        elif system == "Darwin":
            subprocess.Popen(["say", message])
        else:
            command = next((name for name in ("espeak-ng", "espeak") if _command_exists(name)), None)
            if command is None:
                return False
            subprocess.Popen([command, "-v", os.getenv("SEHCS_TTS_VOICE", "en+f3"), message])
        return True
    except (OSError, subprocess.SubprocessError):
        return False


def _command_exists(command: str) -> bool:
    from shutil import which
    return which(command) is not None
