"""Raspberry Pi text-to-speech helper for the fingerprint bridge."""
from __future__ import annotations

import os
import sys
import subprocess
import tempfile
from pathlib import Path
from shutil import which


def speak(text: str, enabled: bool = True) -> bool:
    """Speak a short message through the Pi speaker, if TTS is installed."""
    if not enabled or not text:
        return False
    message = " ".join(str(text).split())[:500]
    command = next((name for name in ("espeak-ng", "espeak") if which(name)), None)
    if os.getenv("SEHCS_TTS_ENGINE", "piper").lower() == "piper":
        return _speak_with_piper(message)
    if command is None:
        return False
    try:
        voice_name = os.getenv("SEHCS_TTS_VOICE", "en+f3")
        subprocess.Popen([command, "-v", voice_name, "-s", "145", message])
        return True
    except (OSError, subprocess.SubprocessError):
        return False


def enabled_from_environment() -> bool:
    return os.getenv("SEHCS_VOICE_ENABLED", "true").lower() in {"1", "true", "yes", "on"}


def _speak_with_piper(message: str) -> bool:
    piper = which("piper")
    if piper is None:
        venv_piper = Path(sys.executable).with_name("piper")
        if venv_piper.is_file():
            piper = str(venv_piper)
    player = which(os.getenv("SEHCS_AUDIO_PLAYER", "aplay"))
    model = os.getenv("SEHCS_PIPER_MODEL", "").strip()
    if not piper or not player or not model:
        return False

    wav_path = ""
    try:
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as output:
            wav_path = output.name
        subprocess.run(
            [piper, "--model", model, "--output_file", wav_path],
            input=message,
            text=True,
            check=True,
            timeout=30,
        )
        player_args = [player]
        audio_device = os.getenv("SEHCS_AUDIO_DEVICE", "").strip()
        if audio_device and os.path.basename(player) == "aplay":
            player_args.extend(["-D", audio_device])
        player_args.append(wav_path)
        subprocess.run(player_args, check=True, timeout=120)
        return True
    except (OSError, subprocess.SubprocessError):
        return False
    finally:
        if wav_path:
            try:
                os.unlink(wav_path)
            except OSError:
                pass
