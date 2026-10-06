"""Original-clock audio repeats and the mixer's existing seam taper."""

import math

import numpy as np


def loop_pcm(chunk, target, *, capture_gain=False):
    if (not isinstance(chunk, np.ndarray) or chunk.dtype != np.float32 or
            chunk.ndim != 2 or not len(chunk) or not np.all(np.isfinite(chunk)) or
            type(target) is not int or target <= 0):
        raise ValueError('Loop audio requires finite float32 PCM and a positive sample count')
    clip = np.tile(chunk, (math.ceil(target / len(chunk)), 1))[:target].copy()
    taper = min(480, len(chunk) // 4)
    gain = np.ones(target, dtype=np.float32) if capture_gain else None
    if taper:
        for seam in range(len(chunk), target, len(chunk)):
            left = min(taper, seam)
            right = min(taper, target - seam)
            left_taper = np.linspace(1, 0, left, dtype=np.float32)
            right_taper = np.linspace(0, 1, right, dtype=np.float32)
            clip[seam-left:seam] *= left_taper[:, None]
            clip[seam:seam+right] *= right_taper[:, None]
            if gain is not None:
                gain[seam-left:seam] *= left_taper
                gain[seam:seam+right] *= right_taper
    return clip, gain, taper
