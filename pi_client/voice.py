"""Raspberry Pi text-to-speech helper for the fingerprint bridge."""
from __future__ import annotations

import os
import subprocess
from shutil import which


def speak(text: str, enabled: bool = True) -> bool:
    """Speak a short message through the Pi speaker, if TTS is installed."""
    if not enabled or not text:
        return False
    command = next((name for name in ("espeak-ng", "espeak") if which(name)), None)
    if command is None:
        return False
    try:
        voice_name = os.getenv("SEHCS_TTS_VOICE", "en")
        subprocess.Popen([command, "-v", voice_name, "-s", "145", " ".join(str(text).split())[:500]])
        return True
    except (OSError, subprocess.SubprocessError):
        return False


def enabled_from_environment() -> bool:
    return os.getenv("SEHCS_VOICE_ENABLED", "true").lower() in {"1", "true", "yes", "on"}
