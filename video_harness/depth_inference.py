"""Local image-model depth with one explicit shared normalization interval."""
from pathlib import Path
import numpy as np

from .common import fingerprint, write
from .depth_artifact import _source, raw_field, prepare_inferred_depth
from .transitions import _frames


def infer_depth(source, model_dir, first_frame, end_frame_exclusive, output, actor, reason):
    from .depth_model import LocalDepthModel, validate_model_binding
    if actor not in ('human','codex','claude_code','automation') or not isinstance(reason,str) or not reason.strip():
        raise ValueError('Depth inference requires real actor and reason')
    binding, width, height, count, fps = _source(source)
    if (type(first_frame) is not int or type(end_frame_exclusive) is not int
            or not 0 <= first_frame < end_frame_exclusive <= count):
        raise ValueError('Depth inference requires an actual nonempty source-frame interval')
    output = Path(output).resolve()
    if output.exists():
        raise FileExistsError(output)
    output.mkdir(parents=True)
    raw_dir, normalized_dir = output/'raw', output/'normalized-inputs'
    raw_dir.mkdir(); normalized_dir.mkdir()
    model = LocalDepthModel(model_dir)
    raw_rows = []
    lower, upper = float('inf'), float('-inf')
    indices = list(range(first_frame, end_frame_exclusive))
    with _frames(source, indices, width, height, output/'decode.log') as frames:
        for frame, picture in zip(indices, frames):
            field = model.predict(picture)
            path = raw_dir/f'{frame:09d}.npy'
            with path.open('xb') as stream:
                np.save(stream, field, allow_pickle=False)
            field = raw_field(path, width, height)
            lower, upper = min(lower, float(field.min())), max(upper, float(field.max()))
            raw_rows.append({'frame':frame, 'field':fingerprint(path)})
    if not lower < upper:
        raise ValueError('Constant model depth cannot establish relative ordering')
    fields = {}
    for row in raw_rows:
        field = raw_field(row['field']['path'], width, height)
        normalized = ((field.astype(np.float64)-lower)/(upper-lower)).astype(np.float32)
        path = normalized_dir/f"{row['frame']:09d}.npy"
        with path.open('xb') as stream:
            np.save(stream, normalized, allow_pickle=False)
        fields[row['frame']] = path
    if fingerprint(source) != binding:
        raise ValueError('Depth source changed during inference')
    validate_model_binding(model.binding)
    execution = output/'execution.json'
    write(execution, {'version':1, 'model':model.binding, 'source':binding,
                      'width':width, 'height':height, 'fps':fps, 'source_frame_count':count,
                      'start_frame':first_frame, 'end_frame_exclusive':end_frame_exclusive,
                      'actor':actor, 'reason':reason.strip()})
    evidence = {'model':model.binding, 'raw_fields':raw_rows, 'minimum':lower, 'maximum':upper,
                'near_high_assumption':True, 'temporal_consistency':False, 'execution':fingerprint(execution)}
    return prepare_inferred_depth(source, fields, output/'fields', actor, reason, evidence)
