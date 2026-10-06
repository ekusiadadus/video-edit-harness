"""Local, manually seeded picture tracking. All boxes use normalized coordinates.

This is an aid for proposing an edit, not an object detector or an approval of
the resulting crop. Loss is sticky until an explicit correction is supplied.
"""
from __future__ import annotations

import json
import math
from pathlib import Path
import subprocess

import numpy as np


def _cv2():
    try:
        import cv2
    except ImportError as exc:
        raise RuntimeError('Object tracking needs OpenCV: install with uv sync --extra tracking') from exc
    return cv2


def _box(value):
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        raise ValueError('box must have four normalized coordinates')
    if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in value):
        raise ValueError('box coordinates must be finite numbers')
    x0, y0, x1, y1 = map(float, value)
    if not (0 <= x0 < x1 <= 1 and 0 <= y0 < y1 <= 1):
        raise ValueError('box must have positive area inside the frame')
    return [x0, y0, x1, y1]


def _gray(frame, cv2):
    array = np.asarray(frame)
    if array.dtype != np.uint8 or array.ndim not in (2, 3):
        raise ValueError('frames must be uint8 grayscale, RGB or RGBA arrays')
    if array.ndim == 2:
        gray = array
    elif array.shape[2] == 3:
        gray = cv2.cvtColor(array, cv2.COLOR_RGB2GRAY)
    elif array.shape[2] == 4:
        gray = cv2.cvtColor(array, cv2.COLOR_RGBA2GRAY)
    else:
        raise ValueError('frames must be uint8 grayscale, RGB or RGBA arrays')
    if min(gray.shape) < 8:
        raise ValueError('frame dimensions must be at least 8 pixels')
    return np.ascontiguousarray(gray)


def _corners(gray, box, cv2):
    h, w = gray.shape
    x0, y0, x1, y1 = box
    left, top = math.ceil(x0 * w), math.ceil(y0 * h)
    right, bottom = math.floor(x1 * w), math.floor(y1 * h)
    if right - left < 8 or bottom - top < 8:
        return None
    roi = gray[top:bottom, left:right]
    if float(roi.std()) < 7:
        return None
    mask = np.zeros_like(gray)
    mask[top:bottom, left:right] = 255
    points = cv2.goodFeaturesToTrack(gray, maxCorners=120, qualityLevel=.01,
                                      minDistance=3, mask=mask, blockSize=3)
    return points if points is not None and len(points) >= 6 else None


def _lost(index, reason, count=0):
    return {'frame': index, 'box': None, 'state': 'lost',
            'quality': {'reason': reason, 'feature_count': int(count)}}


