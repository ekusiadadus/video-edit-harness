"""Review-required, frame-bound foreground masks from tracked subject boxes."""
from __future__ import annotations

from contextlib import closing
from fractions import Fraction
from importlib.metadata import version
import json
import math
from pathlib import Path
import re
import shutil
import subprocess

import numpy as np

from .tracking import _box, _cv2, validate_track
from .video_effects import _probe, _sha, _stream, _verified_rate


ACTORS = {'human', 'codex', 'claude_code', 'automation'}
SHA = re.compile(r'[0-9a-f]{64}\Z')


def _identity(actor, reason):
    if actor not in ACTORS or not isinstance(reason, str) or not reason.strip():
        raise ValueError('Mask selection needs a real actor and decision reason')
    return {'actor': actor, 'reason': reason.strip()}


def _binary(array, width, height):
    if not isinstance(array, np.ndarray) or array.dtype != np.uint8 or array.shape != (height, width):
        raise ValueError('Mask must be full-size uint8 grayscale')
    if not np.isin(array, (0, 255)).all() or not np.any(array == 255) or not np.any(array == 0):
        raise ValueError('Mask must contain binary foreground and background')
    return array


def _stats(mask):
    return {'foreground_pixels': int(np.count_nonzero(mask)),
            'background_pixels': int(mask.size - np.count_nonzero(mask))}


def segment_frame(bgr_uint8, normalized_box, iterations=5):
    """Run GrabCut with a tracked rectangle; return binary mask and pixel counts."""
    cv2 = _cv2()
    frame = np.asarray(bgr_uint8)
    if frame.dtype != np.uint8 or frame.ndim != 3 or frame.shape[2] != 3 or min(frame.shape[:2]) < 8:
        raise ValueError('Segmentation needs a BGR uint8 frame of at least 8x8')
    if type(iterations) is not int or iterations < 1 or iterations > 20:
        raise ValueError('GrabCut iterations must be an integer in [1, 20]')
    x0, y0, x1, y1 = _box(normalized_box)
    height, width = frame.shape[:2]
    left, top = int(np.floor(x0 * width)), int(np.floor(y0 * height))
    right, bottom = int(np.ceil(x1 * width)), int(np.ceil(y1 * height))
    # A rectangle touching all frame edges gives GrabCut no known background.
    if left <= 0 and top <= 0 and right >= width and bottom >= height:
        raise ValueError('Tracked box leaves no known background')
    if right-left < 2 or bottom-top < 2 or (right-left)*(bottom-top) >= width*height:
        raise ValueError('Tracked box is empty or leaves no background')
    seed = np.zeros((height, width), np.uint8)
    cv2.setRNGSeed(0)
    try:
        cv2.grabCut(np.ascontiguousarray(frame), seed, (left, top, right-left, bottom-top),
                    np.zeros((1, 65), np.float64), np.zeros((1, 65), np.float64),
                    iterations, cv2.GC_INIT_WITH_RECT)
    except cv2.error as exc:
        raise ValueError('GrabCut could not segment this tracked rectangle') from exc
    mask = np.where((seed == cv2.GC_FGD) | (seed == cv2.GC_PR_FGD), 255, 0).astype(np.uint8)
    _binary(mask, width, height)
    return mask, _stats(mask)


def _read_png(path, width, height):
    cv2 = _cv2()
    path = Path(path)
    if not path.is_file() or path.suffix.lower() != '.png':
        raise ValueError('Manual mask must be an existing PNG')
    image = cv2.imread(str(path), cv2.IMREAD_UNCHANGED)
    return _binary(image, width, height)


def _probe_source(source, track):
    source = Path(source)
    if not source.is_file():
        raise ValueError('Mask source must exist')
    provenance = track['source']
    # A candidate rerender may retain identical bytes in a new artifact folder.
    # Identity is the sealed content hash and size, not its current location.
    if source.stat().st_size != provenance['bytes'] or _sha(source) != provenance['sha256']:
        raise ValueError('Mask source fingerprint differs from track')
    video = _stream(_probe(source, count=True), 'video')
    if video is None:
        raise ValueError('Mask source has no video')
    try:
        count = int(video['nb_read_frames'])
        width, height = int(video['width']), int(video['height'])
    except (KeyError, ValueError, TypeError) as exc:
        raise ValueError('Mask source needs known frame count and dimensions') from exc
    if width < 8 or height < 8 or count < track['end_frame_exclusive']:
        raise ValueError('Mask source dimensions or frame count invalid')
    if _verified_rate(source, video, count) != Fraction(track['fps']):
        raise ValueError('Mask source FPS differs from track')
    return width, height


