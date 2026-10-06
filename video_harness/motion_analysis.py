"""Local optical-flow evidence for manually selected regions of consecutive frames.

These thresholds are conservative heuristics, not action recognition, camera-motion
compensation, an edit decision, or human review. Image axes are right/down.
"""
from __future__ import annotations

from fractions import Fraction
import math

import numpy as np

from .tracking import _box, _corners, _cv2, _gray


_ALGORITHM = 'lk-roi-motion-v1'
_MIN_FEATURES = 8
_COS_45 = math.sqrt(.5)


def _rate(value):
    try:
        if isinstance(value, bool):
            raise ValueError
        if isinstance(value, (tuple, list)) and len(value) == 2:
            if any(isinstance(v, bool) or not isinstance(v, int) for v in value):
                raise ValueError
            rate = Fraction(*value)
        elif isinstance(value, (str, int, Fraction)):
            rate = Fraction(value)
        else:
            raise ValueError
    except (ValueError, TypeError, ZeroDivisionError, OverflowError) as exc:
        raise ValueError('fps must be a positive rational number') from exc
    if rate <= 0:
        raise ValueError('fps must be a positive rational number')
    return rate


def _uncertain_pair(index, count, accepted, reason):
    return {'from_frame': index, 'to_frame': index + 1,
            'feature_count': count, 'accepted_features': accepted,
            'dx_per_second': None, 'dy_per_second': None,
            'coherence': None, 'state': 'uncertain', 'reason': reason}


def _pair(first, second, box, fps, cv2, index):
    height, width = first.shape
    points = _corners(first, box, cv2)
    count = 0 if points is None else len(points)
    if count < _MIN_FEATURES:
        return _uncertain_pair(index, count, 0, 'insufficient_features')
    parameters = dict(winSize=(21, 21), maxLevel=3,
                      criteria=(cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 30, .01))
    forward, status, _ = cv2.calcOpticalFlowPyrLK(first, second, points, None, **parameters)
    if forward is None or status is None:
        return _uncertain_pair(index, count, 0, 'insufficient_flow')
    backward, reverse_status, _ = cv2.calcOpticalFlowPyrLK(second, first, forward, None, **parameters)
    if backward is None or reverse_status is None:
        return _uncertain_pair(index, count, 0, 'insufficient_flow')
    old = points.reshape(-1, 2)
    new = forward.reshape(-1, 2)
    returned = backward.reshape(-1, 2)
    valid = (status.reshape(-1) == 1) & (reverse_status.reshape(-1) == 1)
    valid &= np.isfinite(new).all(axis=1) & np.isfinite(returned).all(axis=1)
    valid &= np.linalg.norm(old - returned, axis=1) <= .75
    # A feature leaving the image cannot establish motion in the selected view.
    valid &= (new[:, 0] >= 0) & (new[:, 0] < width)
    valid &= (new[:, 1] >= 0) & (new[:, 1] < height)
    accepted = int(valid.sum())
    if accepted < _MIN_FEATURES or accepted < math.ceil(.35 * count):
        return _uncertain_pair(index, count, accepted, 'insufficient_flow')
    moves = new[valid].astype(np.float64) - old[valid].astype(np.float64)
    median = np.median(moves, axis=0)
    magnitude = float(np.linalg.norm(median))
    if magnitude < .5:
        return _uncertain_pair(index, count, accepted, 'low_motion')
    lengths = np.linalg.norm(moves, axis=1)
    aligned = lengths >= .5
    if not aligned.any():
        return _uncertain_pair(index, count, accepted, 'low_motion')
    cosine = np.sum(moves[aligned] * median, axis=1) / (lengths[aligned] * magnitude)
    coherence = float(np.mean(cosine >= _COS_45))
    if coherence < .75:
        result = _uncertain_pair(index, count, accepted, 'incoherent_flow')
        result['coherence'] = coherence
        return result
    return {'from_frame': index, 'to_frame': index + 1,
            'feature_count': count, 'accepted_features': accepted,
            'dx_per_second': float(median[0] / width * fps),
            'dy_per_second': float(median[1] / height * fps),
            'coherence': coherence, 'state': 'measured', 'reason': None}


