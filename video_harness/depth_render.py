"""Local, source-bound relative-depth picture composite with unchanged audio."""

from __future__ import annotations

from copy import deepcopy
from fractions import Fraction
from pathlib import Path
import subprocess

import numpy as np
from PIL import Image

from .assets import validate_asset
from .common import fingerprint
from .depth_artifact import validate_depth
from .depth_composite import _unit, compose_depth_layer
from .patterns import resolve_asset_policy
from .transitions import _frames, _pcm_hash
from .video_effects import _probe, _stream, _verified_rate


def _rgba(asset, width, height):
    if asset['kind'] != 'image':
        raise ValueError('Depth layer needs a registered image asset')
    with Image.open(asset['path']) as image:
        if image.mode != 'RGBA' or image.size != (width, height) or getattr(image, 'n_frames', 1) != 1:
            raise ValueError('Depth layer needs one full-canvas RGBA image; resizing is unsupported')
        image.load()
        pixels = np.array(image, dtype=np.uint8, copy=True)
    return pixels


def _zero_start(stream, name):
    if 'start_time' not in stream:
        raise ValueError(f'Depth {name} start time is unknown')
    try:
        start = Fraction(str(stream['start_time']))
    except (ValueError, TypeError, ZeroDivisionError) as exc:
        raise ValueError(f'Depth {name} start time is invalid') from exc
    if start != 0:
        raise ValueError(f'Depth {name} must start at zero')


