"""Source-bound, manually editable relative depth; never metric distance."""
from pathlib import Path

import numpy as np

from .common import fingerprint, read, write
from .video_effects import _probe, _stream, _verified_rate


def _field(path, width, height):
    try:
        value = np.load(path, allow_pickle=False, mmap_mode='r')
    except (OSError, ValueError) as exc:
        raise ValueError('Depth field must be a numeric NPY file') from exc
    if (not isinstance(value, np.ndarray) or value.dtype != np.float32 or
            value.shape != (height, width) or not np.isfinite(value).all() or
            np.any(value < 0) or np.any(value > 1)):
        raise ValueError('Depth field needs full-size finite float32 values in [0, 1]')
    return value


def _reference(value):
    if (not isinstance(value, dict) or set(value) != {'path','sha256','bytes'} or
            not isinstance(value['path'], str) or not value['path'] or
            type(value['bytes']) is not int or value['bytes'] <= 0 or
            not isinstance(value['sha256'], str) or len(value['sha256']) != 64 or
            any(c not in '0123456789abcdef' for c in value['sha256'])):
        raise ValueError('Invalid depth file fingerprint')
    return value


def _source(source):
    path = Path(source).resolve(strict=True)
    binding = fingerprint(path)
    picture = _stream(_probe(path, count=True), 'video')
    if picture is None:
        raise ValueError('Depth source needs video')
    # Fields describe coded pixels. FFmpeg's default display transforms could
    # otherwise rotate/mirror the picture beneath those unchanged coordinates.
    if (picture.get('tags', {}).get('rotate') not in (None, '0', 0)
            or any(row.get('side_data_type') == 'Display Matrix'
                   for row in picture.get('side_data_list', []))):
        raise ValueError('Depth source display transforms are unsupported; prepare an oriented source first')
    count = int(picture['nb_read_frames'])
    width, height = int(picture['width']), int(picture['height'])
    rate = _verified_rate(path, picture, count)
    if count <= 0 or width <= 0 or height <= 0:
        raise ValueError('Invalid depth source geometry')
    if fingerprint(path) != binding:
        raise ValueError('Depth source changed during probe')
    return binding, width, height, count, str(rate)


def prepare_manual_depth(source, fields, output, actor, reason):
    """Copy explicit contiguous frame fields to a new review-required artifact.

    The caller declares near-high relative values. No per-frame min/max
    normalization or inferred metric calibration is applied here.
    """
    if actor not in ('human', 'codex', 'claude_code', 'automation'):
        raise ValueError('Record a real depth actor')
    if not isinstance(reason, str) or not reason.strip():
        raise ValueError('Depth preparation requires an observation reason')
    if not isinstance(fields, dict) or not fields:
        raise ValueError('Provide explicit source-frame depth fields')
    if any(type(frame) is not int for frame in fields):
        raise ValueError('Depth frame IDs must be integers')
    frames = sorted(fields)
    if frames != list(range(frames[0], frames[-1]+1)):
        raise ValueError('Depth fields must cover a contiguous interval without missing frames')
    binding, width, height, count, fps = _source(source)
    if not 0 <= frames[0] <= frames[-1] < count:
        raise ValueError('Depth field interval exceeds source frames')
    target = Path(output).resolve()
    if target.exists():
        raise FileExistsError(target)
    # Validate every input before writing; later changes fail instead of mixing
    # revisions. Keep memory bounded to one field while copying.
    inputs = {}
    for frame in frames:
        path = Path(fields[frame]).resolve(strict=True)
        reference = fingerprint(path)
        _field(path, width, height)
        if fingerprint(path) != reference:
            raise ValueError('Depth input changed during validation')
        inputs[frame] = reference
    target.mkdir(parents=True, exist_ok=False)
    rows = []
    for frame in frames:
        reference = inputs[frame]
        path = Path(reference['path'])
        if fingerprint(path) != reference:
            raise ValueError('Depth input changed before copying')
        value = _field(path, width, height)
        output_field = target/f'{frame:09d}.npy'
        with output_field.open('xb') as stream:
            np.save(stream, value, allow_pickle=False)
        if fingerprint(path) != reference:
            raise ValueError('Depth input changed during copying')
        rows.append({'frame': frame, 'field': fingerprint(output_field),
                     'input': reference, 'origin': 'manual_relative',
                     'minimum': float(value.min()), 'maximum': float(value.max())})
    if fingerprint(source) != binding:
        raise ValueError('Depth source changed during preparation')
    document = {'version': 1, 'source': binding, 'fps': fps, 'width': width,
                'height': height, 'source_frame_count': count,
                'start_frame': frames[0], 'end_frame_exclusive': frames[-1]+1,
                'representation': 'relative_near_high_float32_0_1',
                'normalization': 'explicit_shared_relative_scale',
                'algorithm': 'manual-relative-depth-v1', 'actor': actor,
                'reason': reason.strip(), 'rows': rows, 'review_required': True,
                'metric_distance': False, 'adopted': False}
    manifest = target/'depth.json'
    write(manifest, document)
    validate_depth(manifest, source)
    return manifest


