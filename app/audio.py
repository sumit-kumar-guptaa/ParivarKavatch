"""Audio conversion, 8 kHz normalisation, and an optional telephone filter.

ffmpeg does the heavy lifting. WAV files already in the target format pass
through without spawning a process.
"""

from __future__ import annotations

import asyncio
import math
import shutil
import tempfile
import wave
from array import array
from io import BytesIO
from pathlib import Path

from app.config import settings


class AudioProcessingError(ValueError):
    """Raised when incoming or outgoing audio cannot be converted."""


_SUFFIX_BY_TYPE = {
    "audio/webm": ".webm",
    "audio/ogg": ".ogg",
    "audio/mp4": ".m4a",
    "audio/m4a": ".m4a",
    "audio/mpeg": ".mp3",
    "audio/mp3": ".mp3",
    "audio/wav": ".wav",
    "audio/x-wav": ".wav",
    "audio/wave": ".wav",
}


def _suffix_for(content_type: str | None) -> str:
    if not content_type:
        return ".bin"
    clean = content_type.split(";", 1)[0].strip().lower()
    return _SUFFIX_BY_TYPE.get(clean, ".bin")


def looks_like_wav(data: bytes) -> bool:
    """Cheap RIFF/WAVE header check."""
    return len(data) > 12 and data[:4] == b"RIFF" and data[8:12] == b"WAVE"


def is_target_wav(data: bytes) -> bool:
    """True when bytes are mono 16-bit PCM at the configured sample rate."""
    if not looks_like_wav(data):
        return False
    try:
        with wave.open(BytesIO(data), "rb") as handle:
            return (
                handle.getnchannels() == 1
                and handle.getsampwidth() == 2
                and handle.getframerate() == settings.target_sample_rate
            )
    except (wave.Error, EOFError):
        return False


def pcm16_wav(samples: array, sample_rate: int) -> bytes:
    """Wrap signed 16-bit mono samples in a WAV container."""
    buffer = BytesIO()
    with wave.open(buffer, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)
        handle.writeframes(samples.tobytes())
    return buffer.getvalue()


def mock_speech_wav(text: str, sample_rate: int | None = None) -> bytes:
    """Create a short tone plus silence as a stand-in for real TTS audio."""
    rate = sample_rate or settings.target_sample_rate
    words = max(1, len(text.split()))
    duration = min(8.0, max(1.0, 0.35 + words / 2.6))
    tone_frames = int(rate * 0.12)
    total_frames = int(rate * duration)
    samples = array("h", [0]) * total_frames
    for index in range(min(tone_frames, total_frames)):
        envelope = 1.0 - (index / max(1, tone_frames))
        samples[index] = int(2200 * envelope * math.sin(2 * math.pi * 660 * index / rate))
    return pcm16_wav(samples, rate)


def wav_duration(data: bytes) -> float:
    """Return duration in seconds for a WAV payload."""
    try:
        with wave.open(BytesIO(data), "rb") as handle:
            return handle.getnframes() / float(handle.getframerate())
    except (wave.Error, EOFError) as exc:
        raise AudioProcessingError("Invalid WAV payload") from exc


def _run_ffmpeg(data: bytes, content_type: str | None, phone_filter: bool) -> bytes:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise AudioProcessingError("ffmpeg is not installed or not on PATH")
    if not data:
        raise AudioProcessingError("Empty audio payload")

    with tempfile.TemporaryDirectory(prefix="parivar_audio_") as temp_dir:
        source = Path(temp_dir) / f"input{_suffix_for(content_type)}"
        destination = Path(temp_dir) / "output.wav"
        source.write_bytes(data)
        command = [
            ffmpeg,
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(source),
            "-ac",
            "1",
            "-ar",
            str(settings.target_sample_rate),
            "-sample_fmt",
            "s16",
        ]
        if phone_filter:
            command += ["-af", "highpass=f=300,lowpass=f=3400"]
        command += ["-f", "wav", str(destination)]
        try:
            import subprocess

            result = subprocess.run(command, capture_output=True, timeout=30, check=False)
        except (OSError, subprocess.SubprocessError) as exc:
            raise AudioProcessingError(f"ffmpeg failed to start: {exc}") from exc
        if result.returncode != 0 or not destination.exists():
            detail = result.stderr.decode("utf-8", errors="replace").strip()
            raise AudioProcessingError(f"Could not decode audio: {detail[:300]}")
        return destination.read_bytes()


def normalize_to_target_wav(
    data: bytes,
    content_type: str | None = None,
    *,
    phone_filter: bool = False,
) -> bytes:
    """Convert arbitrary browser audio to mono 16-bit WAV at 8 kHz."""
    if not data:
        raise AudioProcessingError("Empty audio payload")
    if len(data) > settings.max_audio_bytes:
        raise AudioProcessingError("Audio payload is too large")
    if is_target_wav(data) and not phone_filter:
        return data
    return _run_ffmpeg(data, content_type, phone_filter)


async def normalize_for_stt(data: bytes, content_type: str | None = None) -> bytes:
    """Async wrapper around inbound conversion."""
    return await asyncio.to_thread(normalize_to_target_wav, data, content_type)


async def prepare_outbound_audio(
    data: bytes,
    content_type: str | None = None,
    *,
    phone_filter: bool | None = None,
) -> bytes:
    """Apply 8 kHz conversion and the optional phone band filter to TTS output."""
    use_filter = settings.phone_filter if phone_filter is None else phone_filter
    if is_target_wav(data) and not use_filter:
        return data
    return await asyncio.to_thread(
        lambda: normalize_to_target_wav(data, content_type, phone_filter=use_filter)
    )


def wav_info(data: bytes) -> dict[str, int]:
    """Expose basic WAV metadata (handy in tests and diagnostics)."""
    with wave.open(BytesIO(data), "rb") as handle:
        return {
            "channels": handle.getnchannels(),
            "sample_width": handle.getsampwidth(),
            "sample_rate": handle.getframerate(),
            "frames": handle.getnframes(),
        }
