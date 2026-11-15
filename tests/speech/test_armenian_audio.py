"""Network-free tests of Armenian voice pacing without altering phonemes."""

from __future__ import annotations

import numpy as np

from openjarvis.speech.armenian_audio import shorten_long_pauses


def test_shortens_only_long_silences():
    sr = 24000
    speech = np.full(sr // 4, 0.08, dtype=np.float32)
    short = np.zeros(sr // 5, dtype=np.float32)
    long = np.zeros(sr, dtype=np.float32)
    audio = np.concatenate((speech, short, speech, long, speech))

    processed = shorten_long_pauses(audio, sr)
    assert processed.dtype == audio.dtype
    assert len(processed) < len(audio) - int(0.65 * sr)
    assert len(processed) > len(audio) - int(0.85 * sr)
    assert np.count_nonzero(processed == 0.08) == 3 * len(speech)


def test_keeps_uninterrupted_speech_and_quiet_short_pauses():
    sr = 24000
    audio = np.concatenate(
        (np.full(sr, 0.1, dtype=np.float32), np.zeros(sr // 8, np.float32))
    )
    result = shorten_long_pauses(audio, sr)
    assert result is audio


def test_ignores_multichannel_and_empty_samples():
    assert shorten_long_pauses(np.zeros((100, 2)), 24000).shape == (100, 2)
    assert shorten_long_pauses(np.zeros(0), 24000).size == 0
