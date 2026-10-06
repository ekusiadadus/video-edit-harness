"""Optional, pose-associated subject masks from a local MediaPipe task model.

The masks are binary review aids. Pose indices only associate each result's
landmarks and mask within one frame; identity still requires reliable torso
landmarks and an unambiguous manual seed or continuous pose.
"""
from __future__ import annotations

from fractions import Fraction
import math
from pathlib import Path

import numpy as np

from .tracking import _box
from .tracking_pose import _candidate, _select


def _mask_array(mask, shape, threshold):
    """Return a full-size binary mask, or None for unusable probabilities."""
    try:
        data = np.asarray(mask.numpy_view())
    except (AttributeError, TypeError, ValueError):
        return None
    if data.shape == (*shape, 1):
        data = data[:, :, 0]
    if data.shape != shape or data.dtype.kind != 'f':
        return None
    if not np.isfinite(data).all() or np.any((data < 0) | (data > 1)):
        return None
    return np.asarray(data >= threshold, dtype=np.uint8)


def segment_frames_pose(frames, initial_box, model_path, fps, corrections=None,
                        num_poses=6, threshold=.5):
    """Return one row per RGB frame, with a mask only for a selected pose.

    A lost row stays lost until an explicit correction. A missing or malformed
    segmentation result loses the frame, never silently substitutes another
    pose's mask or a rectangular selection.
    """
    initial = _box(initial_box)
    if corrections is None:
        corrections = {}
    if not isinstance(corrections, dict) or any(type(k) is not int or k < 0 for k in corrections):
        raise ValueError('corrections must map nonnegative integer frames to boxes')
    corrections = {k: _box(v) for k, v in corrections.items()}
    if type(num_poses) is not int or num_poses < 1:
        raise ValueError('num_poses must be a positive integer')
    if isinstance(threshold, bool) or not isinstance(threshold, (int, float)) or not math.isfinite(threshold) or not 0 < threshold < 1:
        raise ValueError('threshold must be finite and strictly between 0 and 1')
    try:
        rate = Fraction(fps)
    except (TypeError, ValueError, ZeroDivisionError, OverflowError) as exc:
        raise ValueError('fps must be a positive finite rate no greater than 1000') from exc
    if not 0 < rate <= 1000:
        raise ValueError('fps must be a positive finite rate no greater than 1000')
    model = Path(model_path)
    if not model.is_file():
        raise ValueError('model_path must be an existing local task model')
    try:
        import mediapipe as mp
    except ImportError as exc:
        raise RuntimeError('Semantic masks need MediaPipe: install the tracking dependency') from exc

    options = mp.tasks.vision.PoseLandmarkerOptions(
        base_options=mp.tasks.BaseOptions(model_asset_path=str(model),
                                          delegate=mp.tasks.BaseOptions.Delegate.CPU),
        running_mode=mp.tasks.vision.RunningMode.VIDEO,
        num_poses=num_poses,
        output_segmentation_masks=True)

    rows = []
    previous = None
    dimensions = None
    prior_timestamp = -1
    with mp.tasks.vision.PoseLandmarker.create_from_options(options) as landmarker:
        for index, frame in enumerate(frames):
            array = np.asarray(frame)
            if array.dtype != np.uint8 or array.ndim != 3 or array.shape[2] != 3 or min(array.shape[:2]) < 8:
                raise ValueError('frames must be RGB uint8 arrays at least 8 pixels wide and high')
            if dimensions is None:
                dimensions = array.shape
            elif array.shape != dimensions:
                raise ValueError('all frames must have the same dimensions')
            timestamp = round(Fraction(index * 1000, 1) / rate)
            if timestamp <= prior_timestamp:
                raise ValueError('frame timestamps must strictly increase')
            prior_timestamp = timestamp
            image = mp.Image(image_format=mp.ImageFormat.SRGB, data=np.ascontiguousarray(array))
            result = landmarker.detect_for_video(image, timestamp)
            poses = getattr(result, 'pose_landmarks', None)
            masks = getattr(result, 'segmentation_masks', None)
            manual = index == 0 or index in corrections
            reason = None
            if poses is None or masks is None or len(poses) != len(masks):
                reason = 'missing_or_mismatched_segmentation_masks'
            else:
                # Keep original result indices through reliability filtering.
                binary = [_mask_array(mask, dimensions[:2], threshold) for mask in masks]
                if any(mask is None for mask in binary):
                    reason = 'invalid_segmentation_mask'
                else:
                    candidates = []
                    for pose_index, pose in enumerate(poses):
                        candidate = _candidate(pose)
                        if candidate is not None:
                            candidates.append({**candidate, 'pose_index': pose_index})
                    selected, reason = _select(
                        candidates,
                        seed_box=corrections.get(index, initial) if manual else None,
                        previous=previous)
            if reason is not None:
                previous = None
                rows.append({'frame': index, 'state': 'lost', 'box': None,
                             'quality': {'reason': reason}, 'mask': None})
            else:
                previous = selected
                rows.append({'frame': index, 'state': 'manual' if manual else 'tracked',
                             'box': selected['box'], 'mask': binary[selected['pose_index']],
                             'quality': {'pose_geometry': 'torso_landmarks',
                                         'min_visibility': selected['min_visibility'],
                                         'min_presence': selected['min_presence'],
                                         'association_kind': selected['association_kind'],
                                         'association_score': selected['association_score'],
                                         'pose_index': selected['pose_index']}})
    if not rows:
        raise ValueError('frames must contain at least one frame')
    if any(k >= len(rows) for k in corrections):
        raise ValueError('correction frame outside supplied frames')
    return rows
