"""Thin Timbre text-to-speech wrapper with a silent mock voice."""

from __future__ import annotations

import asyncio
import httpx

from app.audio import mock_speech_wav
from app.config import settings
from app.llm import LIVE_SETUP_TODO, ProviderError, ProviderNotConfigured


async def synthesize(
    text: str,
    *,
    language: str = "hi-IN",
    voice: str | None = None,
) -> tuple[bytes, str]:
    """Return (audio_bytes, mime_type). Mock mode returns a short WAV tone/silence."""
    if settings.use_mock_tts:
        return await asyncio.to_thread(mock_speech_wav, text), "audio/wav"

    if not (settings.timbre_endpoint and settings.gnani_api_key):
        raise ProviderNotConfigured(LIVE_SETUP_TODO)

    payload = {
        "text": text,
        "voice": voice or settings.timbre_voice,
        "model": settings.timbre_model,
        "language": language if language != "hi-IN" else settings.timbre_language,
        "speed": 1.0,
        "audio_config": {
            "sample_rate": settings.target_sample_rate,
            "num_channels": 1,
            "sample_width": 2,
            "encoding": "linear_pcm",
            "container": "wav",
        },
    }
    try:
        async with httpx.AsyncClient(timeout=settings.request_timeout_seconds) as client:
            response = await client.post(
                settings.timbre_endpoint,
                headers={
                    "X-API-Key-ID": settings.gnani_api_key,
                    "Content-Type": "application/json",
                },
                json=payload,
            )
            response.raise_for_status()
    except httpx.HTTPError as exc:
        raise ProviderError(f"Timbre request failed: {exc}") from exc
    return response.content, response.headers.get("content-type", "audio/wav").split(";", 1)[0]