def _decode(source, first, end, width, height):
    command = ['ffmpeg', '-hide_banner', '-nostdin', '-v', 'error', '-threads', '1',
               '-filter_threads', '1', '-i', str(source), '-vf',
               f'trim=start_frame={first}:end_frame={end}', '-fps_mode', 'passthrough',
               '-an', '-pix_fmt', 'bgr24', '-threads', '1', '-f', 'rawvideo', '-']
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    size = width*height*3
    try:
        for frame in range(first, end):
            payload = process.stdout.read(size)
            if len(payload) != size:
                raise ValueError(f'FFmpeg produced fewer frames than expected at {frame}')
            yield frame, np.frombuffer(payload, np.uint8).reshape(height, width, 3)
        extra = process.stdout.read(1)
        error = process.stderr.read().decode(errors='replace')
        if process.wait() != 0 or extra:
            raise ValueError(f'FFmpeg frame decode failed: {error[-500:]}')
    except BaseException:
        process.kill()
        process.wait()
        raise
    finally:
        process.stdout.close()
        process.stderr.close()


def _pose_model(track, model_path=None):
    if track['algorithm'] != 'pose-v1' or 'selection' not in track or 'engine_version' not in track:
        raise ValueError('Semantic masks need a sealed pose-v1 track and selection')
    model = track['model']
    if model_path is not None and Path(model_path).resolve() != Path(model['path']):
        raise ValueError('Semantic model path differs from pose track')
    if not Path(model['path']).is_file() or Path(model['path']).stat().st_size != model['bytes'] or _sha(model['path']) != model['sha256']:
        raise ValueError('Bound pose model changed')
    return model


def _same_torso(observed, tracked):
    a, b = _box(observed), _box(tracked)
    intersection = max(0., min(a[2], b[2])-max(a[0], b[0])) * max(0., min(a[3], b[3])-max(a[1], b[1]))
    area_a = (a[2]-a[0])*(a[3]-a[1])
    area_b = (b[2]-b[0])*(b[3]-b[1])
    return intersection / (area_a+area_b-intersection) >= .3


