"""Small, uncalibrated reference-relative measures for #20; no application imports."""

import re
from difflib import SequenceMatcher

import numpy as np
from scipy.signal import correlate, correlation_lags


def relative(value, reference):
    """GOP log-ratio relative to the original, capped at 100 (not calibrated)."""
    return float(100 * np.exp(min(0.0, value - reference)))


def gop(log_probs, expected, phone_ids):
    """Duration-normalized log posterior ratio to strongest competing PHONE.

    Exclude CTC blank/special tokens from the competitor set. Frames are those
    assigned to the expected phone by CTC Viterbi, not whole-word letter confidence.
    """
    competitors = [i for i in phone_ids if i != expected]
    return float(
        np.mean(log_probs[:, expected] - log_probs[:, competitors].max(axis=1))
    )


def matched_indices(reference, hypothesis):
    # Ordered text matches without a time cutoff; missing words stay missing.
    matcher = SequenceMatcher(None, reference, hypothesis, autojunk=False)
    return [
        (a + i, b + i) for a, b, n in matcher.get_matching_blocks() for i in range(n)
    ]


def timing(original, shadow):
    if len(original) < 2:
        return None
    original, shadow = np.asarray(original), np.asarray(shadow)
    lag = np.median(shadow - original)
    residual = np.mean(np.abs(shadow - original - lag))
    rate = (shadow[-1] - shadow[0]) / max(original[-1] - original[0], 0.01)
    # A 250 ms following lag is allowed; removing every constant lag hides late starts.
    penalty = max(0.0, abs(lag) - 0.25) + residual + 0.5 * abs(rate - 1)
    return float(100 * np.exp(-penalty))


def echo(original, shadow, rate=16000):
    """Waveform correlation +/-1.5 s; exact leakage screen, not acoustic AEC."""
    a, b = np.asarray(original)[::4], np.asarray(shadow)[::4]
    if not len(a) or not len(b):
        return 0.0
    a, b = a - a.mean(), b - b.mean()
    denom = np.linalg.norm(a) * np.linalg.norm(b)
    if denom == 0:
        return 0.0
    c = correlate(b, a, method="fft") / denom
    lag = correlation_lags(len(b), len(a))
    return float(np.max(np.abs(c[np.abs(lag) <= rate / 4 * 1.5])))


def filler_count(text):
    return len(re.findall(r"\b(?:um|uh|er|erm|like|you know)\b", text.lower()))


def fluency(original_gaps, shadow_gaps):
    if not len(original_gaps):
        return None
    extra = np.maximum(
        0, np.asarray(shadow_gaps) - np.asarray(original_gaps) - 0.15
    ).sum()
    return float(100 * np.exp(-extra))
