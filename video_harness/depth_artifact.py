"""Source-bound, manually editable relative depth; never metric distance."""
from pathlib import Path
import math
import shutil

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
    return _prepare_depth(source, fields, output, actor, reason)


def prepare_inferred_depth(source, fields, output, actor, reason, inference):
    """Retain normalized fields with raw model/normalization provenance."""
    return _prepare_depth(source, fields, output, actor, reason, inference)


def correct_depth(manifest, corrections, output, actor, reason):
    """Copy a validated interval with explicit frame corrections into a review-required v3 revision."""
    if actor not in ('human', 'codex', 'claude_code', 'automation'):
        raise ValueError('Record a real depth actor')
    if not isinstance(reason, str) or not reason.strip():
        raise ValueError('Depth correction requires an observation reason')
    if not isinstance(corrections, dict) or not corrections:
        raise ValueError('Provide explicit corrected source-frame fields')
    if any(type(frame) is not int for frame in corrections):
        raise ValueError('Depth correction frame IDs must be integers')
    parent_path = Path(manifest).resolve(strict=True)
    parent_ref = fingerprint(parent_path)
    parent = validate_depth(parent_path)
    if parent['version'] not in (1, 2, 3, 4):
        raise ValueError('Depth correction parent version is unsupported')
    _ensure_lineage_room(parent_path)
    if fingerprint(parent_path) != parent_ref:
        raise ValueError('Depth parent manifest changed during validation')
    first, end = parent['start_frame'], parent['end_frame_exclusive']
    if any(not first <= frame < end for frame in corrections):
        raise ValueError('Depth correction is outside parent interval')
    target = Path(output).resolve()
    if target.exists():
        raise FileExistsError(target)
    inputs = {}
    for frame, item in corrections.items():
        path = Path(item).resolve(strict=True)
        ref = fingerprint(path)
        _field(path, parent['width'], parent['height'])
        if fingerprint(path) != ref:
            raise ValueError('Depth correction changed during validation')
        inputs[frame] = ref
    rows = []
    target.mkdir(parents=True, exist_ok=False)
    for old in parent['rows']:
        frame = old['frame']
        changed = frame in inputs
        ref = inputs[frame] if changed else old['field']
        if fingerprint(ref['path']) != ref:
            raise ValueError('Depth correction or parent field changed before copying')
        values = _field(ref['path'], parent['width'], parent['height'])
        destination = target/f'{frame:09d}.npy'
        with destination.open('xb') as stream:
            np.save(stream, values, allow_pickle=False)
        if fingerprint(ref['path']) != ref:
            raise ValueError('Depth correction or parent field changed during copying')
        rows.append({'frame': frame, 'field': fingerprint(destination), 'input': ref,
                     'origin': 'manual_correction' if changed else 'retained_depth',
                     'minimum': float(values.min()), 'maximum': float(values.max())})
    if fingerprint(parent_path) != parent_ref or fingerprint(parent['source']['path']) != parent['source']:
        raise ValueError('Depth parent or source changed during correction')
    document = {key: parent[key] for key in ('source', 'fps', 'width', 'height',
                 'source_frame_count', 'start_frame', 'end_frame_exclusive',
                 'representation', 'normalization', 'metric_distance')}
    document.update(version=3, algorithm='manual-depth-correction-v1', actor=actor,
                    reason=reason.strip(), rows=rows, review_required=True, adopted=False,
                    parent=parent_ref, corrected_frames=sorted(inputs))
    result = target/'depth.json'
    write(result, document)
    validate_depth(result)
    return result


def _ensure_lineage_room(parent_path):
    """Reject a 33rd artifact before creating an output directory."""
    seen = set()
    path = Path(parent_path).resolve()
    for depth in range(1, 33):
        if path in seen:
            raise ValueError('Depth lineage contains a cycle')
        seen.add(path)
        doc = read(path)
        if doc.get('version') not in (3, 4):
            if depth >= 32:
                raise ValueError('Depth lineage exceeds 32 revisions')
            return
        ref = _reference(doc['parent'])
        if fingerprint(ref['path']) != ref:
            raise ValueError('Depth parent manifest binding changed')
        path = Path(ref['path']).resolve()
    raise ValueError('Depth lineage exceeds 32 revisions')


