"""Local picture backend for source-bound transitions (not yet a session command).

Decode the actual recorded source frames, fit them to the assembled canvas and
stream one composed frame at a time. The base audio is copied, never stretched.
This backend operates on explicitly declared Rec.709 footage before grading.
"""
from contextlib import contextmanager, ExitStack
from fractions import Fraction
from pathlib import Path
import subprocess

import numpy as np

from .common import fingerprint
from .render_cache import digest
from .transition_mapping import compile_transitions
from .video_effects import _probe, _stream, _verified_rate


def _eligible(cfg):
    from .production import frozen_pattern
    if cfg.get('edit_basis') != 'visual' or cfg.get('retime') or cfg.get('audio_cuts') is not None:
        raise ValueError('Transitions require visual editing without retime or J/L cuts')
    if cfg.get('input_color') != 'rec709':
        raise ValueError('Transitions currently require explicit Rec.709 inputs')
    if cfg.get('fcp_handoff') == 'editable':
        raise ValueError('Transitions require baked mix/video_only handoff; editable FCP transitions are unsupported')
    pattern = frozen_pattern(cfg)
    if pattern['id'] == 'natural' or pattern['intensity'] == 'off':
        raise ValueError('Transitions conflict with natural/off')


def _registered_sources(cfg, mapping):
    from .assets import validate_asset
    from .patterns import resolve_asset_policy
    records = cfg.get('assets')
    if not isinstance(records, list) or not records:
        raise ValueError('Transitions require registered local video assets')
    registry = {row['asset_id']: row for row in records}
    if len(registry) != len(records):
        raise ValueError('Duplicate transition asset IDs')
    sources = {}
    for row in mapping['sequence']:
        aid = row['asset_id']
        if aid in sources:
            continue
        if aid not in registry:
            raise ValueError('Transition source is not registered')
        asset = validate_asset(registry[aid], resolve_asset_policy(cfg))
        if asset['kind'] != 'video':
            raise ValueError('Transition source must be registered video')
        actual = probe_binding(asset['path'])
        if actual['sha256'] != asset['sha256'] or actual['bytes'] != asset['bytes']:
            raise ValueError('Transition source differs from registered asset')
        sources[aid] = actual
    return sources


def prepare_transitions(base, mapping, cfg, request, actor, reason):
    """Seal an explicit rights-checked proposal to the retained visual assembly."""
    _eligible(cfg)
    compiled = compile_transitions(mapping, request, _registered_sources(cfg, mapping), actor, reason)
    video = probe_binding(base)
    if video['frame_count'] != compiled['frame_count'] or Fraction(video['fps']) != Fraction(compiled['fps']):
        raise ValueError('Transition base does not match mapping frame count/FPS')
    return {'version': 1, 'compiled': compiled,
            'input_video': {key: video[key] for key in ('path', 'bytes', 'sha256')}}


def render_transition_setting(base, mapping, cfg, setting, target):
    _eligible(cfg)
    if (not isinstance(setting, dict) or set(setting) != {'version', 'compiled', 'input_video'}
            or type(setting['version']) is not int or setting['version'] != 1):
        raise ValueError('Use a session source-bound transition candidate')
    proposal = setting['compiled']
    sources = _registered_sources(cfg, mapping)
    expected = compile_transitions(mapping, proposal['request'], sources, proposal['actor'], proposal['reason'])
    if digest(proposal) != digest(expected):
        raise ValueError('Transition proposal or registered source mapping changed')
    return render_transitions(base, mapping, proposal, target, input_color=cfg['input_color'],
                              base_binding=setting['input_video'])


