"""Audio format helpers and optional ffmpeg phone filter tests."""

from __future__ import annotations

import shutil

import pytest

from app.audio import (
    is_target_wav,
    mock_speech_wav,
    normalize_to_target_wav,
    wav_info,
)


def test_mock_tts_wav_is_8khz_mono_pcm() -> None:
    wav = mock_speech_wav("Namaste, yeh ek test hai.")
    info = wav_info(wav)
    assert info["channels"] == 1
    assert info["sample_width"] == 2
    assert info["sample_rate"] == 8000
    assert info["frames"] > 0
    assert is_target_wav(wav) is True


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")
def test_phone_filter_keeps_target_format() -> None:
    wav = mock_speech_wav("Filter check.")
    filtered = normalize_to_target_wav(wav, "audio/wav", phone_filter=True)
    assert is_target_wav(filtered) is True
    assert len(filtered) > 44