def _inherited_cut_frames(parent):
    """Carry declared discontinuities through v3 corrections and later v4 passes."""
    cuts = set()
    current = parent
    for _ in range(32):
        if current['version'] == 4:
            cuts.update(current['temporal']['config']['cut_frames'])
        if current['version'] not in (3, 4):
            return sorted(cuts)
        current = read(current['parent']['path'])
    raise ValueError('Depth lineage exceeds 32 revisions')


def stabilize_depth(manifest, output, actor, reason, *, strength=.5, fb_tolerance=1.0,
                    photometric_tolerance=.08, min_coverage=.5, cut_frames=()):
    """Derive a review-required v4 field artifact from actual source-frame motion."""
    from .depth_temporal import ALGORITHM, BACKEND, replay_temporal, temporal_config
    from .tracking import _cv2
    if actor not in ('human', 'codex', 'claude_code', 'automation'):
        raise ValueError('Record a real depth actor')
    if not isinstance(reason, str) or not reason.strip():
        raise ValueError('Depth stabilization requires an observation reason')
    parent_path = Path(manifest).resolve(strict=True)
    parent_ref = fingerprint(parent_path)
    parent = validate_depth(parent_path)
    _ensure_lineage_room(parent_path)
    config = temporal_config(strength, fb_tolerance, photometric_tolerance, min_coverage,
                             cut_frames, parent['start_frame'], parent['end_frame_exclusive'])
    config['cut_frames'] = sorted(set(config['cut_frames']) | set(_inherited_cut_frames(parent)))
    target = Path(output).resolve()
    if target.exists():
        raise FileExistsError(target)
    target.mkdir(parents=True, exist_ok=False)
    try:
        rows, observations = [], []
        replay = replay_temporal(parent, config, log=target/'decode.log')
        try:
            for old in parent['rows']:
                values, observation = next(replay)
                destination = target / f"{old['frame']:09d}.npy"
                with destination.open('xb') as stream:
                    np.save(stream, values, allow_pickle=False)
                rows.append({'frame': old['frame'], 'field': fingerprint(destination), 'input': old['field'],
                             'origin': 'temporal_stabilized' if observation['reset_reason'] is None else 'temporal_reset',
                             'minimum': float(values.min()), 'maximum': float(values.max())})
                observations.append(observation)
            if next(replay, None) is not None:
                raise ValueError('Depth temporal replay produced extra frames')
        finally:
            replay.close()
        if fingerprint(parent_path) != parent_ref or fingerprint(parent['source']['path']) != parent['source']:
            raise ValueError('Depth parent or source changed during stabilization')
        document = {key: parent[key] for key in ('source', 'fps', 'width', 'height',
                    'source_frame_count', 'start_frame', 'end_frame_exclusive',
                    'representation', 'normalization', 'metric_distance')}
        document.update(version=4, algorithm=ALGORITHM, actor=actor, reason=reason.strip(),
                        rows=rows, review_required=True, adopted=False, parent=parent_ref,
                        temporal={'version': 1, 'algorithm': ALGORITHM, 'backend': BACKEND,
                                  'opencv_version': _cv2().__version__, 'config': config,
                                  'observations': observations})
        result = target/'depth.json'
        write(result, document)
        validate_depth(result)
        return result
    except BaseException:
        shutil.rmtree(target)
        raise


def _prepare_depth(source, fields, output, actor, reason, inference=None):
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
                     'input': reference, 'origin': 'model_relative' if inference is not None else 'manual_relative',
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
    if inference is not None:
        document.update(version=2, algorithm='depth-anything-v2-small-hf-v1',
                        normalization='interval_shared_minmax', inference=inference)
    manifest = target/'depth.json'
    write(manifest, document)
    validate_depth(manifest, source)
    return manifest


