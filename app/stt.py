"""Thin Prisma speech-to-text wrapper with a mock mode for zero-credit development."""

from __future__ import annotations

import hashlib
import httpx

from app.config import settings
from app.llm import LIVE_SETUP_TODO, ProviderError, ProviderNotConfigured

_MOCK_TRANSCRIPTS = (
    "Hello? Kaun bol raha hai? Mujhe kuch samajh nahi aa raha.",
    "Main apna OTP ya bank detail kisi ko nahi bataunga. Pehle likhit notice bhejiye.",
    "Ek minute, mujhe apne bete se baat karne dijiye.",
    "Aap kaunse department se hain? Main pehle verify karna chahta hoon.",
    "Yeh fraud lag raha hai. Main call cut kar raha hoon.",
    "Theek hai, lekin pehle mujhe official website par check karne dijiye.",
)


async def transcribe(
    audio: bytes,
    *,
    language: str = "hi-IN",
    content_type: str | None = None,
) -> str:
    """Transcribe 8 kHz mono WAV. Hindi-English code-mixing with auto detect."""
    if settings.use_mock_stt:
        digest = hashlib.sha256(audio or b"mock").digest()
        return _MOCK_TRANSCRIPTS[digest[0] % len(_MOCK_TRANSCRIPTS)]

    if not (settings.prisma_endpoint and settings.gnani_api_key):
        raise ProviderNotConfigured(LIVE_SETUP_TODO)

    # Official Prisma REST contract: multipart audio_file + language_code.
    # Prisma REST uses en-IN for mixed Hindi-English recognition.
    request_language = "en-IN" if language in ("auto", "hi-en") else language
    files = {"audio_file": ("parent.wav", audio, content_type or "audio/wav")}
    data = {
        "language_code": request_language,
        "format": "verbatim",
    }
    try:
        async with httpx.AsyncClient(timeout=settings.request_timeout_seconds) as client:
            response = await client.post(
                settings.prisma_endpoint,
                headers={"X-API-Key-ID": settings.gnani_api_key},
                files=files,
                data=data,
            )
            response.raise_for_status()
            payload = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise ProviderError(f"Prisma request failed: {exc}") from exc

    transcript = payload.get("transcript") if isinstance(payload, dict) else None
    if not isinstance(transcript, str) or not transcript.strip():
        raise ProviderError("Prisma returned no transcript in the documented response.")
    return transcript.strip()