def compose_frame(left, right, kind, progress, direction=None):
    """Return RGB pixels and the exact encoded-RGB/spatial operator evidence."""
    if (not isinstance(left, np.ndarray) or not isinstance(right, np.ndarray)
            or left.dtype != np.uint8 or right.dtype != np.uint8
            or left.shape != right.shape or left.ndim != 3 or left.shape[2] != 3
            or not all(left.shape)):
        raise ValueError('Transition inputs must be equally sized nonempty uint8 RGB frames')
    if not isinstance(progress, str):
        raise ValueError('Transition progress must be a rational string')
    try:
        p = Fraction(progress)
    except (ValueError, ZeroDivisionError) as exc:
        raise ValueError('Transition progress must be rational') from exc
    if not 0 <= p <= 1:
        raise ValueError('Transition progress must be within [0,1]')
    if kind == 'dissolve':
        if direction is not None:
            raise ValueError('Dissolve has no direction')
        # Integer arithmetic is exact and cannot overflow for the bounded window.
        if p.denominator > 120:
            raise ValueError('Dissolve denominator exceeds bounded transition window')
        n, d = p.numerator, p.denominator
        pixels = ((left.astype(np.uint32) * (d-n) + right.astype(np.uint32) * n
                   + d//2) // d).astype(np.uint8)
        return pixels, {'operator': 'encoded_rgb_dissolve', 'right_weight': str(p),
                        'rounding': 'nearest_half_up'}
    if kind != 'push' or not isinstance(direction, str) or direction not in {'left', 'right', 'up', 'down'}:
        raise ValueError('Unsupported transition type/direction')
    height, width = left.shape[:2]
    extent = width if direction in {'left', 'right'} else height
    shift = round(p * extent)
    out = np.empty_like(left)
    if direction == 'left':
        out[:, :width-shift] = left[:, shift:]
        out[:, width-shift:] = right[:, :shift]
    elif direction == 'right':
        out[:, :shift] = right[:, width-shift:]
        out[:, shift:] = left[:, :width-shift]
    elif direction == 'up':
        out[:height-shift] = left[shift:]
        out[height-shift:] = right[:shift]
    else:
        out[:shift] = right[height-shift:]
        out[shift:] = left[:height-shift]
    return out, {'operator': 'spatial_push', 'direction': direction,
                 'shift_pixels': shift, 'extent_pixels': extent,
                 'rounding': 'nearest_ties_even'}


def probe_binding(path):
    binding = fingerprint(path)
    video = _stream(_probe(path, count=True), 'video')
    if video is None:
        raise ValueError('Transition source has no video')
    count = int(video['nb_read_frames'])
    binding.update(fps=str(_verified_rate(path, video, count)), frame_count=count)
    return binding


@contextmanager
def _frames(path, indices, width, height, log):
    """Bounded-memory decoder, preserving repeated source-frame references."""
    if not indices or indices != sorted(indices):
        raise ValueError('Decoder requires nondecreasing actual source frame indices')
    filters = (f'trim=start_frame={indices[0]}:end_frame={indices[-1]+1},'
               f'scale={width}:{height}:force_original_aspect_ratio=decrease,'
               f'pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,setsar=1')
    with Path(log).open('wb') as errors:
        process = subprocess.Popen(['ffmpeg', '-v', 'error', '-threads', '1',
            '-filter_threads', '1', '-i', str(path), '-an', '-vf', filters,
            '-fps_mode', 'passthrough', '-pix_fmt', 'rgb24', '-f', 'rawvideo', 'pipe:1'],
            stdout=subprocess.PIPE, stderr=errors)
        def iterator():
            current = indices[0]-1
            pixels = None
            for requested in indices:
                while current < requested:
                    data = process.stdout.read(width*height*3)
                    if len(data) != width*height*3:
                        raise ValueError('Actual transition source decode ended early')
                    pixels = np.frombuffer(data, np.uint8).reshape(height, width, 3)
                    current += 1
                yield pixels
        try:
            yield iter(iterator())
            # A fully consumed iterator leaves no unrequested frames in its trim.
            remainder = process.stdout.read()
            if remainder or process.wait() != 0:
                raise ValueError('Actual transition source decode failed or left frames')
        finally:
            process.stdout.close()
            if process.poll() is None:
                process.kill()
            process.wait()


def _pcm_hash(path):
    return subprocess.check_output(['ffmpeg', '-v', 'error', '-i', str(path),
        '-map', '0:a:0', '-vn', '-c:a', 'pcm_s32le', '-f', 'hash', '-hash', 'sha256', '-']).decode().strip()


def render_transitions(base, mapping, compiled, target, *, input_color, base_binding):
    """Low-level backend; callers must validate registered rights before use.

    The input is the ungraded visual assembly. Source bindings and the entire
    compiled proposal are revalidated. No adoption, human review or FCP import
    is inferred from successful rendering.
    """
    if input_color != 'rec709':
        raise ValueError('Transition backend currently requires explicit Rec.709 inputs')
    base, target = Path(base).resolve(), Path(target).resolve()
    if target.exists() or target == base:
        raise ValueError('Transition output must be a new distinct path')
    sources = {key: probe_binding(value['path']) for key, value in compiled['source_bindings'].items()}
    expected = compile_transitions(mapping, compiled['request'], sources,
                                   compiled['actor'], compiled['reason'])
    if digest(expected) != digest(compiled):
        raise ValueError('Transition proposal or source binding changed')
    before = fingerprint(base)
    if (not isinstance(base_binding, dict) or set(base_binding) != {'path', 'bytes', 'sha256'}
            or any(before[key] != base_binding[key] for key in ('bytes', 'sha256'))):
        raise ValueError('Transition base video binding changed')
    info = _probe(base, count=True)
    video = _stream(info, 'video')
    if video is None:
        raise ValueError('Transition base has no video')
    count = int(video['nb_read_frames'])
    rate = _verified_rate(base, video, count)
    if count != compiled['frame_count'] or rate != Fraction(compiled['fps']):
        raise ValueError('Transition base does not match mapping frame count/FPS')
    width, height = video['width'], video['height']
    if width % 2 or height % 2:
        raise ValueError('Transition output requires an even-sized canvas')
    has_audio = _stream(info, 'audio') is not None
    pcm_before = _pcm_hash(base) if has_audio else None
    target.parent.mkdir(parents=True, exist_ok=True)
    logs = target.parent / (target.stem + '-transition-logs')
    logs.mkdir(exist_ok=False)
    operators = []
    try:
        with (logs/'encode.log').open('wb') as errors:
            cmd = ['ffmpeg', '-v', 'error', '-n', '-threads', '1', '-filter_threads', '1',
                '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-s', f'{width}x{height}',
                '-r', str(rate), '-i', 'pipe:0', '-i', str(base), '-map', '0:v:0']
            if has_audio:
                cmd += ['-map', '1:a:0', '-c:a', 'copy']
            cmd += ['-c:v', 'libx264', '-threads', '1', '-crf', '18', '-pix_fmt', 'yuv420p',
                '-color_primaries', 'bt709', '-color_trc', 'bt709', '-colorspace', 'bt709',
                '-movflags', '+faststart', '-movie_timescale', '48000', str(target)]
            encoder = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=errors)
            try:
                with _frames(base, list(range(count)), width, height, logs/'base.log') as base_frames:
                    events = iter(compiled['events'])
                    event = next(events, None)
                    index = 0
                    while index < count:
                        pixels = next(base_frames)
                        if event is not None and index == event['first_frame']:
                            with ExitStack() as stack:
                                decoders = {}
                                for side in ('left', 'right'):
                                    rows = [f[side] for f in event['frames']]
                                    path = sources[rows[0]['asset_id']]['path']
                                    decoders[side] = stack.enter_context(_frames(path,
                                        [f['source_frame'] for f in rows], width, height,
                                        logs/f'{len(operators)}-{side}.log'))
                                for offset, row in enumerate(event['frames']):
                                    if offset:
                                        next(base_frames)
                                    composed, operator = compose_frame(next(decoders['left']),
                                        next(decoders['right']), event['type'], row['progress'],
                                        event.get('direction'))
                                    encoder.stdin.write(composed.tobytes())
                                    operators.append({'output_frame': row['output_frame'], **operator})
                            # Both sources and the base window were consumed together.
                            event = next(events, None)
                            index += offset + 1
                        else:
                            encoder.stdin.write(pixels.tobytes())
                            index += 1
                encoder.stdin.close()
                if encoder.wait() != 0:
                    raise ValueError('Transition encoder failed')
            finally:
                if not encoder.stdin.closed:
                    try:
                        encoder.stdin.close()
                    except BrokenPipeError:
                        pass
                if encoder.poll() is None:
                    encoder.kill()
                encoder.wait()
        result = _probe(target, count=True)
        output_video = _stream(result, 'video')
        if (int(output_video['nb_read_frames']) != count
                or _verified_rate(target, output_video, count) != rate):
            raise ValueError('Transition output frame count/FPS changed')
        with (logs/'decode.log').open('wb') as log:
            subprocess.run(['ffmpeg', '-v', 'error', '-xerror', '-i', str(target),
                            '-f', 'null', '-'], stdout=log, stderr=log, check=True)
        pcm_after = _pcm_hash(target) if has_audio else None
        if pcm_after != pcm_before:
            raise ValueError('Transition output decoded audio changed')
        if fingerprint(base) != before or any(probe_binding(s['path']) != s for s in sources.values()):
            raise ValueError('Transition inputs changed during rendering')
        return {'version': 1, 'input_video': before, 'output_video': fingerprint(target),
                'compiled': compiled, 'operators': operators, 'decoded_pcm_sha256': pcm_after,
                'full_decode': True, 'review_required': True, 'adopted': False}
    except BaseException:
        target.unlink(missing_ok=True)
        raise
