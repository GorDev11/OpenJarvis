"""Small deterministic post-processing for Pocket-TTS waveform pacing.

This never changes phonemes or synthesizes new speech. It only shortens long
near-silent gaps between phrases, leaving short natural pauses alone.
"""

from __future__ import annotations

import numpy as np


def shorten_long_pauses(
    samples: np.ndarray,
    sample_rate: int,
    *,
    min_silence_seconds: float = 0.48,
    retain_seconds: float = 0.24,
    silence_threshold: float = 0.003,
) -> np.ndarray:
    """Shorten long low-amplitude spans without touching spoken audio.

    Only runs of quiet samples longer than min_silence_seconds are processed.
    Retain equal halves at each end of an interior silence to avoid deleting
    consonant transitions. Input stays mono with the same sample rate/dtype.
    """
    signal = np.asarray(samples)
    if signal.ndim != 1 or signal.size == 0 or sample_rate <= 0:
        return signal
    threshold_samples = int(min_silence_seconds * sample_rate)
    retained = int(retain_seconds * sample_rate)
    if threshold_samples <= 0 or retained <= 0 or retained >= threshold_samples:
        return signal

    silent = np.abs(signal) < silence_threshold
    change = np.flatnonzero(np.diff(silent.astype(np.int8))) + 1
    edges = np.concatenate(([0], change, [len(signal)]))
    result = []
    cursor = 0

    for start, stop in zip(edges[:-1], edges[1:]):
        if not silent[start] or stop - start <= threshold_samples:
            continue
        # Keep less leading/trailing padding, but never remove it entirely.
        if start == 0:
            left, right = 0, min(retained // 2, stop - start)
        elif stop == len(signal):
            left, right = min(retained // 2, stop - start), 0
        else:
            left = retained // 2
            right = retained - left
        result.append(signal[cursor : start + left])
        cursor = stop - right

    if not result:
        return signal
    result.append(signal[cursor:])
    return np.concatenate(result)