def render_depth_layer(base, depth_manifest, registered_image_asset, policy, target,
                       *, input_color, threshold=.5, softness=.1, strength=1,
                       actor, reason):
    """Render one unadopted local candidate; depth is explicit relative near-high.

    The manifest must describe the exact base video. No model runs here, and
    the depth interval is applied only to its corresponding source frames.
    """
    if input_color != 'rec709':
        raise ValueError('Depth composition requires explicit Rec.709 input')
    if actor not in ('human', 'codex', 'claude_code', 'automation') or not isinstance(reason, str) or not reason.strip():
        raise ValueError('Depth composition needs a real actor and reason')
    threshold = _unit(threshold, 'threshold')
    softness = _unit(softness, 'softness', positive=True)
    strength = _unit(strength, 'strength')
    base = Path(base).resolve(strict=True)
    manifest = Path(depth_manifest).resolve(strict=True)
    target = Path(target).resolve()
    if target.exists() or target == base:
        raise ValueError('Depth output must be a new path distinct from its base')
    source_binding = fingerprint(base)
    manifest_binding = fingerprint(manifest)
    depth = validate_depth(manifest, source=base)
    if depth['source'] != source_binding:
        raise ValueError('Depth source binding differs from base video')
    resolved_policy = resolve_asset_policy({'asset_policy': policy})
    asset = validate_asset(registered_image_asset, resolved_policy, operation='embedded_use')
    info = _probe(base, count=True)
    video = _stream(info, 'video')
    if video is None:
        raise ValueError('Depth base has no video')
    _zero_start(video, 'base video')
    count = int(video['nb_read_frames'])
    rate = _verified_rate(base, video, count)
    width, height = int(video['width']), int(video['height'])
    if width <= 0 or height <= 0 or width % 2 or height % 2:
        raise ValueError('Depth base needs positive even canvas dimensions')
    if (count != depth['source_frame_count'] or str(rate) != depth['fps']
            or (width, height) != (depth['width'], depth['height'])):
        raise ValueError('Depth artifact frame geometry differs from base video')
    layer = _rgba(asset, width, height)
    if fingerprint(base) != source_binding or fingerprint(manifest) != manifest_binding:
        raise ValueError('Depth base or manifest changed during validation')
    if fingerprint(asset['path'])['sha256'] != asset['sha256']:
        raise ValueError('Depth layer image changed during loading')

    input_audio = _stream(info, 'audio')
    has_audio = input_audio is not None
    if has_audio:
        _zero_start(input_audio, 'base audio')
    pcm_before = _pcm_hash(base) if has_audio else None
    target.parent.mkdir(parents=True, exist_ok=True)
    logs = target.parent / (target.stem + '-depth-logs')
    logs.mkdir(exist_ok=False)
    rows = {row['frame']: row for row in depth['rows']}
    try:
        with (logs/'encode.log').open('wb') as errors:
            cmd = ['ffmpeg', '-v', 'error', '-nostdin', '-n', '-threads', '1',
                   '-filter_threads', '1', '-f', 'rawvideo', '-pix_fmt', 'rgb24',
                   '-s', f'{width}x{height}', '-r', str(rate), '-i', 'pipe:0',
                   '-i', str(base), '-map', '0:v:0']
            if has_audio:
                cmd += ['-map', '1:a:0', '-c:a', 'copy']
            cmd += ['-c:v', 'libx264', '-threads', '1', '-crf', '18', '-pix_fmt', 'yuv420p',
                    '-color_primaries', 'bt709', '-color_trc', 'bt709', '-colorspace', 'bt709',
                    '-movflags', '+faststart', '-movie_timescale', '48000', str(target)]
            encoder = subprocess.Popen(cmd, stdin=subprocess.PIPE,
                                       stdout=subprocess.DEVNULL, stderr=errors)
            try:
                with _frames(base, list(range(count)), width, height, logs/'base.log') as frames:
                    for index in range(count):
                        picture = next(frames)
                        if index in rows:
                            field = np.load(rows[index]['field']['path'], mmap_mode='r', allow_pickle=False)
                            picture = compose_depth_layer(picture, field, layer, strength,
                                                          threshold, softness)
                        encoder.stdin.write(picture.tobytes())
                encoder.stdin.close()
                if encoder.wait() != 0:
                    raise ValueError('Depth encoder failed')
            finally:
                if not encoder.stdin.closed:
                    try:
                        encoder.stdin.close()
                    except BrokenPipeError:
                        pass
                if encoder.poll() is None:
                    encoder.kill()
                encoder.wait()

        observed = _probe(target, count=True)
        output_video = _stream(observed, 'video')
        if (output_video is None or int(output_video['nb_read_frames']) != count
                or _verified_rate(target, output_video, count) != rate):
            raise ValueError('Depth output frame count or FPS changed')
        _zero_start(output_video, 'output video')
        output_audio = _stream(observed, 'audio')
        if (output_audio is not None) != has_audio:
            raise ValueError('Depth output audio presence changed')
        if output_audio is not None:
            _zero_start(output_audio, 'output audio')
        with (logs/'decode.log').open('wb') as log:
            subprocess.run(['ffmpeg', '-v', 'error', '-xerror', '-i', str(target),
                            '-f', 'null', '-'], stdout=log, stderr=log, check=True)
        pcm_after = _pcm_hash(target) if has_audio else None
        if pcm_after != pcm_before:
            raise ValueError('Depth output decoded audio changed')
        if fingerprint(base) != source_binding or fingerprint(manifest) != manifest_binding:
            raise ValueError('Depth base or manifest changed during rendering')
        if validate_depth(manifest, source=base) != depth:
            raise ValueError('Depth fields changed during rendering')
        if validate_asset(registered_image_asset, resolved_policy, operation='embedded_use') != asset:
            raise ValueError('Depth image registration changed during rendering')
        return {'version': 1, 'operator': 'relative_depth_rgba_behind_nearer_picture',
                'base': source_binding, 'depth_manifest': manifest_binding,
                'depth_source': depth['source'], 'depth_interval':
                {'start_frame': depth['start_frame'], 'end_frame_exclusive': depth['end_frame_exclusive']},
                'image_asset': {'asset_id': asset['asset_id'], 'path': asset['path'],
                                'sha256': asset['sha256'], 'bytes': asset['bytes'],
                                'record_sha256': asset['record_sha256']},
                'image_asset_record': deepcopy(asset), 'asset_policy': deepcopy(resolved_policy),
                'parameters': {'threshold': threshold, 'softness': softness, 'strength': strength,
                               'input_color': input_color, 'near_high': True},
                'actor': actor, 'reason': reason.strip(), 'frame_count': count,
                'fps': str(rate), 'output': fingerprint(target),
                'decoded_pcm_sha256': pcm_after, 'full_decode': True,
                'review_required': True, 'adopted': False, 'metric_distance': False}
    except BaseException:
        target.unlink(missing_ok=True)
        raise
