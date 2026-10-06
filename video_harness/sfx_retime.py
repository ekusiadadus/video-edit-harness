"""Source-bound SFX content retiming, separate from musical playback."""

from copy import deepcopy
from fractions import Fraction

import numpy as np

from .render_cache import digest
from .time_mapping import compile_retime

RATE = 48000
KEYS = {'version', 'mapping', 'mapping_sha256', 'original_start_frame',
        'original_end_frame_exclusive', 'source_sha256', 'content_sha256', 'backend'}


def _time(cue, key):
    from .cues import _seconds
    return _seconds(cue.get(key, 0), key)


def _content(cue, sha):
    return digest({'asset_id': cue['asset_id'], 'source_sha256': sha,
                   **{key: str(_time(cue, key)) for key in
                      ('source_start', 'source_end', 'fade_in', 'fade_out')}})


def _compiled(mapping):
    """Recompile continuous spans; a self-consistent digest alone is insufficient."""
    if not isinstance(mapping, dict) or not isinstance(mapping.get('spans'), list):
        raise ValueError('SFX retime needs a compiled continuous mapping')
    operations = []
    try:
        for span in mapping['spans']:
            op = {key: span[key] for key in ('id', 'kind', 'reason')}
            if span['kind'] == 'ramp':
                op.update(source_first_frame=span['source_first_frame'],
                          source_end_frame_exclusive=span['source_end_frame_exclusive'],
                          speed_start=float(Fraction(span['requested_speed_start'])),
                          speed_end=float(Fraction(span['requested_speed_end'])))
            elif span['kind'] == 'freeze':
                op.update(source_frame=span['source_frame'], output_frames=
                          span['output_end_frame_exclusive'] - span['output_first_frame'])
            else:
                raise ValueError('Invalid SFX retime span kind')
            operations.append(op)
        canonical = compile_retime(mapping['input_frame_count'], mapping['fps'], operations)
    except (KeyError, TypeError, ZeroDivisionError, OverflowError) as exc:
        raise ValueError('Invalid SFX retime mapping') from exc
    if digest(canonical) != digest(mapping):
        raise ValueError('SFX retime mapping differs from recompiled continuous spans')
    return canonical


def _bounds(cue, fps):
    bounds = [_time(cue, key) * fps for key in ('output_start', 'output_end')]
    if any(value.denominator != 1 for value in bounds):
        raise ValueError('SFX retime needs exact frame-aligned cue bounds')
    return tuple(int(value) for value in bounds)


def make_audio_retime(cue, assets, compiled, backend='rubberband'):
    from .cues import _asset_map
    if 'audio_retime' in cue:
        raise ValueError('SFX retime composition requires a fresh original render')
    mapping = _compiled(compiled)
    first, end = _bounds(cue, Fraction(mapping['fps']))
    asset = _asset_map(assets).get(cue.get('asset_id'), {})
    sha = asset.get('sha256') or asset.get('file_sha256')
    metadata = {'version': 1, 'mapping': deepcopy(mapping),
                'mapping_sha256': digest(mapping), 'original_start_frame': first,
                'original_end_frame_exclusive': end, 'source_sha256': sha,
                'content_sha256': _content(cue, sha), 'backend': backend}
    selected = [j for j, base in enumerate(mapping['frame_map']) if first <= base < end]
    if not selected:
        raise ValueError('SFX retime cue interval is omitted')
    moved = dict(cue, audio_retime=metadata,
                 output_start=str(Fraction(selected[0], 1) / Fraction(mapping['fps'])),
                 output_end=str(Fraction(selected[-1] + 1, 1) / Fraction(mapping['fps'])))
    validate_audio_retime(moved, assets)
    return metadata