def validate_depth(manifest, source=None, *, _parents=()):
    """Revalidate exact fields/source geometry; success is not visual review."""
    manifest_path = Path(manifest).resolve(strict=True)
    if manifest_path in _parents:
        raise ValueError('Depth correction lineage contains a cycle')
    if len(_parents) >= 32:
        raise ValueError('Depth correction lineage exceeds 32 revisions')
    lineage = (*_parents, manifest_path)
    doc = read(manifest)
    required = {'version', 'source', 'fps', 'width', 'height', 'source_frame_count',
                'start_frame', 'end_frame_exclusive', 'representation', 'normalization',
                'algorithm', 'actor', 'reason', 'rows', 'review_required',
                'metric_distance', 'adopted'}
    inferred = isinstance(doc, dict) and type(doc.get('version')) is int and doc.get('version') == 2
    corrected = isinstance(doc, dict) and type(doc.get('version')) is int and doc.get('version') == 3
    temporal = isinstance(doc, dict) and type(doc.get('version')) is int and doc.get('version') == 4
    if inferred:
        required.add('inference')
    if corrected:
        required.update({'parent', 'corrected_frames'})
    if temporal:
        required.update({'parent', 'temporal'})
    if (not isinstance(doc, dict) or set(doc) != required or type(doc['version']) is not int or
            doc['version'] != (4 if temporal else 3 if corrected else 2 if inferred else 1) or doc['representation'] != 'relative_near_high_float32_0_1' or
            (not corrected and not temporal and doc['normalization'] != ('interval_shared_minmax' if inferred else 'explicit_shared_relative_scale')) or
            doc['algorithm'] != ('farneback-fb-photo-v1' if temporal else 'manual-depth-correction-v1' if corrected else 'depth-anything-v2-small-hf-v1' if inferred else 'manual-relative-depth-v1') or doc['review_required'] is not True or
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
                type(row['frame']) is not int or row['frame'] != frame or
                (not corrected and not temporal and row['origin'] != ('model_relative' if inferred else 'manual_relative')) or
                (temporal and row['origin'] not in ('temporal_stabilized', 'temporal_reset'))):
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
    if inferred:
        _validate_inference(doc)
    if corrected:
        _validate_correction(doc, manifest, source, lineage)
    if temporal:
        _validate_temporal(doc, manifest, source, lineage)
    return doc


def _validate_correction(doc, manifest, source, lineage):
    parent_ref = _reference(doc['parent'])
    if Path(parent_ref['path']).resolve() == Path(manifest).resolve():
        raise ValueError('Depth correction cannot parent itself')
    if fingerprint(parent_ref['path']) != parent_ref:
        raise ValueError('Depth parent manifest binding changed')
    parent_doc = read(parent_ref['path'])
    if (not isinstance(parent_doc, dict) or type(parent_doc.get('version')) is not int
            or parent_doc['version'] not in (1, 2, 3, 4)):
        raise ValueError('Depth correction parent must be v1, v2, v3 or v4')
    parent = validate_depth(parent_ref['path'], source, _parents=lineage)
    if fingerprint(parent_ref['path']) != parent_ref:
        raise ValueError('Depth parent manifest changed during validation')

    keys = ('source', 'fps', 'width', 'height', 'source_frame_count', 'start_frame',
            'end_frame_exclusive', 'representation', 'normalization', 'metric_distance')
    if any(doc[key] != parent[key] for key in keys):
        raise ValueError('Depth correction source, interval, canvas or scale differs from parent')
    frames = doc['corrected_frames']
    if (not isinstance(frames, list) or not frames or
            any(type(frame) is not int for frame in frames) or
            frames != sorted(set(frames)) or
            any(not doc['start_frame'] <= frame < doc['end_frame_exclusive'] for frame in frames)):
        raise ValueError('Depth corrected frame IDs are invalid')
    corrected = set(frames)
    for row, original in zip(doc['rows'], parent['rows']):
        changed = row['frame'] in corrected
        expected_origin = 'manual_correction' if changed else 'retained_depth'
        expected_input = row['input'] if changed else original['field']
        if row['origin'] != expected_origin or row['input'] != expected_input:
            raise ValueError('Depth correction row origin or input binding changed')
        input_values = _field(row['input']['path'], doc['width'], doc['height'])
        values = _field(row['field']['path'], doc['width'], doc['height'])
        if not np.array_equal(values, input_values):
            raise ValueError('Depth correction row differs from declared input')
        if not changed and not np.array_equal(values, _field(original['field']['path'], doc['width'], doc['height'])):
            raise ValueError('Depth retained row differs from parent')
        if fingerprint(row['input']['path']) != row['input'] or fingerprint(row['field']['path']) != row['field']:
            raise ValueError('Depth correction row changed during validation')
    if fingerprint(parent_ref['path']) != parent_ref:
        raise ValueError('Depth parent manifest changed during validation')