def prepare_masks(source, track_path, output_dir, actor, reason, corrections=None,
                  backend='grabcut', model_path=None, threshold=.5):
    """Write exact-frame PNGs and a sealed manifest into a new directory."""
    identity = _identity(actor, reason)
    source, track_path, output_dir = map(Path, (source, track_path, output_dir))
    if not track_path.is_file():
        raise ValueError('Tracking artifact must exist')
    track_sha = _sha(track_path)
    track = json.loads(track_path.read_text(encoding='utf-8'))
    first, end = track['start_frame'], track['end_frame_exclusive']
    validate_track(track, source=source, first_frame=first, end_frame=end)
    width, height = _probe_source(source, track)
    if not isinstance(backend, str) or backend not in {'grabcut', 'pose'}:
        raise ValueError('Unsupported mask backend')
    if backend == 'grabcut':
        if model_path is not None or threshold != .5:
            raise ValueError('GrabCut does not use a model or threshold')
    else:
        if isinstance(threshold, bool) or not isinstance(threshold, (float, int)) or not math.isfinite(threshold) or not 0 < threshold < 1:
            raise ValueError('Semantic threshold must be finite and strictly between 0 and 1')
        model = _pose_model(track, model_path)
        from .semantic_mask import segment_frames_pose
        try:
            mediapipe_version = version('mediapipe')
        except Exception as exc:
            raise RuntimeError('Semantic masks need installed MediaPipe') from exc
        if mediapipe_version != track['engine_version']:
            raise ValueError('MediaPipe version differs from pose track')
    if corrections is None:
        corrections = {}
    if not isinstance(corrections, dict) or any(type(k) is not int or not first <= k < end for k in corrections):
        raise ValueError('Manual corrections must map absolute frames within the track to PNGs')
    selected = {}
    for frame, path in corrections.items():
        path = Path(path)
        _read_png(path, width, height)
        selected[frame] = {'path': str(path.resolve()), 'sha256': _sha(path), **identity}
    if output_dir.exists():
        raise FileExistsError(output_dir)
    output_dir.mkdir(parents=True)
    cv2 = _cv2()
    try:
        rows = []
        with closing(_decode(source, first, end, width, height)) as decoded:
            if backend == 'pose':
                pose_corrections = {i: row['box'] for i, row in enumerate(track['rows'])
                                    if i and row['state'] == 'manual'}
                def rgb_frames():
                    for _, bgr in decoded:
                        yield np.ascontiguousarray(bgr[:, :, ::-1])
                semantic_rows = segment_frames_pose(rgb_frames(), track['rows'][0]['box'],
                                                    model['path'], track['fps'], pose_corrections,
                                                    num_poses=6, threshold=threshold)
                if len(semantic_rows) != end-first:
                    raise ValueError('Semantic masks do not cover exact frame interval')
                frames = ((first+i, None) for i in range(end-first))
            else:
                frames = decoded
            for frame, bgr in frames:
                if backend == 'pose':
                    semantic = semantic_rows[frame-first]
                    if (not isinstance(semantic, dict) or type(semantic.get('frame')) is not int or
                            semantic['frame'] != frame-first or
                            semantic.get('state') not in {'manual', 'tracked'} or
                            semantic.get('mask') is None or not _same_torso(semantic['box'], track['rows'][frame-first]['box'])):
                        raise ValueError(f'Semantic pose lost or differs from track at frame {frame}')
                    expected_state = 'manual' if track['rows'][frame-first]['state'] == 'manual' else 'tracked'
                    if semantic['state'] != expected_state:
                        raise ValueError(f'Semantic pose selection differs from track at frame {frame}')
                    _binary(semantic['mask'], width, height)
                if frame in selected:
                    correction = selected[frame]
                    if _sha(correction['path']) != correction['sha256']:
                        raise ValueError('Manual mask changed during generation')
                    mask = _read_png(correction['path'], width, height)
                    origin = 'manual'
                else:
                    if backend == 'pose':
                        mask, origin = semantic['mask'], 'pose'
                    else:
                        mask, _ = segment_frame(bgr, track['rows'][frame-first]['box'])
                        origin = 'grabcut'
                name = f'{frame:08d}.png'
                ok, encoded = cv2.imencode('.png', mask)
                if not ok:
                    raise ValueError('Could not encode mask PNG')
                (output_dir / name).write_bytes(encoded.tobytes())
                rows.append({'frame': frame, 'mask_path': str((output_dir/name).resolve()), 'sha256': _sha(output_dir/name),
                             'origin': origin, 'stats': _stats(mask)})
        if _sha(source) != track['source']['sha256'] or source.stat().st_size != track['source']['bytes'] or _sha(track_path) != track_sha:
            raise ValueError('Source or tracking artifact changed during generation')
        if backend == 'pose':
            _pose_model(track, model_path)
        manifest = {'version': 1 if backend == 'grabcut' else 2, 'source': track['source'],
                    'track': {'path': str(track_path.resolve()), 'sha256': track_sha},
                    'fps': track['fps'], 'start_frame': first, 'end_frame_exclusive': end,
                    'width': width, 'height': height,
                    'algorithm': 'opencv-grabcut-rect-v1' if backend == 'grabcut' else 'mediapipe-pose-segmentation-v1',
                    'selection': {**identity, 'corrections': {str(k): v for k, v in selected.items()}},
                    'rows': rows, 'review_required': True}
        if backend == 'grabcut':
            manifest['opencv_version'] = cv2.__version__
        else:
            manifest['semantic'] = {'model': model, 'mediapipe_version': mediapipe_version,
                                    'threshold': float(threshold), 'num_poses': 6}
        manifest_path = output_dir / 'manifest.json'
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2, allow_nan=False)+'\n', encoding='utf-8')
        validate_masks(manifest_path, source=source, first_frame=first, end_frame=end)
        return manifest
    except BaseException:
        shutil.rmtree(output_dir)
        raise


