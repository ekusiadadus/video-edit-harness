"""Local MediaPipe pose tracking with explicit seed and sticky identity loss.

Pose indices are per-frame detections, not person identities. The returned torso
boxes and geometric scores are review aids, not probabilities of identity.
"""
from __future__ import annotations

from fractions import Fraction
import math
from pathlib import Path

import numpy as np

from .tracking import _box


_TORSO = (11, 12, 23, 24)  # shoulders and hips


def _candidate(landmarks):
    """Extract a reliable normalized torso or reject a partial/uncertain pose."""
    if len(landmarks) <= max(_TORSO):
        return None
    points = []
    confidences = []
    for index in _TORSO:
        point = landmarks[index]
        values = (getattr(point, 'x', None), getattr(point, 'y', None),
                  getattr(point, 'visibility', None), getattr(point, 'presence', None))
        if any(isinstance(value, bool) or not isinstance(value, (int, float)) for value in values):
            return None
        x, y, visibility, presence = map(float, values)
        if not all(map(math.isfinite, (x, y, visibility, presence))):
            return None
        if not (.5 <= visibility <= 1 and .5 <= presence <= 1) or not (-.05 <= x <= 1.05 and -.05 <= y <= 1.05):
            return None
        confidences.append((visibility, presence))
        points.append((min(1., max(0., x)), min(1., max(0., y))))
    xs, ys = zip(*points)
    box = [min(xs), min(ys), max(xs), max(ys)]
    if box[2] - box[0] < .015 or box[3] - box[1] < .015:
        return None
    shoulder_mid = ((points[0][0] + points[1][0]) / 2, (points[0][1] + points[1][1]) / 2)
    hip_mid = ((points[2][0] + points[3][0]) / 2, (points[2][1] + points[3][1]) / 2)
    torso_length = math.dist(shoulder_mid, hip_mid)
    if torso_length < .015:
        return None
    return {'box': box, 'center': ((sum(xs) / 4), (sum(ys) / 4)),
            'geometry': (torso_length, math.hypot(box[2] - box[0], box[3] - box[1])),
            'min_visibility': min(v for v, _ in confidences),
            'min_presence': min(p for _, p in confidences)}


def _intersection(a, b):
    return max(0., min(a[2], b[2]) - max(a[0], b[0])) * max(0., min(a[3], b[3]) - max(a[1], b[1]))


def _select(candidates, *, seed_box=None, previous=None):
    """Return (candidate, reason), rejecting comparable matches explicitly."""
    if seed_box is not None:
        sx = (seed_box[0] + seed_box[2]) / 2
        sy = (seed_box[1] + seed_box[3]) / 2
        seed_area = (seed_box[2] - seed_box[0]) * (seed_box[3] - seed_box[1])
        ranked = []
        for candidate in candidates:
            box = candidate['box']
            cx, cy = candidate['center']
            overlap = _intersection(seed_box, box) / seed_area
            contains = box[0] <= sx <= box[2] and box[1] <= sy <= box[3]
            # A small clothing selection may overlap just part of the torso.
            if overlap >= .12 or contains:
                ranked.append((overlap + (0.5 if contains else 0.), candidate))
        ranked.sort(key=lambda entry: entry[0], reverse=True)
        if not ranked:
            return None, 'no_pose_in_manual_box'
        if len(ranked) > 1 and ranked[1][0] >= ranked[0][0] * .75:
            return None, 'ambiguous_manual_box'
        return {**ranked[0][1], 'association_score': ranked[0][0],
                'association_kind': 'seed_overlap'}, None

    if previous is None:
        return None, 'awaiting_manual_correction'
    px, py = previous['center']
    pw = previous['box'][2] - previous['box'][0]
    ph = previous['box'][3] - previous['box'][1]
    previous_geometry = previous['geometry']
    # Keep the original strict, axis-normalized center-motion gate. Only the
    # scale check uses rotation-tolerant torso length and overall extent.
    ranked = []
    for candidate in candidates:
        cx, cy = candidate['center']
        distance = math.hypot((cx - px) / max(.05, pw), (cy - py) / max(.05, ph))
        scale = max(max(a / b, b / a) for a, b in zip(candidate['geometry'], previous_geometry))
        if distance <= .65 and scale <= 1.65:
            ranked.append((distance + .15 * (scale - 1), candidate))
    ranked.sort(key=lambda entry: entry[0])
    if not ranked:
        return None, 'no_continuous_pose'
    # Two bodies at similar positions are not distinguishable by pose geometry.
    if len(ranked) > 1 and ranked[1][0] - ranked[0][0] < .25:
        return None, 'ambiguous_pose'
    return {**ranked[0][1], 'association_score': ranked[0][0],
            'association_kind': 'torso_distance'}, None


