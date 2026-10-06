"""Shared, static pixel geometry for preview overlays and editable FCPXML.

Coordinates are measured on the square-pixel output canvas. FCP positions are
relative to its centre, in percentages of project frame height; positive Y moves up.
Dynamic tracking, source rotation and non-square pixels are excluded.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from fractions import Fraction
import math
import json
import subprocess


def _positive_dimension(value, name):
    if type(value) is not int or value <= 0:
        raise ValueError(f'{name} must be a positive integer')
    return value


def _number(value, name):
    if type(value) is bool:
        raise ValueError(f'{name} must be finite')
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f'{name} must be finite') from exc
    if not math.isfinite(result):
        raise ValueError(f'{name} must be finite')
    return result


def check_video_geometry(stream):
    """Reject video dimensions whose display geometry is not coded W x H."""
    if stream.get('codec_type') != 'video':
        raise ValueError('visual source has no video stream')
    width = _positive_dimension(int(stream['width']), 'source width')
    height = _positive_dimension(int(stream['height']), 'source height')
    sar = stream.get('sample_aspect_ratio') or '1:1'
    if sar not in {'1:1', '1/1'}:
        raise ValueError('non-square source sample aspect ratio is unsupported')
    rotation = stream.get('tags', {}).get('rotate', '0')
    if _number(rotation, 'source rotation') != 0:
        raise ValueError('rotated source geometry is unsupported')
    for side in stream.get('side_data_list', []):
        if 'rotation' in side and _number(side['rotation'], 'source rotation') != 0:
            raise ValueError('rotated source geometry is unsupported')
        if side.get('side_data_type') == 'Display Matrix' and 'rotation' not in side:
            raise ValueError('unknown display matrix rotation is unsupported')
    return width, height


def check_overlay_video_timing(stream):
    """Require the same zero-based CFR clock for preview and XML video cues."""
    if stream.get('codec_type') != 'video':
        raise ValueError('visual source has no video stream')
    try:
        rate = Fraction(stream['r_frame_rate'])
        average = Fraction(stream['avg_frame_rate'])
        start = Fraction(str(stream['start_time']))
    except (KeyError, TypeError, ValueError, ZeroDivisionError) as exc:
        raise ValueError('overlay video timing is unknown') from exc
    if rate <= 0 or average <= 0 or abs(rate - average) / rate > Fraction(1, 100):
        raise ValueError('variable/unknown overlay video frame rate is unsupported')
    if start != 0:
        raise ValueError('nonzero overlay video start_time is unsupported')
    return rate



def check_overlay_video_clock(path, stream):
    """Verify actual presentation times; matching average rates alone is insufficient."""
    rate = check_overlay_video_timing(stream)
    try:
        timebase = Fraction(stream['time_base'])
    except (KeyError, TypeError, ValueError, ZeroDivisionError) as exc:
        raise ValueError('overlay video timebase is unknown') from exc
    if timebase <= 0:
        raise ValueError('overlay video timebase must be positive')
    result = json.loads(subprocess.check_output([
        'ffprobe', '-v', 'error', '-select_streams', 'v:0', '-show_entries',
        'frame=best_effort_timestamp', '-of', 'json', str(path)]))
    try:
        ticks = [int(row['best_effort_timestamp']) for row in result['frames']]
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError('overlay video frame timestamps are unknown') from exc
    if not ticks or ticks[0] != 0:
        raise ValueError('overlay video frames must start at zero')
    declared = stream.get('nb_frames')
    if declared not in (None, 'N/A') and int(declared) != len(ticks):
        raise ValueError('overlay video frame count differs from timestamps')
    ideal = 1 / (rate * timebase)
    tolerance = min(Fraction(1), ideal / 4)
    for index, tick in enumerate(ticks):
        if index and tick <= ticks[index - 1]:
            raise ValueError('overlay video frame timestamps must increase')
        if abs(tick - index * ideal) > tolerance:
            raise ValueError('overlay video requires constant frame timestamps')
    return rate


def _round_nearest(value: Fraction):
    """FFmpeg scale's av_rescale-style nearest-integer size rounding."""
    return (value.numerator * 2 + value.denominator) // (2 * value.denominator)