def analyze_frames(frames, box, fps):
    """Measure pairwise normalized screen velocity in a fixed manual ROI.

    ``fps`` accepts Fraction, integer, rational string, or numerator/denominator
    pair. Frames are zero-indexed, consecutive RGB uint8 or grayscale uint8.
    Uncertain pairs are reseeded independently on the next source frame.
    """
    cv2 = _cv2()
    selected = _box(box)
    rate = _rate(fps)
    if isinstance(frames, np.ndarray) and frames.ndim >= 3:
        frames = list(frames)
    grays = []
    shape = channels = None
    for frame in frames:
        array = np.asarray(frame)
        current_channels = 1 if array.ndim == 2 else array.shape[2] if array.ndim == 3 else None
        if current_channels not in (1, 3):
            raise ValueError('frames must be consistently grayscale or RGB uint8')
        if channels is None:
            channels = current_channels
        elif current_channels != channels:
            raise ValueError('all frames must use the same color format')
        gray = _gray(array, cv2)
        if shape is None:
            shape = gray.shape
        elif gray.shape != shape:
            raise ValueError('all frames must have the same dimensions')
        grays.append(gray)
    if len(grays) < 2:
        raise ValueError('at least two consecutive frames are required')
    h, w = shape
    pairs = [_pair(grays[i], grays[i + 1], selected, float(rate), cv2, i)
             for i in range(len(grays) - 1)]
    measured = [row for row in pairs if row['state'] == 'measured']
    summary = {'state': 'uncertain', 'reason': 'insufficient_measured_pairs',
               'measured_pairs': len(measured), 'total_pairs': len(pairs),
               'dx_per_second': None, 'dy_per_second': None,
               'temporal_coherence': None}
    if len(measured) >= 2 and len(measured) / len(pairs) >= .75:
        velocities = np.array([[row['dx_per_second'], row['dy_per_second']]
                               for row in measured])
        vector = np.median(velocities, axis=0)
        magnitude = float(np.linalg.norm(vector))
        if magnitude > 0:
            lengths = np.linalg.norm(velocities, axis=1)
            aligned = np.sum(velocities * vector, axis=1) / (lengths * magnitude)
            coherence = float(np.mean(aligned >= _COS_45))
            summary['temporal_coherence'] = coherence
            if coherence >= .75:
                summary.update(state='measured', reason=None,
                               dx_per_second=float(vector[0]),
                               dy_per_second=float(vector[1]))
            else:
                summary['reason'] = 'incoherent_temporal_direction'
        else:
            summary['reason'] = 'low_motion'
    return {'version': 1, 'algorithm': _ALGORITHM, 'opencv_version': cv2.__version__,
            'fps': f'{rate.numerator}/{rate.denominator}',
            'dimensions': {'width': w, 'height': h}, 'box': selected,
            'pairs': pairs, 'summary': summary}


def compare_motion(left, right):
    """Compare two measured summaries; all unknowns remain uncertain."""
    result = {'classification': 'uncertain', 'reason': None,
              'cosine': None, 'angle_degrees': None, 'speed_ratio': None}
    for candidate in (left, right):
        if not isinstance(candidate, dict) or candidate.get('version') != 1 or candidate.get('algorithm') != _ALGORITHM:
            raise ValueError('expected lk-roi-motion-v1 analysis')
    if left.get('dimensions') != right.get('dimensions'):
        result['reason'] = 'different_dimensions'
        return result
    summaries = [candidate.get('summary') for candidate in (left, right)]
    if any(not isinstance(s, dict) or s.get('state') != 'measured' for s in summaries):
        result['reason'] = 'unmeasured_motion'
        return result
    vectors = []
    for summary in summaries:
        values = [summary.get('dx_per_second'), summary.get('dy_per_second')]
        if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in values):
            raise ValueError('measured velocities must be finite')
        vectors.append(np.array(values, dtype=np.float64))
    speeds = [float(np.linalg.norm(v)) for v in vectors]
    if not all(math.isfinite(speed) and speed > 0 for speed in speeds):
        result['reason'] = 'low_motion'
        return result
    cosine = float(np.clip(np.dot(*vectors) / (speeds[0] * speeds[1]), -1, 1))
    ratio = max(speeds) / min(speeds)
    result.update(cosine=cosine, angle_degrees=float(math.degrees(math.acos(cosine))),
                  speed_ratio=float(ratio), reason=None,
                  classification='compatible' if cosine >= _COS_45 and ratio <= 2.5 else 'incompatible')
    return result
