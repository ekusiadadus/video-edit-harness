"""Measured scalar relationship between two native 48 kHz stereo WAV files.

This checks decoded samples, not normalizer internals, target loudness, exact
PCM identity, or FCP playback parity.
"""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np

from . import audio_mix
from .audio_envelopes import file_identity
from .common import probe


RATE = 48000
CHANNELS = 2


def _native_audio(path):
    info = probe(path)
    streams = [row for row in info.get("streams", []) if row.get("codec_type") == "audio"]
    format_names = str(info.get("format", {}).get("format_name", "")).split(",")
    if ("wav" not in format_names or len(streams) != 1 or
            str(streams[0].get("sample_rate")) != str(RATE) or
            type(streams[0].get("channels")) is not int or
            streams[0]["channels"] != CHANNELS):
        raise ValueError("normalization proof requires native 48 kHz stereo WAV")


def prove_scalar_normalization(input_wav, output_wav, *, absolute_error=2e-6):
    """Return path-free proof of a bounded common sample gain, when observed.

    Both channels and every decoded sample share one least-squares scalar.
    Silence-to-silence uses unity; silence-to-sound has no defined scalar and
    is reported as non-scalar with ``scalar_gain=None``.
    """
    if type(absolute_error) not in (int, float) or not math.isfinite(absolute_error) or absolute_error < 0:
        raise ValueError("absolute_error must be finite and nonnegative")
    source_path = Path(input_wav)
    result_path = Path(output_wav)
    source_fp = file_identity(source_path)
    result_fp = file_identity(result_path)
    _native_audio(source_path)
    _native_audio(result_path)
    source = audio_mix._decode(source_path)
    result = audio_mix._decode(result_path)
    if file_identity(source_path) != source_fp or file_identity(result_path) != result_fp:
        raise ValueError("normalization proof input changed during decode")
    if (source.ndim != 2 or result.ndim != 2 or source.shape[1] != CHANNELS or
            result.shape[1] != CHANNELS or len(source) == 0 or len(result) == 0):
        raise ValueError("normalization proof requires nonempty stereo audio")
    if len(source) != len(result):
        raise ValueError("normalization proof sample counts differ")
    if not np.all(np.isfinite(source)) or not np.all(np.isfinite(result)):
        raise ValueError("normalization proof audio must be finite")

    x = source.astype(np.float64).reshape(-1)
    y = result.astype(np.float64).reshape(-1)
    denominator = float(np.dot(x, x))
    if denominator == 0:
        if np.all(y == 0):
            gain = 1.0
            maximum = 0.0
            rms = 0.0
            status = "verified_scalar"
            reason = "Both decoded WAVs are exactly silent; unity is a valid scalar."
        else:
            gain = None
            maximum = float(np.max(np.abs(y)))
            rms = float(np.sqrt(np.mean(np.square(y))))
            status = "non_scalar"
            reason = "Silent input produced nonzero output; no scalar can explain it."
    else:
        gain = max(0.0, float(np.dot(x, y) / denominator))
        if not math.isfinite(gain):
            raise ValueError("normalization proof scalar is non-finite")
        residual = y - x * gain
        maximum = float(np.max(np.abs(residual)))
        rms = float(np.sqrt(np.mean(np.square(residual))))
        status = "verified_scalar" if maximum <= absolute_error else "non_scalar"
        reason = ("A single measured nonnegative scalar explains every decoded sample within tolerance."
                  if status == "verified_scalar" else
                  "No single nonnegative scalar explains every decoded sample within tolerance.")
    if file_identity(source_path) != source_fp or file_identity(result_path) != result_fp:
        raise ValueError("normalization proof input changed during analysis")
    return {"version": 1, "sample_rate": RATE, "channels": CHANNELS,
            "input": source_fp, "output": result_fp, "samples": len(source),
            "absolute_error_tolerance": float(absolute_error),
            "scalar_gain": gain, "max_absolute_error": maximum, "rms_error": rms,
            "status": status, "decision_reason": reason, "actor": "automation"}
