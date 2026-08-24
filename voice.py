"""Small cross-platform text-to-speech helper for SEHCS server agents."""
from __future__ import annotations

import os
import platform
import subprocess
from typing import Optional


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
            subprocess.Popen([command, "-v", os.getenv("SEHCS_TTS_VOICE", "en"), message])
        return True
    except (OSError, subprocess.SubprocessError):
        return False


def _command_exists(command: str) -> bool:
    from shutil import which
    return which(command) is not None
