"""Pure, versioned recipes for reviewable local picture effects.

Compilation returns ordinary ``revise_effects`` add operations. It neither
selects a candidate nor claims that a musical beat or subject was detected.
"""

from __future__ import annotations

from copy import deepcopy
from fractions import Fraction
import math

from .video_effects import _canonical_event, _mapping_shape


_COMMON = frozenset({'version', 'id', 'template', 'output_start', 'output_end',
                     'strength', 'reason', 'reduced_motion', 'parameters'})
_PARAMETERS = {
    'beat_focus': frozenset({'anchor_x', 'anchor_y', 'max_scale', 'minimum_saturation'}),
    'reveal_callout': frozenset({'anchor_x', 'anchor_y', 'max_scale', 'text', 'x', 'y',
                                'font_size_fraction', 'font_path'}),
}


def catalog() -> dict:
    """Describe the exact v1 recipes without promising automatic edit choices."""
    from .effect_catalog import catalog as effect_catalog
    effects = effect_catalog()['effects']
    zoom = {key: deepcopy(effects['smooth_zoom']['parameters'][key])
            for key in ('anchor_x', 'anchor_y', 'max_scale')}
    zoom['max_scale']['default'] = 1.10
    saturation = deepcopy(effects['saturation_pulse']['parameters']['minimum_saturation'])
    saturation['default'] = .8
    title = {key: deepcopy(effects['keyword_title']['parameters'][key])
             for key in ('text', 'x', 'y', 'font_size_fraction', 'font_path')}
    return {'version': 1, 'backend': 'local_burned', 'review_required': True,
                     'analysis_claims': [], 'native_editable': False, 'depth_aware': False,
                     'templates': {
                         'beat_focus': {
                             'normal': ['smooth_zoom', 'saturation_pulse'],
                             'reduced_motion': ['saturation_pulse'],
                             'reduced_motion_minimum_saturation_floor': .95,
                             'minimum_frames': 3,
                             'intent': 'Emphasize a manually chosen interval; no beat detection.',
                             'parameters': {**zoom, 'minimum_saturation': saturation},
                         },
                         'reveal_callout': {
                             'normal': ['smooth_zoom', 'keyword_title'],
                             'reduced_motion': ['keyword_title'],
                             'minimum_frames': 6,
                             'intent': 'Zoom then fade in a manually supplied label.',
                             'parameters': {**zoom, **title},
                         },
                     }}


def _frame(value: object, rate: Fraction, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, (str, int, float, Fraction)):
        raise ValueError(f'{name} must be a frame-aligned finite time')
    try:
        if isinstance(value, float) and not math.isfinite(value):
            raise ValueError
        time = Fraction(str(value).removesuffix('s'))
    except (ValueError, ZeroDivisionError, OverflowError):
        raise ValueError(f'{name} must be a frame-aligned finite time') from None
    frame = time * rate
    if frame.denominator != 1:
        raise ValueError(f'{name} must align exactly to an output frame')
    return frame.numerator


def _seconds(frame: int, rate: Fraction) -> str:
    return str(Fraction(frame, 1) / rate)


def compile_template(request: dict, mapping: dict) -> list[dict]:
    """Validate and expand a manual recipe into exact add operations."""
    if not isinstance(request, dict) or set(request) != _COMMON or type(request.get('version')) is not int or request['version'] != 1:
        raise ValueError('Template request needs exact version-1 fields')
    template = request['template']
    if not isinstance(template, str) or template not in _PARAMETERS:
        raise ValueError('Unsupported motion template')
    namespace = request['id']
    if not isinstance(namespace, str) or not namespace or namespace.strip() != namespace or any(c.isspace() for c in namespace):
        raise ValueError('Template id must be a nonempty namespace')
    if type(request['reduced_motion']) is not bool:
        raise ValueError('reduced_motion must be a boolean')
    strength = request['strength']
    if isinstance(strength, bool) or not isinstance(strength, (int, float)):
        raise ValueError('strength must be a finite number in (0, 1]')
    try:
        strength = float(strength)
    except (OverflowError, ValueError):
        raise ValueError('strength must be a finite number in (0, 1]') from None
    if not math.isfinite(strength) or not 0 < strength <= 1:
        raise ValueError('strength must be a finite number in (0, 1]')
    reason = request['reason']
    if not isinstance(reason, str) or not reason.strip():
        raise ValueError('Template reason must be nonempty')
    parameters = request['parameters']
    if not isinstance(parameters, dict) or set(parameters) - _PARAMETERS[template]:
        raise ValueError('Template parameters must be an object of supported fields')

    rate, count = _mapping_shape(mapping)
    if 'frame_count' in mapping and (type(mapping['frame_count']) is not int or mapping['frame_count'] != count):
        raise ValueError('Mapping frame_count differs from duration and FPS')
    first = _frame(request['output_start'], rate, 'output_start')
    end = _frame(request['output_end'], rate, 'output_end')
    minimum = 3 if template == 'beat_focus' else 6
    if first < 0 or end > count or end - first < minimum:
        raise ValueError(f'{template} needs at least {minimum} existing output frames')

    def event(suffix: str, kind: str, start: int, stop: int, controls: dict) -> dict:
        row = {'id': f'{namespace}-{suffix}', 'type': kind, 'effect_version': 1,
               'output_start': _seconds(start, rate), 'output_end': _seconds(stop, rate),
               'strength': strength, 'reason': reason.strip(), 'parameters': controls}
        # The existing event validator enforces parameter ranges, font identity,
        # minimum pulse length, and the output mapping's frame limits.
        return _canonical_event(row, rate, count)

    from .effect_catalog import validate_parameters
    zoom_controls = {key: parameters[key] for key in ('anchor_x', 'anchor_y', 'max_scale') if key in parameters}
    validate_parameters('smooth_zoom', zoom_controls)
    events = []
    if template == 'beat_focus':
        minimum_saturation = parameters.get('minimum_saturation', .8)
        if not request['reduced_motion']:
            zoom = dict(zoom_controls)
            zoom.setdefault('anchor_x', .5)
            zoom.setdefault('anchor_y', .5)
            zoom.setdefault('max_scale', 1.10)
            events.append(event('zoom', 'smooth_zoom', first, end, zoom))
        # Validate the supplied value even if the reduced variant clamps it.
        supplied = validate_parameters('saturation_pulse', {'minimum_saturation': minimum_saturation})
        target = max(supplied['minimum_saturation'], .95) if request['reduced_motion'] else supplied['minimum_saturation']
        events.append(event('saturation', 'saturation_pulse', first, end,
                            {'minimum_saturation': target}))
    else:
        title = {key: parameters[key] for key in ('text', 'x', 'y', 'font_size_fraction', 'font_path') if key in parameters}
        title['motion'] = 'fade'
        if not request['reduced_motion']:
            midpoint = first + (end - first) // 2
            zoom = dict(zoom_controls)
            zoom.setdefault('anchor_x', .5)
            zoom.setdefault('anchor_y', .5)
            zoom.setdefault('max_scale', 1.10)
            events.append(event('zoom', 'smooth_zoom', first, midpoint, zoom))
            first = midpoint
        events.append(event('title', 'keyword_title', first, end, title))
    return [{'action': 'add', 'event': row} for row in events]