def _rows_from_detections(detections, initial_box, corrections=None):
    """Pure selection path for synthetic multi-person/crossing tests."""
    initial = _box(initial_box)
    if corrections is None:
        corrections = {}
    if not isinstance(corrections, dict) or any(type(k) is not int or k < 0 for k in corrections):
        raise ValueError('corrections must map nonnegative integer frames to boxes')
    corrections = {k: _box(v) for k, v in corrections.items()}
    rows = []
    previous = None
    for index, poses in enumerate(detections):
        manual = index == 0 or index in corrections
        candidates = [candidate for pose in poses if (candidate := _candidate(pose)) is not None]
        selected, reason = _select(candidates, seed_box=corrections.get(index, initial) if manual else None,
                                   previous=previous)
        if selected is None:
            previous = None
            rows.append({'frame': index, 'box': None, 'state': 'lost', 'quality': {'reason': reason}})
        else:
            previous = selected
            rows.append({'frame': index, 'box': selected['box'],
                         'state': 'manual' if manual else 'tracked',
                         'quality': {'pose_geometry': 'torso_landmarks',
                                     'min_visibility': selected['min_visibility'],
                                     'min_presence': selected['min_presence'],
                                     'association_kind': selected['association_kind'],
                                     'association_score': selected['association_score']}})
    if not rows:
        raise ValueError('frames must contain at least one frame')
    if any(k >= len(rows) for k in corrections):
        raise ValueError('correction frame outside supplied frames')
    return rows


def track_frames_pose(frames, initial_box, model_path, fps, corrections=None, num_poses=6):
    """Detect poses in consecutive RGB frames with a local MediaPipe task model."""
    _box(initial_box)
    if type(num_poses) is not int or num_poses < 1:
        raise ValueError('num_poses must be a positive integer')
    try:
        rate = Fraction(fps)
    except (TypeError, ValueError, ZeroDivisionError) as exc:
        raise ValueError('fps must be a positive finite rate no greater than 1000') from exc
    if not 0 < rate <= 1000:
        raise ValueError('fps must be a positive rate no greater than 1000')
    model = Path(model_path)
    if not model.is_file():
        raise ValueError('model_path must be an existing local task model')
    try:
        import mediapipe as mp
    except ImportError as exc:
        raise RuntimeError('Pose tracking needs MediaPipe: install the tracking dependency') from exc

    options = mp.tasks.vision.PoseLandmarkerOptions(
        base_options=mp.tasks.BaseOptions(model_asset_path=str(model),
                                          delegate=mp.tasks.BaseOptions.Delegate.CPU),
        running_mode=mp.tasks.vision.RunningMode.VIDEO,
        num_poses=num_poses)

    def detections(landmarker):
        dimensions = None
        prior_timestamp = -1
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
            yield landmarker.detect_for_video(image, timestamp).pose_landmarks

    with mp.tasks.vision.PoseLandmarker.create_from_options(options) as landmarker:
        return _rows_from_detections(detections(landmarker), initial_box, corrections)
