"""Retain the actual secondary-video samples through a cue phase map.

The original render seals its actual output samples in a transparent layer.
Retiming selects those decoded samples, preserving trim, placement and alpha.
Input timestamps remain audit metadata rather than a reconstruction recipe.
"""

from __future__ import annotations

from fractions import Fraction
from pathlib import Path
import hashlib
import json
import subprocess
import re

from .cues import validate_video_phase
from .common import fingerprint


def video_cue_content_sha256(cue, source_sha256):
    """Bind samples to the source trim and baked spatial/opacity settings."""
    content = {'asset_id': cue['asset_id'], 'source_sha256': source_sha256,
               'source_start': str(Fraction(str(cue['source_start']))),
               'source_end': str(Fraction(str(cue['source_end']))),
               'position': cue.get('position', 'center'),
               'opacity': str(Fraction(str(cue.get('opacity', 1))))}
    if cue.get('loop', False):
        content['loop'] = True
    if any(Fraction(str(cue.get(key, 0))) for key in ('fade_in', 'fade_out')):
        content.update({key: str(Fraction(str(cue.get(key, 0)))) for key in ('fade_in', 'fade_out')})
    return hashlib.sha256(json.dumps(content, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def static_cue_content_sha256(cue, source_sha256):
    """Bind a sealed static layer to its image or generated title pixels."""
    role = cue['role']
    if role not in {'image', 'title'}:
        raise ValueError('Static cue digest requires image or title role')
    content = {'role': role, 'source_sha256': source_sha256,
               'position': cue.get('position', 'center'),
               'opacity': str(Fraction(str(cue.get('opacity', 1)))),
               'fade_in': str(Fraction(str(cue.get('fade_in', 0)))),
               'fade_out': str(Fraction(str(cue.get('fade_out', 0))))}
    if role == 'image':
        content['asset_id'] = cue['asset_id']
    else:
        content['text'] = cue['text']
    return hashlib.sha256(json.dumps(content, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def capture_overlay_clock(source, cue, rate):
    """Observe the original base picture clock instead of inventing timestamps."""
    rate = Fraction(rate)
    first = Fraction(str(cue['output_start'])) * rate
    end = Fraction(str(cue['output_end'])) * rate
    if first.denominator != 1 or end.denominator != 1 or not 1 <= end-first <= 4096:
        return None
    before = fingerprint(source)
    document = json.loads(subprocess.check_output(['ffprobe', '-v', 'error', '-select_streams', 'v:0',
        '-show_streams', '-show_frames', '-show_entries',
        'stream=time_base:frame=best_effort_timestamp', '-of', 'json', str(source)]))
    observed = subprocess.run(['ffmpeg', '-v', 'info', '-nostdin', '-i', str(source),
        '-filter_complex', '[0:v]showinfo[clock]', '-map', '[clock]', '-map', '0:a?',
        '-frames:v', '1', '-shortest', '-c:v', 'rawvideo', '-c:a', 'copy', '-f', 'null',
        'pipe:1'], stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, check=True)
    trace = observed.stderr.decode('utf-8', errors='replace')
    timebase = re.search(r'config in time_base:\s*(\d+/\d+)', trace)
    first_pts = re.search(r'n:\s*0\s+pts:\s*(-?\d+)', trace)
    if not timebase or not first_pts or Fraction(timebase[1]) != Fraction(document['streams'][0]['time_base']):
        raise ValueError('Cannot observe the effective overlay input clock')
    after = fingerprint(source)
    if before != after:
        raise ValueError('Overlay base changed while observing its clock')
    ticks = [int(row['best_effort_timestamp']) for row in document['frames']]
    input_shift = int(first_pts[1]) - ticks[0]
    if first < 0 or end > len(ticks):
        raise ValueError('Overlay interval exceeds observed base frames')
    return {'cue_id': cue['id'], 'base_sha256': before['sha256'],
            'original_start_frame': first.numerator, 'original_frame_count': int(end-first),
            'original_time_base': document['streams'][0]['time_base'],
            'original_input_pts_shift': input_shift,
            'original_timestamps': ticks[first.numerator:end.numerator]}


def retime_video_cue_layer(source, cue, placement, canvas_size, rate, output, *, log_path=None):
    """Remap sealed actual-output RGBA samples; never reconstruct input clocks."""
    from .overlay_layers import remap_overlay_layer
    phase = validate_video_phase(cue, rate)
    if phase is None or phase['version'] != 2:
        raise ValueError('Visual cue retime needs a fresh original render with sealed layer evidence')
    expected_sha = cue.get('_source_sha256')
    if not isinstance(expected_sha, str) or len(expected_sha) != 64:
        raise ValueError('Video cue source SHA-256 is missing')
    source, output = Path(source), Path(output)
    if fingerprint(source)['sha256'] != expected_sha:
        raise ValueError('Video cue source SHA-256 mismatch before remap')
    digest_cue = video_cue_content_sha256 if cue['role'] == 'video' else static_cue_content_sha256
    if digest_cue(cue, expected_sha) != phase['original_cue_sha256']:
        if cue['role'] == 'video':
            raise ValueError('Video cue source trim or baked placement changed; render a fresh original layer')
        raise ValueError('Static cue source or baked settings changed; render a fresh original layer')
    result = remap_overlay_layer(phase['original_layer'], phase['frames'], rate, canvas_size,
                                output, log_path=log_path)
    if fingerprint(source)['sha256'] != expected_sha:
        output.unlink(missing_ok=True)
        raise ValueError('Video cue source SHA-256 mismatch after remap')
    digest = hashlib.sha256(json.dumps(phase, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    return {**result, 'cue_id': cue['id'], 'source_sha256': expected_sha,
            'phase_map_sha256': digest, 'phase_map': phase, 'output_fps': str(Fraction(rate))}
