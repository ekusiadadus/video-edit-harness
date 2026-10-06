"""Bounded conversion of measured sample gains to editable volume keyframes.

Segments assume linear interpolation in dB, as expressed in the generated
FCPXML. An FCP GUI import/playback calibration is still required to confirm
that Final Cut Pro evaluates these points the same way.
"""

from __future__ import annotations

from fractions import Fraction
import math

import numpy as np


RATE = 48000
ZERO_FLOOR_DB = -96.0
MAX_DB = 24.0
_ZERO_GAIN = 10 ** (ZERO_FLOOR_DB / 20)
_MAX_GAIN = 10 ** (MAX_DB / 20)
_MIN_EVALUATION_BUDGET = 50_000_000


def _time(value):
    return f"{value.numerator}s" if value.denominator == 1 else f"{value.numerator}/{value.denominator}s"


def _segment_error(gain, db, first, last):
    """Return the maximum *linear gain* residual and its sample index."""
    if first == last:
        return abs(float(gain[first]) - 10 ** (float(db[first]) / 20)), first
    samples = np.arange(first, last + 1, dtype=np.float64)
    fraction = (samples - first) / (last - first)
    estimated_db = float(db[first]) + fraction * (float(db[last]) - float(db[first]))
    estimated = np.power(10.0, estimated_db / 20.0)
    residual = np.abs(estimated - gain[first:last + 1])
    local = int(np.argmax(residual))
    return float(residual[local]), first + local


def compile_gain_keyframes(curve, *, source_start=Fraction(0), sample_rate=RATE,
                           scalar_gain=1.0, absolute_error=2e-5, max_keyframes=20000):
    """Approximate each measured sample within ``absolute_error`` linear gain.

    ``curve`` is a cue-local, nonnegative sample gain before the common peak
    guard. ``scalar_gain`` applies that guard or another common linear scalar.
    Points include the first and last samples, with exact source-clock times.
    There is no silent quality reduction: impossible error or point limits fail.
    """
    if type(sample_rate) is not int or sample_rate != RATE:
        raise ValueError("unsupported sample rate")
    if type(max_keyframes) is not int or max_keyframes < 1:
        raise ValueError("max_keyframes must be positive")
    if type(scalar_gain) not in (int, float) or not math.isfinite(scalar_gain) or scalar_gain < 0:
        raise ValueError("scalar_gain must be finite and nonnegative")
    if type(absolute_error) not in (int, float) or not math.isfinite(absolute_error) or absolute_error < 0:
        raise ValueError("absolute_error must be finite and nonnegative")
    try:
        start = Fraction(str(source_start))
    except (TypeError, ValueError, ZeroDivisionError) as exc:
        raise ValueError("invalid source_start") from exc
    if start < 0:
        raise ValueError("source_start must be nonnegative")
    try:
        raw = np.asarray(curve)
    except (TypeError, ValueError) as exc:
        raise ValueError("invalid gain curve") from exc
    if raw.ndim != 1 or raw.size == 0 or raw.dtype.kind not in "iuf":
        raise ValueError("gain curve must be a nonempty numeric vector")
    gain = raw.astype(np.float64)
    if not np.all(np.isfinite(gain)) or np.any(gain < 0):
        raise ValueError("gain curve must be finite and nonnegative")
    gain *= float(scalar_gain)
    if not np.all(np.isfinite(gain)) or np.any(gain > _MAX_GAIN):
        raise ValueError("gain exceeds the +24 dB FCP limit")

    # The export uses six decimal places of dB. Build from the exact serialized
    # values so the error test covers quantization and the -96 dB zero floor.
    db = np.round(20 * np.log10(np.maximum(gain, _ZERO_GAIN)), 6)
    if np.any(db > MAX_DB):
        raise ValueError("gain exceeds the +24 dB FCP limit")
    endpoint_error = np.abs(np.power(10.0, db[[0, -1]] / 20) - gain[[0, -1]])
    if np.any(endpoint_error > absolute_error):
        raise ValueError("gain cannot meet absolute error at the -96 dB floor")

    last = len(gain) - 1
    indices = {0, last}
    if len(indices) > max_keyframes:
        raise ValueError("gain needs more than max_keyframes")
    stack = [(0, last)] if last else []
    maximum_error = float(np.max(endpoint_error))
    # A maximally jagged curve can force edge splits and quadratic rescanning.
    # Reject that case explicitly instead of hanging or relaxing the error.
    evaluation_budget = max(_MIN_EVALUATION_BUDGET, 16 * len(gain))
    evaluated_samples = 0
    while stack:
        first, end = stack.pop()
        evaluated_samples += end - first + 1
        if evaluated_samples > evaluation_budget:
            raise ValueError("gain exceeds sample evaluation budget")
        error, offending = _segment_error(gain, db, first, end)
        if error <= absolute_error:
            maximum_error = max(maximum_error, error)
            continue
        if offending == first or offending == end:
            raise ValueError("gain cannot meet absolute error at a keyframe")
        indices.add(offending)
        if len(indices) > max_keyframes:
            raise ValueError("gain needs more than max_keyframes")
        stack.append((offending, end))
        stack.append((first, offending))

    keyframes = []
    for sample in sorted(indices):
        keyframes.append({"sample": sample,
                          "time": _time(start + Fraction(sample, sample_rate)),
                          "value": f"{db[sample]:.6f}dB",
                          "interp": "linear", "curve": "linear"})
    return {"keyframes": keyframes, "samples": len(gain), "sample_rate": sample_rate,
            "zero_floor_db": ZERO_FLOOR_DB,
            "max_absolute_gain_error": maximum_error,
            "scalar_gain": float(scalar_gain)}