def validate_depth(manifest, source=None):
    """Revalidate exact fields/source geometry; success is not visual review."""
    doc = read(manifest)
    required = {'version', 'source', 'fps', 'width', 'height', 'source_frame_count',
                'start_frame', 'end_frame_exclusive', 'representation', 'normalization',
                'algorithm', 'actor', 'reason', 'rows', 'review_required',
                'metric_distance', 'adopted'}
    if (not isinstance(doc, dict) or set(doc) != required or type(doc['version']) is not int or
            doc['version'] != 1 or doc['representation'] != 'relative_near_high_float32_0_1' or
            doc['normalization'] != 'explicit_shared_relative_scale' or
            doc['algorithm'] != 'manual-relative-depth-v1' or doc['review_required'] is not True or
            doc['metric_distance'] is not False or doc['adopted'] is not False):
        raise ValueError('Invalid relative depth manifest contract')
    if doc['actor'] not in ('human', 'codex', 'claude_code', 'automation') or not isinstance(doc['reason'], str) or not doc['reason'].strip():
        raise ValueError('Depth manifest requires real actor and reason')
    for key in ('width', 'height', 'source_frame_count', 'start_frame', 'end_frame_exclusive'):
        if type(doc[key]) is not int:
            raise ValueError('Depth geometry/frame fields must be integers')
    if not isinstance(doc['fps'], str):
        raise ValueError('Depth FPS must be a rational string')
    _reference(doc['source'])
    binding, width, height, count, fps = _source(source or doc['source']['path'])
    if (binding['sha256'] != doc['source'].get('sha256') or binding['bytes'] != doc['source'].get('bytes') or
            (width, height, count, fps) != (doc['width'], doc['height'], doc['source_frame_count'], doc['fps'])):
        raise ValueError('Depth source fingerprint or geometry changed')
    first, end = doc['start_frame'], doc['end_frame_exclusive']
    if not 0 <= first < end <= count or not isinstance(doc['rows'], list) or len(doc['rows']) != end-first:
        raise ValueError('Depth rows do not cover the declared source interval')
    for frame, row in zip(range(first, end), doc['rows']):
        if (not isinstance(row, dict) or set(row) != {'frame','field','input','origin','minimum','maximum'} or
                type(row['frame']) is not int or row['frame'] != frame or row['origin'] != 'manual_relative'):
            raise ValueError('Invalid or missing depth frame provenance')
        for key in ('field', 'input'):
            ref = _reference(row[key])
            if fingerprint(ref['path']) != ref:
                raise ValueError('Depth field binding changed')
        value = _field(row['field']['path'], width, height)
        if (type(row['minimum']) not in (float, int) or type(row['maximum']) not in (float, int) or
                row['minimum'] != float(value.min()) or row['maximum'] != float(value.max())):
            raise ValueError('Depth field statistics changed')
        if fingerprint(row['field']['path']) != row['field']:
            raise ValueError('Depth field changed during validation')
    if fingerprint(binding['path']) != binding:
        raise ValueError('Depth source changed during validation')
    return doc