def validate_audio_retime(cue, assets=None, fps=None):
    metadata = cue.get('audio_retime')
    if metadata is None and 'audio_retime' not in cue:
        return None
    if cue.get('role') != 'sfx' or cue.get('loop', False):
        raise ValueError('Content retime requires a nonlooped SFX cue')
    if (not isinstance(metadata, dict) or set(metadata) != KEYS or
            type(metadata['version']) is not int or metadata['version'] != 1 or
            not isinstance(metadata['backend'], str) or metadata['backend'] not in {'rubberband', 'phase_vocoder'}):
        raise ValueError('Invalid SFX audio_retime metadata')
    mapping = _compiled(metadata['mapping'])
    rate = Fraction(mapping['fps'])
    if fps is not None and Fraction(str(fps)) != rate:
        raise ValueError('SFX retime FPS differs from output clock')
    if metadata['mapping_sha256'] != digest(mapping):
        raise ValueError('SFX retime mapping digest mismatch')
    sha = metadata['source_sha256']
    if not isinstance(sha, str) or len(sha) != 64 or any(c not in '0123456789abcdef' for c in sha):
        raise ValueError('SFX retime requires source SHA-256')
    if assets is not None:
        from .cues import _asset_map
        asset = _asset_map(assets).get(cue.get('asset_id'), {})
        if (asset.get('sha256') or asset.get('file_sha256')) != sha:
            raise ValueError('SFX retime source SHA changed')
    if metadata['content_sha256'] != _content(cue, sha):
        raise ValueError('SFX retime source trim or original fades changed')
    first, end = metadata['original_start_frame'], metadata['original_end_frame_exclusive']
    if type(first) is not int or type(end) is not int or not 0 <= first < end <= mapping['input_frame_count']:
        raise ValueError('SFX retime original bounds are invalid')
    old_duration = Fraction(end - first, 1) / rate
    if _time(cue, 'source_start') < 0 or _time(cue, 'source_end') - _time(cue, 'source_start') < old_duration:
        raise ValueError('SFX retime source too short for original cue')
    if any(_time(cue, key) < 0 for key in ('fade_in', 'fade_out')) or sum(
            _time(cue, key) for key in ('fade_in', 'fade_out')) > old_duration:
        raise ValueError('SFX retime fades exceed original cue duration')
    selected = [j for j, base in enumerate(mapping['frame_map']) if first <= base < end]
    if not selected or selected[-1] - selected[0] + 1 != len(selected):
        raise ValueError('SFX retime cue is omitted or discontinuous')
    if _bounds(cue, rate) != (selected[0], selected[-1] + 1):
        raise ValueError('SFX retime output interval differs from mapping')
    return deepcopy(metadata)


def render_retimed_sfx(chunk, cue, log_dir=None):
    """Apply old fades before continuous retime, crop only on the new clock."""
    from .retime_audio import retime_audio, _sample_boundary
    metadata = validate_audio_retime(cue)
    if metadata is None:
        raise ValueError('SFX content retime metadata is required')
    if not isinstance(chunk, np.ndarray) or chunk.dtype != np.float32 or chunk.ndim != 2 or chunk.shape[1] != 2 or not np.all(np.isfinite(chunk)):
        raise ValueError('SFX retime requires finite float32 stereo PCM')
    mapping = metadata['mapping']
    fps = Fraction(mapping['fps'])
    first = _sample_boundary(metadata['original_start_frame'], RATE, fps)
    end = _sample_boundary(metadata['original_end_frame_exclusive'], RATE, fps)
    target = end - first
    if len(chunk) < target - 1:
        raise ValueError('SFX source shorter than original PCM interval')
    clip = chunk[:target].copy()
    if len(clip) < target:
        clip = np.pad(clip, ((0, target-len(clip)), (0, 0)))
    for key, at_start in (('fade_in', True), ('fade_out', False)):
        count = min(target, round(_time(cue, key) * RATE))
        if count:
            ramp = np.linspace(0, 1, count, dtype=np.float32)
            if at_start:
                clip[:count] *= ramp[:, None]
            else:
                clip[-count:] *= ramp[::-1, None]
    timeline = np.zeros((_sample_boundary(mapping['input_frame_count'], RATE, fps), 2), dtype=np.float32)
    timeline[first:end] = clip
    result, evidence = retime_audio(timeline, RATE, mapping, backend=metadata['backend'], log_dir=log_dir)
    new_first, new_end = (round(_time(cue, key) * RATE) for key in ('output_start', 'output_end'))
    return result[new_first:new_end].copy(), {
        'metadata_sha256': digest(metadata), 'audio': evidence,
        'original_cue_samples': [first, end], 'output_cue_samples': [new_first, new_end],
        'fade_policy': 'original_pcm_before_content_retime',
        'duck_policy': 'new_output_speech_after_content_retime'}
