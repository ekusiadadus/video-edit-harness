"""Local, bounded motion-compensated smoothing of relative depth fields."""
from contextlib import contextmanager
from pathlib import Path
import math
import tempfile
import threading

import numpy as np

from .tracking import _cv2
from .transitions import _frames

MAX_FRAMES = 4096
ALGORITHM = 'farneback-fb-photo-v1'
BACKEND = 'opencv-cpu'
_OPENCV_LOCK = threading.RLock()


def temporal_config(strength, fb_tolerance, photometric_tolerance, min_coverage, cut_frames,
                    first, end):
    values = {'strength': strength, 'fb_tolerance': fb_tolerance,
              'photometric_tolerance': photometric_tolerance, 'min_coverage': min_coverage}
    for name, value in values.items():
        if (type(value) not in (int, float) or not math.isfinite(value)):
            raise ValueError('Depth temporal ' + name + ' must be a finite number')
    if not 0 < strength <= 1 or not 0 < fb_tolerance <= 8 or not 0 < photometric_tolerance <= .5 or not 0 < min_coverage <= 1:
        raise ValueError('Depth temporal parameters exceed bounded ranges')
    if (not isinstance(cut_frames, (list, tuple)) or any(type(x) is not int for x in cut_frames)
            or list(cut_frames) != sorted(set(cut_frames))
            or any(not first < x < end for x in cut_frames)):
        raise ValueError('Depth temporal cuts must be unique sorted source-frame IDs inside the interval')
    if end - first > MAX_FRAMES:
        raise ValueError('Depth temporal interval exceeds the bounded 4096-frame limit')
    return {'strength': float(strength), 'fb_tolerance': float(fb_tolerance),
            'photometric_tolerance': float(photometric_tolerance),
            'min_coverage': float(min_coverage), 'cut_frames': list(cut_frames)}


@contextmanager
def source_frames(source, first, end, width, height, log):
    # The transition decoder uses trim on actual source frames and no inferred alignment.
    indices = list(range(first, end))
    with _frames(source, indices, width, height, log) as iterator:
        yield iterator


@contextmanager
def fixed_opencv(cv2):
    """Bound local flow execution and restore process settings after replay."""
    with _OPENCV_LOCK:
        threads = cv2.getNumThreads()
        opencl = cv2.ocl.useOpenCL()
        try:
            cv2.setNumThreads(1)
            cv2.ocl.setUseOpenCL(False)
            yield
        finally:
            cv2.setNumThreads(threads)
            cv2.ocl.setUseOpenCL(opencl)