def _validate_temporal(doc, manifest, source, lineage):
    """Replay actual optical flow; self-reported coverage cannot validate fields."""
    from .depth_temporal import ALGORITHM, BACKEND, replay_temporal, temporal_config
    from .tracking import _cv2
    parent_ref = _reference(doc['parent'])
    if Path(parent_ref['path']).resolve() == Path(manifest).resolve() or fingerprint(parent_ref['path']) != parent_ref:
        raise ValueError('Depth temporal parent binding changed')
    parent = validate_depth(parent_ref['path'], source, _parents=lineage)
    if fingerprint(parent_ref['path']) != parent_ref:
        raise ValueError('Depth temporal parent changed during validation')
    keys = ('source', 'fps', 'width', 'height', 'source_frame_count', 'start_frame',
            'end_frame_exclusive', 'representation', 'normalization', 'metric_distance')
    if any(doc[key] != parent[key] for key in keys):
        raise ValueError('Depth temporal source, interval, canvas or scale differs from parent')
    temporal = doc['temporal']
    if (not isinstance(temporal, dict) or set(temporal) != {'version', 'algorithm', 'backend',
            'opencv_version', 'config', 'observations'} or type(temporal['version']) is not int
            or temporal['version'] != 1 or temporal['algorithm'] != ALGORITHM
            or temporal['backend'] != BACKEND or temporal['opencv_version'] != _cv2().__version__
            or not isinstance(temporal['config'], dict) or
            set(temporal['config']) != {'strength','fb_tolerance','photometric_tolerance',
                                       'min_coverage','cut_frames'} or
            not isinstance(temporal['observations'], list) or
            len(temporal['observations']) != len(doc['rows'])):
        raise ValueError('Invalid depth temporal provenance/backend')
    config = temporal_config(**temporal['config'], first=doc['start_frame'],
                             end=doc['end_frame_exclusive'])
    if config != temporal['config']:
        raise ValueError('Depth temporal config is not canonical')
    if not set(_inherited_cut_frames(parent)) <= set(config['cut_frames']):
        raise ValueError('Depth temporal ancestor cut was removed')
    replay = replay_temporal(parent, config)
    try:
        for row, original, recorded in zip(doc['rows'], parent['rows'], temporal['observations']):
            derived, observation = next(replay)
            if (row['input'] != original['field'] or
                    row['origin'] != ('temporal_stabilized' if observation['reset_reason'] is None else 'temporal_reset')
                    or recorded != observation):
                raise ValueError('Depth temporal input or observed flow evidence changed')
            saved = _field(row['field']['path'], doc['width'], doc['height'])
            if not np.array_equal(saved, derived):
                raise ValueError('Depth temporal field differs from recomputed flow')
            if fingerprint(row['field']['path']) != row['field']:
                raise ValueError('Depth temporal field changed during validation')
        if next(replay, None) is not None:
            raise ValueError('Depth temporal replay produced extra frames')
    finally:
        replay.close()
    if fingerprint(parent_ref['path']) != parent_ref:
        raise ValueError('Depth temporal parent changed during replay')
    if fingerprint(parent['source']['path']) != parent['source']:
        raise ValueError('Depth temporal decoded source changed during replay')
    if source is not None:
        actual_source = fingerprint(source)
        if (actual_source['sha256'], actual_source['bytes']) != (
                parent['source']['sha256'], parent['source']['bytes']):
            raise ValueError('Depth temporal source override changed during replay')
    for original, row in zip(parent['rows'], doc['rows']):
        for ref in (original['field'], original['input'], row['field'], row['input']):
            if fingerprint(ref['path']) != ref:
                raise ValueError('Depth temporal source or field changed during replay')


