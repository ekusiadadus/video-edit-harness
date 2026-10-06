"""Deterministic encoded-RGB compositing from an explicit relative-depth map.

Depth values are caller-normalized to [0, 1], with larger values meaning
nearer picture content. This module performs no inference or segmentation.
"""

from __future__ import annotations

import math
import numpy as np


def _unit(value, name, *, positive=False):
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, (int, float, np.integer, np.floating)):
        raise ValueError(f'{name} must be a finite number in [0, 1]')
    try:
        number = float(value)
    except (OverflowError, ValueError):
        raise ValueError(f'{name} must be a finite number in [0, 1]') from None
    if not math.isfinite(number) or not (0 < number <= 1 if positive else 0 <= number <= 1):
        interval = '(0, 1]' if positive else '[0, 1]'
        raise ValueError(f'{name} must be a finite number in {interval}')
    return number


def _size(value, name):
    if type(value) is not int or value <= 0:
        raise ValueError(f'{name} must be a positive integer')
    return value


def _depth(depth_normalized, width, height):
    if (not isinstance(depth_normalized, np.ndarray) or depth_normalized.ndim != 2
            or depth_normalized.shape != (height, width)
            or not np.issubdtype(depth_normalized.dtype, np.floating)):
        raise ValueError('depth must be a same-canvas 2D floating array')
    if not np.isfinite(depth_normalized).all() or np.any(depth_normalized < 0) or np.any(depth_normalized > 1):
        raise ValueError('depth must contain finite normalized values in [0, 1]')
    return depth_normalized.astype(np.float64, copy=False)


def depth_visibility(depth_normalized, width, height, threshold=.5, softness=.1):
    """Return far-layer visibility: 1 far, 0 near, smoothstep at the boundary."""
    width = _size(width, 'width')
    height = _size(height, 'height')
    depth = _depth(depth_normalized, width, height)
    threshold = _unit(threshold, 'threshold')
    softness = _unit(softness, 'softness', positive=True)
    lower = threshold - softness / 2
    t = np.clip((depth - lower) / softness, 0.0, 1.0)
    return 1.0 - t * t * (3.0 - 2.0 * t)


def compose_depth_layer(rgb_uint8, depth_float, rgba_uint8, strength=1,
                        threshold=.5, softness=.1):
    """Place registered RGBA imagery behind nearer picture content.

    RGB arithmetic is performed on encoded 8-bit channel values and rounded
    half up. The original inputs are never modified.
    """
    if (not isinstance(rgb_uint8, np.ndarray) or rgb_uint8.dtype != np.uint8
            or rgb_uint8.ndim != 3 or rgb_uint8.shape[2] != 3
            or min(rgb_uint8.shape[:2]) <= 0):
        raise ValueError('base must be a nonempty HxWx3 uint8 RGB array')
    height, width = rgb_uint8.shape[:2]
    if (not isinstance(rgba_uint8, np.ndarray) or rgba_uint8.dtype != np.uint8
            or rgba_uint8.shape != (height, width, 4)):
        raise ValueError('layer must be a same-canvas HxWx4 uint8 RGBA array')
    strength = _unit(strength, 'strength')
    visibility = depth_visibility(depth_float, width, height, threshold, softness)
    alpha = rgba_uint8[..., 3].astype(np.float64) / 255.0 * visibility * strength
    output = (rgb_uint8.astype(np.float64) * (1.0 - alpha[..., None])
              + rgba_uint8[..., :3].astype(np.float64) * alpha[..., None])
    return np.clip(np.floor(output + .5), 0, 255).astype(np.uint8)