def stabilize_one(previous_rgb, current_rgb, previous_depth, current_depth, config, cv2):
    """Return a candidate and observed coverage; reject inconsistent/occluded pixels."""
    height, width = current_depth.shape
    previous_gray = cv2.cvtColor(np.ascontiguousarray(previous_rgb), cv2.COLOR_RGB2GRAY)
    current_gray = cv2.cvtColor(np.ascontiguousarray(current_rgb), cv2.COLOR_RGB2GRAY)
    options = dict(pyr_scale=.5, levels=3, winsize=15, iterations=3,
                   poly_n=5, poly_sigma=1.2, flags=0)
    backward = cv2.calcOpticalFlowFarneback(current_gray, previous_gray, None, **options)
    forward = cv2.calcOpticalFlowFarneback(previous_gray, current_gray, None, **options)
    yy, xx = np.mgrid[:height, :width].astype(np.float32)
    map_x, map_y = xx + backward[:, :, 0], yy + backward[:, :, 1]
    finite = np.isfinite(map_x) & np.isfinite(map_y)
    valid = finite & (map_x >= 0) & (map_x <= width-1) & (map_y >= 0) & (map_y <= height-1)
    safe_x = np.where(finite, map_x, -1).astype(np.float32)
    safe_y = np.where(finite, map_y, -1).astype(np.float32)
    sampled_forward = cv2.remap(forward, safe_x, safe_y, cv2.INTER_LINEAR,
                                borderMode=cv2.BORDER_CONSTANT, borderValue=0)
    fb_error = np.linalg.norm(backward + sampled_forward, axis=2)
    previous_warped = cv2.remap(previous_gray, safe_x, safe_y, cv2.INTER_LINEAR,
                                borderMode=cv2.BORDER_CONSTANT, borderValue=0)
    photo_error = np.abs(previous_warped.astype(np.float32) - current_gray.astype(np.float32)) / 255
    valid &= np.isfinite(fb_error) & (fb_error <= config['fb_tolerance'])
    valid &= photo_error <= config['photometric_tolerance']
    # Dense flow in a flat region can be numerically consistent while conveying
    # no motion evidence. Require observed local texture on both sides.
    def texture(gray):
        image = gray.astype(np.float32)
        mean = cv2.boxFilter(image, -1, (7, 7), normalize=True)
        variance = cv2.boxFilter(image * image, -1, (7, 7), normalize=True) - mean * mean
        return variance > 9
    prior_texture = cv2.remap(texture(previous_gray).astype(np.uint8), safe_x, safe_y,
                             cv2.INTER_NEAREST, borderMode=cv2.BORDER_CONSTANT, borderValue=0)
    valid &= texture(current_gray) & (prior_texture > 0)
    coverage = float(np.count_nonzero(valid) / valid.size)
    if coverage < config['min_coverage']:
        return current_depth.copy(), coverage, 'low_valid_coverage'
    old = cv2.remap(previous_depth, safe_x, safe_y, cv2.INTER_LINEAR,
                    borderMode=cv2.BORDER_CONSTANT, borderValue=0)
    output = current_depth.copy()
    strength = config['strength']
    output[valid] = ((1-strength) * current_depth[valid] + strength * old[valid]).astype(np.float32)
    np.clip(output, 0, 1, out=output)
    return output, coverage, None


def replay_temporal(parent, config, *, log=None):
    """Yield actual derived arrays and observations with only one frame of history."""
    from .depth_artifact import _field
    cv2 = _cv2()
    first, end = parent['start_frame'], parent['end_frame_exclusive']
    config = temporal_config(**config, first=first, end=end)
    if log is None:
        with tempfile.TemporaryDirectory(prefix='depth-temporal-validate-') as temporary:
            yield from replay_temporal(parent, config, log=Path(temporary)/'decode.log')
        return
    cut_frames = set(config['cut_frames'])
    with fixed_opencv(cv2):
        with source_frames(parent['source']['path'], first, end, parent['width'], parent['height'], log) as frames:
            previous_rgb = previous_depth = None
            for row, rgb in zip(parent['rows'], frames):
                frame = row['frame']
                current = np.array(_field(row['field']['path'], parent['width'], parent['height']), copy=True)
                if previous_rgb is None:
                    result, coverage, reset = current, 0.0, 'interval_start'
                elif frame in cut_frames:
                    result, coverage, reset = current, 0.0, 'declared_cut'
                else:
                    result, coverage, reset = stabilize_one(previous_rgb, rgb, previous_depth,
                                                            current, config, cv2)
                observation = {'frame': frame, 'valid_coverage': coverage, 'reset_reason': reset}
                yield result, observation
                previous_rgb, previous_depth = np.array(rgb, copy=True), result


def stabilize_depth(manifest, output, actor, reason, *, strength=.5, fb_tolerance=1.0,
                    photometric_tolerance=.08, min_coverage=.5, cut_frames=()):
    """Public temporal entry point, kept lazy to avoid artifact import cycles."""
    from .depth_artifact import stabilize_depth as create
    return create(manifest, output, actor, reason, strength=strength,
                  fb_tolerance=fb_tolerance, photometric_tolerance=photometric_tolerance,
                  min_coverage=min_coverage, cut_frames=cut_frames)