def track_frames(frames, initial_box, corrections=None):
    """Track consecutive frames; corrections map zero-based frame indices to boxes."""
    cv2 = _cv2()
    initial = _box(initial_box)
    if corrections is None:
        corrections = {}
    if not isinstance(corrections, dict) or any(type(k) is not int or k < 0 for k in corrections):
        raise ValueError('corrections must map nonnegative integer frames to boxes')
    corrections = {k: _box(v) for k, v in corrections.items()}
    rows = []
    previous = points = current_box = None
    dimensions = None
    for index, frame in enumerate(frames):
        gray = _gray(frame, cv2)
        if dimensions is None:
            dimensions = gray.shape
        elif gray.shape != dimensions:
            raise ValueError('all frames must have the same dimensions')
        if index == 0 or index in corrections:
            selected = corrections.get(index, initial)
            points = _corners(gray, selected, cv2)
            if points is None:
                current_box = None
                rows.append(_lost(index, 'featureless_manual_box'))
            else:
                current_box = selected
                rows.append({'frame': index, 'box': selected, 'state': 'manual',
                             'quality': {'feature_count': len(points)}})
            previous = gray
            continue
        if current_box is None:
            rows.append(_lost(index, 'awaiting_manual_correction'))
            previous = gray
            continue
        next_points, status, errors = cv2.calcOpticalFlowPyrLK(
            previous, gray, points, None, winSize=(21, 21), maxLevel=3,
            criteria=(cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 30, .01))
        valid = (status is not None and next_points is not None and errors is not None)
        if valid:
            keep = (status.reshape(-1) == 1) & np.isfinite(errors.reshape(-1))
            keep &= errors.reshape(-1) < 35
            keep &= np.isfinite(next_points.reshape(-1, 2)).all(axis=1)
            old = points.reshape(-1, 2)[keep]
            new = next_points.reshape(-1, 2)[keep]
        else:
            old = new = np.empty((0, 2), dtype=np.float32)
        if len(old) < 6 or len(old) < max(6, len(points) * .35):
            rows.append(_lost(index, 'insufficient_optical_flow', len(old)))
            current_box = None
            previous = gray
            continue
        matrix, inliers = cv2.estimateAffinePartial2D(
            old, new, method=cv2.RANSAC, ransacReprojThreshold=2.5)
        fraction = float(inliers.mean()) if inliers is not None else 0.0
        if matrix is None or not np.isfinite(matrix).all() or fraction < .6:
            rows.append(_lost(index, 'inconsistent_motion', len(old)))
            current_box = None
            previous = gray
            continue
        h, w = gray.shape
        scale = math.hypot(float(matrix[0, 0]), float(matrix[0, 1]))
        if not .7 <= scale <= 1.4:
            rows.append(_lost(index, 'implausible_scale', len(old)))
            current_box = None
            previous = gray
            continue
        x0, y0, x1, y1 = current_box
        corners = np.array([[x0*w, y0*h, 1], [x1*w, y0*h, 1],
                            [x1*w, y1*h, 1], [x0*w, y1*h, 1]])
        moved = corners @ matrix.T
        box = [float(moved[:, 0].min()/w), float(moved[:, 1].min()/h),
               float(moved[:, 0].max()/w), float(moved[:, 1].max()/h)]
        if not (0 <= box[0] < box[2] <= 1 and 0 <= box[1] < box[3] <= 1):
            rows.append(_lost(index, 'out_of_frame', len(old)))
            current_box = None
            previous = gray
            continue
        # Compare source appearance under the observed transform. A flat or
        # occluded destination can retain plausible optical flow coordinates.
        warped = cv2.warpAffine(previous, matrix, (w, h))
        left, top, right, bottom = (max(0, int(box[0]*w)), max(0, int(box[1]*h)),
                                    min(w, int(box[2]*w)), min(h, int(box[3]*h)))
        sample = gray[top:bottom, left:right]
        reference = warped[top:bottom, left:right]
        mismatch = float(np.mean(np.abs(sample.astype(np.float32) - reference.astype(np.float32)))) / 255 if sample.size else 1.0
        if mismatch > .20 or float(sample.std()) < 5:
            rows.append(_lost(index, 'appearance_mismatch', len(old)))
            current_box = None
            previous = gray
            continue
        current_box = box
        refreshed = _corners(gray, box, cv2)
        if refreshed is None:
            rows.append(_lost(index, 'insufficient_features', len(old)))
            current_box = None
        else:
            points = refreshed
            rows.append({'frame': index, 'box': box, 'state': 'tracked',
                         'quality': {'feature_count': len(old), 'inlier_fraction': fraction,
                                     'appearance_mae': mismatch}})
        previous = gray
    if not rows:
        raise ValueError('frames must contain at least one frame')
    if any(k >= len(rows) for k in corrections):
        raise ValueError('correction frame outside supplied frames')
    return rows