def raw_field(path, width, height):
    value = np.load(path, allow_pickle=False, mmap_mode='r')
    if (not isinstance(value, np.ndarray) or value.dtype != np.float32
            or value.shape != (height, width) or not np.isfinite(value).all()):
        raise ValueError('Raw relative depth needs full-size finite float32 fields')
    return value


def _validate_inference(doc):
    from .depth_model import validate_model_binding
    evidence = doc['inference']
    if (not isinstance(evidence, dict) or set(evidence) != {'model','raw_fields','minimum','maximum',
            'near_high_assumption','temporal_consistency','execution'} or evidence['near_high_assumption'] is not True
            or evidence['temporal_consistency'] is not False):
        raise ValueError('Invalid local depth inference evidence')
    validate_model_binding(evidence['model'])
    model = evidence['model']
    expected_execution = {'resize':'official_DPTImageProcessor_518', 'interpolation':'bicubic',
                          'align_corners':False, 'raw_relative_depth':True, 'near_high_ordering':'unverified'}
    runtime = model.get('runtime')
    if (model.get('device') != 'cpu' or model.get('inference') != expected_execution
            or not isinstance(runtime, dict) or set(runtime) != {'torch','transformers','safetensors'}
            or any(not isinstance(version,str) or not version for version in runtime.values())):
        raise ValueError('Depth inference execution provenance is incomplete')
    execution_ref = _reference(evidence['execution'])
    if fingerprint(execution_ref['path']) != execution_ref:
        raise ValueError('Depth execution record changed')
    execution = read(execution_ref['path'])
    expected_record = {'version':1, 'model':model, **{key:doc[key] for key in
                       ('source','width','height','fps','source_frame_count','start_frame',
                        'end_frame_exclusive','actor','reason')}}
    if (not isinstance(execution, dict) or type(execution.get('version')) is not int
            or execution != expected_record or fingerprint(execution_ref['path']) != execution_ref):
        raise ValueError('Depth inference execution record differs from manifest')
    for key in ('minimum','maximum'):
        if type(evidence[key]) not in (int,float) or not math.isfinite(evidence[key]):
            raise ValueError('Invalid depth normalization bound')
    lower, upper = evidence['minimum'], evidence['maximum']
    if not lower < upper or not isinstance(evidence['raw_fields'], list) or len(evidence['raw_fields']) != len(doc['rows']):
        raise ValueError('Depth inference requires a nonconstant shared interval range')
    observed_min, observed_max = float('inf'), float('-inf')
    for row, raw in zip(doc['rows'], evidence['raw_fields']):
        if (not isinstance(raw, dict) or set(raw) != {'frame','field'} or type(raw['frame']) is not int
                or raw['frame'] != row['frame']):
            raise ValueError('Raw inference frame binding changed')
        ref = _reference(raw['field'])
        if fingerprint(ref['path']) != ref:
            raise ValueError('Raw depth inference binding changed')
        value = raw_field(ref['path'], doc['width'], doc['height'])
        observed_min = min(observed_min, float(value.min()))
        observed_max = max(observed_max, float(value.max()))
        normalized = ((value.astype(np.float64)-lower)/(upper-lower)).astype(np.float32)
        if not np.array_equal(normalized, _field(row['field']['path'], doc['width'], doc['height'])):
            raise ValueError('Depth normalized values do not match raw inference')
        if fingerprint(ref['path']) != ref:
            raise ValueError('Raw depth changed during validation')
    if (observed_min, observed_max) != (lower, upper):
        raise ValueError('Depth shared normalization range changed')