def measure_placement(cue, canvas_width, canvas_height, source_width, source_height):
    """Return the actual integer preview rectangle and FCP transform values."""
    cw = _positive_dimension(canvas_width, 'canvas width')
    ch = _positive_dimension(canvas_height, 'canvas height')
    sw = _positive_dimension(source_width, 'source width')
    sh = _positive_dimension(source_height, 'source height')
    role = cue.get('role')
    if role not in {'image', 'video', 'title'}:
        raise ValueError('placement requires an image, video or title cue')
    position = cue.get('position', 'center')
    if position not in {'center', 'top'}:
        raise ValueError('overlay position must be center or top')
    opacity = _number(cue.get('opacity', 1), 'overlay opacity')
    if not 0 <= opacity <= 1:
        raise ValueError('overlay opacity must be 0..1')
    if role == 'title':
        if (sw, sh) != (cw, ch):
            raise ValueError('title image must match the canvas')
        rw, rh = sw, sh
    else:
        bound_w = int(cw * .7)
        bound_h = int(ch * .5)
        if bound_w <= 0 or bound_h <= 0:
            raise ValueError('overlay canvas is too small')
        ratio = min(Fraction(bound_w, sw), Fraction(bound_h, sh))
        rw = min(bound_w, max(1, _round_nearest(sw * ratio)))
        rh = min(bound_h, max(1, _round_nearest(sh * ratio)))
    # Preview's yuv420 overlay normalizes coordinates to its 2-pixel chroma
    # grid. Preserve its effective pixels, including odd top Y coordinates.
    x = ((cw - rw) // 2) & ~1
    y = int(ch * (.25 if position == 'center' else .1)) & ~1
    # FCP position is relative to canvas centre, percentage of project height.
    px = Fraction(2 * x + rw - cw, 2)
    py = Fraction(2 * y + rh - ch, 2)
    return {'canvas_size': [cw, ch], 'source_size': [sw, sh],
            'rendered_size': [rw, rh], 'x_pixels': x, 'y_pixels': y,
            'position': position, 'opacity': opacity,
            'transform_scale': [rw / sw, rh / sh],
            'transform_position': [float(100 * px / ch), float(-100 * py / ch)]}


def xml_number(value):
    return format(_number(value, 'XML geometry'), '.15g')


def _decimal(value, name):
    try:
        result = Decimal(value)
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError(f'invalid {name}') from exc
    if not result.is_finite():
        raise ValueError(f'invalid {name}')
    return result


def _pair(value, name):
    parts = value.split()
    if len(parts) != 2:
        raise ValueError(f'invalid {name}')
    return tuple(_decimal(part, name) for part in parts)


def _canonical(value):
    return str(value.normalize()) if value != 0 else '0'


def parse_static_placement(clip):
    """Read only supported, static FCPXML placement into a canonical snapshot."""
    names = ('adjust-conform', 'adjust-transform', 'adjust-blend')
    nodes = [clip.findall(name) for name in names]
    if all(not matches for matches in nodes):
        return None
    if any(len(matches) != 1 for matches in nodes):
        raise ValueError('visual placement requires one conform, transform and blend')
    conform, transform, blend = (matches[0] for matches in nodes)
    if set(conform.attrib) != {'type'} or conform.get('type') != 'none' or list(conform):
        raise ValueError('unsupported visual conform')
    if set(transform.attrib) - {'enabled', 'position', 'scale', 'rotation', 'anchor'} or list(transform):
        raise ValueError('unsupported visual transform')
    if transform.get('enabled', '1') != '1':
        raise ValueError('disabled visual transform')
    if _decimal(transform.get('rotation', '0'), 'rotation') != 0 or _pair(transform.get('anchor', '0 0'), 'anchor') != (0, 0):
        raise ValueError('rotated or anchored visual transform')
    position = _pair(transform.get('position', '0 0'), 'position')
    scale = _pair(transform.get('scale', '1 1'), 'scale')
    if any(value <= 0 for value in scale):
        raise ValueError('invalid visual scale')
    if set(blend.attrib) - {'amount', 'mode'} or list(blend) or blend.get('mode') not in {None, '0'}:
        raise ValueError('unsupported visual blend')
    opacity = _decimal(blend.get('amount', '1.0'), 'opacity')
    if not 0 <= opacity <= 1:
        raise ValueError('invalid visual opacity')
    return {'conform': 'none', 'position': [_canonical(value) for value in position],
            'scale': [_canonical(value) for value in scale],
            'opacity': _canonical(opacity)}