def track_video(source, initial_box, output, start_frame=0, end_frame=None,
                corrections=None, max_width=640, algorithm='lk', model_path=None,
                actor='automation', reason='Local tracking proposal from an explicit box'):
    """Stream a verified CFR source through FFmpeg and write a new JSON proposal."""
    from .video_effects import _probe, _sha, _stream, _verified_rate

    _box(initial_box)
    if actor not in {'human','codex','claude_code','automation'} or not isinstance(reason,str) or not reason.strip():
        raise ValueError('Tracking needs a real actor and decision reason')
    if algorithm not in {'lk', 'csrt', 'pose'}:
        raise ValueError('Unsupported tracking algorithm')
    model=None
    if algorithm=='pose':
        if model_path is None or not Path(model_path).is_file():
            raise ValueError('Pose tracking needs an explicitly supplied local model')
        model={'path':str(Path(model_path).resolve()),'sha256':_sha(model_path),'bytes':Path(model_path).stat().st_size}
    elif model_path is not None:
        raise ValueError('Only pose tracking uses a model file')
    source, output = Path(source), Path(output)
    if not source.is_file():
        raise ValueError('source must be an existing file')
    if output.exists() or source.resolve() == output.resolve():
        raise FileExistsError(output)
    if type(start_frame) is not int or start_frame < 0 or (end_frame is not None and
            (type(end_frame) is not int or end_frame <= start_frame)):
        raise ValueError('invalid source frame interval')
    if type(max_width) is not int or max_width < 8:
        raise ValueError('max_width must be an integer of at least 8')
    source_sha = _sha(source)
    source_bytes = source.stat().st_size
    info = _probe(source, count=True)
    video = _stream(info, 'video')
    if video is None:
        raise ValueError('source has no video stream')
    try:
        count = int(video['nb_read_frames'])
        src_w, src_h = int(video['width']), int(video['height'])
    except (KeyError, ValueError, TypeError) as exc:
        raise ValueError('source needs known frame count and dimensions') from exc
    rate = _verified_rate(source, video, count)
    stop = count if end_frame is None else end_frame
    if start_frame >= count or stop > count:
        raise ValueError('source frame interval exceeds video')
    width = min(src_w, max_width)
    height = max(8, round(src_h * width / src_w))
    if height > src_h:
        height = src_h
    if corrections is not None and (not isinstance(corrections, dict) or
            any(type(k) is not int or k < start_frame or k >= stop for k in corrections)):
        raise ValueError('corrections must use source frame indices within the interval')
    relative = {k-start_frame: v for k, v in (corrections or {}).items()}
    command = ['ffmpeg', '-hide_banner', '-nostdin', '-v', 'error', '-threads', '1',
               '-filter_threads', '1', '-i', str(source),
               '-vf', f'trim=start_frame={start_frame}:end_frame={stop},scale={width}:{height}',
               '-fps_mode', 'passthrough', '-an', '-pix_fmt', 'rgb24', '-threads', '1', '-f', 'rawvideo', '-']
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    frame_bytes = width * height * 3
    def frames():
        for _ in range(stop-start_frame):
            payload = process.stdout.read(frame_bytes)
            if len(payload) != frame_bytes:
                raise ValueError('FFmpeg produced fewer frames than the verified interval')
            yield np.frombuffer(payload, dtype=np.uint8).reshape(height, width, 3)
    try:
        if algorithm=='pose':
            from .tracking_pose import track_frames_pose
            rows=track_frames_pose(frames(),initial_box,model['path'],rate,relative)
        elif algorithm == 'csrt':
            from .tracking_csrt import track_frames_csrt
            rows = track_frames_csrt(frames(), initial_box, relative)
        else:
            rows = track_frames(frames(), initial_box, relative)
        extra = process.stdout.read(1)
        error = process.stderr.read().decode(errors='replace')
        if process.wait() != 0 or extra:
            raise ValueError(f'FFmpeg frame decode failed: {error[-500:]}')
    except BaseException as exc:
        process.kill()
        process.wait()
        error = process.stderr.read().decode(errors='replace')
        if isinstance(exc, ValueError) and error:
            raise ValueError(f'{exc}; FFmpeg: {error[-1000:]}') from exc
        raise
    finally:
        process.stdout.close()
        process.stderr.close()
    for row in rows:
        row['frame'] += start_frame
    if _sha(source) != source_sha or source.stat().st_size != source_bytes:
        raise ValueError('Tracking source changed during decode')
    result = {'version': 1, 'algorithm': {'csrt':'csrt-v1','lk':'lk-affine-v1','pose':'pose-v1'}[algorithm],
              'engine_version': _cv2().__version__,
              'source': {'path': str(source.resolve()), 'sha256': source_sha,
                         'bytes': source_bytes},
              'fps': str(rate), 'start_frame': start_frame,
              'end_frame_exclusive': stop, 'rows': rows, 'review_required': True}
    result['selection']={'actor':actor,'reason':reason.strip(),'initial_box':_box(initial_box),
                         'corrections':{str(k):_box(v) for k,v in (corrections or {}).items()}}
    if model:
        from importlib.metadata import version
        if _sha(model['path'])!=model['sha256']:
            raise ValueError('Pose model changed during tracking')
        result['model']=model
        result['engine_version']=version('mediapipe')
    validate_track(result)
    with output.open('x', encoding='utf-8') as file:
        json.dump(result, file, ensure_ascii=False, indent=2, allow_nan=False)
        file.write('\n')
    return result