def validate_masks(manifest_path, source=None, first_frame=None, end_frame=None):
    """Verify every mask, track binding, dimensions, timing and review state."""
    manifest_path = Path(manifest_path)
    doc = json.loads(manifest_path.read_text(encoding='utf-8'))
    required = {'version','source','track','fps','start_frame','end_frame_exclusive',
                'width','height','algorithm','selection','rows','review_required'}
    if not isinstance(doc, dict) or type(doc.get('version')) is not int or doc['version'] not in (1, 2) or doc.get('review_required') is not True:
        raise ValueError('Invalid mask manifest schema or review state')
    if doc['version'] == 1:
        if set(doc) != required | {'opencv_version'} or doc['algorithm'] != 'opencv-grabcut-rect-v1' or not isinstance(doc['opencv_version'], str) or not doc['opencv_version']:
            raise ValueError('Invalid mask algorithm binding')
    else:
        if set(doc) != required | {'semantic'} or doc['algorithm'] != 'mediapipe-pose-segmentation-v1':
            raise ValueError('Invalid semantic mask schema or algorithm')
    if type(doc['width']) is not int or type(doc['height']) is not int or min(doc['width'], doc['height']) < 8:
        raise ValueError('Invalid mask dimensions')
    first, end = doc['start_frame'], doc['end_frame_exclusive']
    if type(first) is not int or type(end) is not int or not 0 <= first < end:
        raise ValueError('Invalid mask interval')
    if (first_frame is None) != (end_frame is None):
        raise ValueError('Supply both mask interval bounds')
    if first_frame is not None and (type(first_frame) is not int or type(end_frame) is not int or not first <= first_frame < end_frame <= end):
        raise ValueError('Requested mask interval outside artifact')
    binding = doc['track']
    if not isinstance(binding, dict) or set(binding) != {'path','sha256'} or not isinstance(binding['path'], str) or not Path(binding['path']).is_absolute() or not isinstance(binding['sha256'], str) or not SHA.fullmatch(binding['sha256']):
        raise ValueError('Invalid mask track binding')
    if _sha(binding['path']) != binding['sha256']:
        raise ValueError('Bound track changed')
    track = json.loads(Path(binding['path']).read_text(encoding='utf-8'))
    validate_track(track, source=source, first_frame=first, end_frame=end)
    if doc['version'] == 2:
        model = _pose_model(track)
        semantic = doc['semantic']
        if (not isinstance(semantic, dict) or set(semantic) != {'model','mediapipe_version','threshold','num_poses'} or
                semantic['model'] != model or semantic['mediapipe_version'] != track['engine_version'] or
                not isinstance(semantic['mediapipe_version'], str) or not semantic['mediapipe_version'].strip() or
                type(semantic['num_poses']) is not int or semantic['num_poses'] != 6 or
                isinstance(semantic['threshold'], bool) or not isinstance(semantic['threshold'], (int, float)) or
                not math.isfinite(semantic['threshold']) or not 0 < semantic['threshold'] < 1):
            raise ValueError('Invalid semantic model and threshold binding')
    if doc['source'] != track['source'] or doc['fps'] != track['fps'] or first != track['start_frame'] or end != track['end_frame_exclusive']:
        raise ValueError('Mask manifest differs from track source or timing')
    if source is not None and _probe_source(source, track) != (doc['width'], doc['height']):
        raise ValueError('Mask dimensions differ from source')
    selection = doc['selection']
    if not isinstance(selection, dict) or set(selection) != {'actor','reason','corrections'} or not isinstance(selection['corrections'], dict):
        raise ValueError('Invalid mask selection')
    _identity(selection['actor'], selection['reason'])
    corrections = selection['corrections']
    for key, value in corrections.items():
        if not isinstance(key, str) or not re.fullmatch(r'0|[1-9][0-9]*', key) or not first <= int(key) < end or not isinstance(value, dict) or set(value) != {'path','sha256','actor','reason'}:
            raise ValueError('Invalid manual mask correction')
        _identity(value['actor'], value['reason'])
        if value['actor'] != selection['actor'] or value['reason'] != selection['reason'] or not isinstance(value['path'], str) or not Path(value['path']).is_absolute() or not isinstance(value['sha256'], str) or not SHA.fullmatch(value['sha256']):
            raise ValueError('Invalid manual mask provenance')
        if _sha(value['path']) != value['sha256']:
            raise ValueError('Manual mask changed')
        _read_png(value['path'], doc['width'], doc['height'])
    rows = doc['rows']
    if not isinstance(rows, list) or len(rows) != end-first:
        raise ValueError('Mask rows must cover exact frame interval')
    for frame, row in enumerate(rows, first):
        if not isinstance(row, dict) or set(row) != {'frame','mask_path','sha256','origin','stats'} or type(row['frame']) is not int or row['frame'] != frame:
            raise ValueError('Invalid mask row order')
        expected_origin = 'manual' if str(frame) in corrections else ('pose' if doc['version'] == 2 else 'grabcut')
        if row['mask_path'] != str((manifest_path.parent/f'{frame:08d}.png').resolve()) or row['origin'] != expected_origin or not isinstance(row['sha256'], str) or not SHA.fullmatch(row['sha256']):
            raise ValueError('Invalid mask row binding')
        path = Path(row['mask_path'])
        if _sha(path) != row['sha256']:
            raise ValueError('Mask PNG changed')
        mask = _read_png(path, doc['width'], doc['height'])
        if str(frame) in corrections and not np.array_equal(mask,_read_png(corrections[str(frame)]['path'],doc['width'],doc['height'])):
            raise ValueError('Exported mask pixels differ from selected manual correction')
        if row['stats'] != _stats(mask):
            raise ValueError('Mask pixel statistics changed')
    return doc