def validate_track(track, source=None, first_frame=None, end_frame=None):
    """Validate consecutive tracking rows, provenance and an optional usable interval.

    Loss is evidence, not a box to interpolate. Validation never grants review.
    A requested interval is usable only if every frame has a declared box.
    """
    from fractions import Fraction
    import re
    from .video_effects import _sha, _probe, _stream, _verified_rate
    if isinstance(track, (str, Path)):
        track = json.loads(Path(track).read_text())
    fields = {'version', 'algorithm', 'source', 'fps', 'start_frame',
              'end_frame_exclusive', 'rows', 'review_required'}
    if not isinstance(track, dict) or not fields <= set(track) or set(track)-fields-{'engine_version','model','selection'} or type(track['version']) is not int or track['version'] != 1:
        raise ValueError('Invalid tracking artifact schema')
    if track['algorithm'] not in {'lk-affine-v1', 'csrt-v1', 'pose-v1'} or track['review_required'] is not True:
        raise ValueError('Tracking must remain review-required')
    if 'engine_version' in track and (not isinstance(track['engine_version'],str) or not track['engine_version'].strip()):
        raise ValueError('Invalid tracking engine version')
    if track['algorithm']=='pose-v1':
        model=track.get('model')
        if not isinstance(model,dict) or set(model)!={'path','sha256','bytes'} or not isinstance(model['path'],str) or not Path(model['path']).is_absolute() or not isinstance(model['sha256'],str) or not re.fullmatch('[0-9a-f]{64}',model['sha256']) or type(model['bytes']) is not int or model['bytes']<=0:
            raise ValueError('Pose tracking needs sealed model provenance')
    elif 'model' in track:
        raise ValueError('Unexpected tracking model')
    provenance = track['source']
    if not isinstance(provenance, dict) or set(provenance) != {'path', 'sha256', 'bytes'}:
        raise ValueError('Invalid tracking source provenance')
    if not isinstance(provenance['path'], str) or not Path(provenance['path']).is_absolute():
        raise ValueError('Tracking source path must be absolute')
    if not isinstance(provenance['sha256'], str) or not re.fullmatch('[0-9a-f]{64}', provenance['sha256']):
        raise ValueError('Invalid tracking source SHA')
    if type(provenance['bytes']) is not int or provenance['bytes'] <= 0:
        raise ValueError('Invalid tracking source size')
    try:
        if not isinstance(track['fps'], str):
            raise ValueError()
        rate = Fraction(track['fps'])
    except (ValueError, ZeroDivisionError) as exc:
        raise ValueError('Tracking FPS must be positive rational text') from exc
    if rate <= 0:
        raise ValueError('Tracking FPS must be positive')
    first, end = track['start_frame'], track['end_frame_exclusive']
    if type(first) is not int or type(end) is not int or not 0 <= first < end:
        raise ValueError('Invalid tracking frame bounds')
    if 'selection' in track:
        selection=track['selection']
        if not isinstance(selection,dict) or set(selection)!={'actor','reason','initial_box','corrections'} or selection['actor'] not in {'human','codex','claude_code','automation'} or not isinstance(selection['reason'],str) or not selection['reason'].strip():
            raise ValueError('Invalid tracking selection provenance')
        _box(selection['initial_box'])
        if not isinstance(selection['corrections'],dict):
            raise ValueError('Invalid tracking correction provenance')
        for key,box in selection['corrections'].items():
            if not isinstance(key,str) or not re.fullmatch('0|[1-9][0-9]*',key) or not first<=int(key)<end:
                raise ValueError('Correction provenance lies outside tracked frames')
            _box(box)
    rows = track['rows']
    if not isinstance(rows, list) or len(rows) != end-first:
        raise ValueError('Tracking rows must cover every declared frame')
    awaiting = True
    lost = []
    for index, row in enumerate(rows, first):
        if not isinstance(row, dict) or set(row) != {'frame', 'box', 'state', 'quality'} or type(row['frame']) is not int or row['frame'] != index:
            raise ValueError('Tracking rows must be consecutive source frames')
        if row['state'] not in {'manual', 'tracked', 'lost'} or not isinstance(row['quality'], dict):
            raise ValueError('Invalid tracking state or quality')
        quality = row['quality']
        count = quality.get('feature_count')
        if track['algorithm']=='lk-affine-v1' and (type(count) is not int or count < 0):
            raise ValueError('Invalid feature count')
        if row['state'] == 'lost':
            if row['box'] is not None or not isinstance(quality.get('reason'), str) or not quality['reason'].strip():
                raise ValueError('Lost rows need an explicit reason and no box')
            lost.append(index)
            awaiting = True
        else:
            _box(row['box'])
            if track['algorithm']=='lk-affine-v1' and count < 6:
                raise ValueError('Usable tracking needs at least six features')
            if track['algorithm']=='csrt-v1' and quality.get('tracker_update') is not True:
                raise ValueError('CSRT usable row needs successful update')
            if track['algorithm']=='pose-v1':
                if quality.get('pose_geometry')!='torso_landmarks' or quality.get('association_kind')!=('seed_overlap' if row['state']=='manual' else 'torso_distance'):
                    raise ValueError('Invalid pose association')
                for key in ('min_visibility','min_presence','association_score'):
                    value=quality.get(key)
                    if isinstance(value,bool) or not isinstance(value,(float,int)) or not math.isfinite(value) or value<0 or (key!='association_score' and value>1):
                        raise ValueError('Invalid pose quality')
                    if key in {'min_visibility','min_presence'} and value<.5:
                        raise ValueError('Pose core landmark quality is too low')
                upper=1.5 if row['state']=='manual' else .75
                if quality['association_score']>upper:
                    raise ValueError('Pose association is outside accepted geometry')
            if row['state'] == 'tracked':
                if awaiting:
                    raise ValueError('Lost tracking needs a manual correction')
                metrics = [('inlier_fraction', .6, 1), ('appearance_mae', 0, .20)] if track['algorithm']=='lk-affine-v1' else [('template_correlation', .15, 1)] if track['algorithm']=='csrt-v1' else []
                for key, low, high in metrics:
                    value = quality.get(key)
                    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not low <= value <= high:
                        raise ValueError('Invalid tracking quality metric')
            awaiting = False
    if source is not None:
        path = Path(source)
        if not path.is_file() or path.stat().st_size != provenance['bytes'] or _sha(path) != provenance['sha256']:
            raise ValueError('Tracking source fingerprint changed')
        video = _stream(_probe(path, count=True), 'video')
        if video is None:
            raise ValueError('Tracking source has no video')
        count = int(video['nb_read_frames'])
        if end > count or _verified_rate(path, video, count) != rate:
            raise ValueError('Tracking source timing changed')
    if (first_frame is None) != (end_frame is None):
        raise ValueError('Supply both interval bounds')
    if first_frame is not None:
        if type(first_frame) is not int or type(end_frame) is not int or not first <= first_frame < end_frame <= end:
            raise ValueError('Requested tracking interval outside artifact')
        if any(first_frame <= frame < end_frame for frame in lost):
            raise ValueError('Requested tracking interval contains lost frames; supply manual corrections')
    return {'version': 1, 'algorithm': track['algorithm'], 'engine_version': track.get('engine_version'),
            'source_sha256': provenance['sha256'], 'fps': str(rate),
            'start_frame': first, 'end_frame_exclusive': end,
            'frame_count': len(rows), 'lost_frames': lost, 'review_required': True}
