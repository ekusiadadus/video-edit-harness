"""Music-bound beat focus proposals; no musical-meter or human-review claim."""
from copy import deepcopy
from fractions import Fraction
import math

from .beats import ANALYZER_VERSION, map_beats
from .common import probe
from .motion_templates import compile_template
from .production import verify_production
from .render_cache import digest
from .video_effects import _mapping_shape

_FIELDS = {'version', 'id', 'cue_id', 'beat_map', 'beat_indices', 'window_frames',
           'strength', 'reduced_motion', 'parameters', 'protected_intervals'}
_TIME_FIELDS = (_FIELDS - {'beat_indices'}) | {'output_times', 'max_distance'}
_METHODS = {'manual_beats', 'manual_bpm', 'librosa_beat_track', 'transient_hints'}


def compile_beat_focus(request, mapping, production, reason):
    if (not isinstance(request, dict) or type(request.get('version')) is not int
            or request['version'] not in (1, 2)
            or set(request) != (_FIELDS if request['version']==1 else _TIME_FIELDS)):
        raise ValueError('Beat focus requires exact version-1 or version-2 fields')
    if (not isinstance(request['id'], str) or not request['id'] or request['id'].strip() != request['id']
            or any(c.isspace() for c in request['id']) or not isinstance(request['cue_id'], str)):
        raise ValueError('Beat focus needs a nonempty namespace and music cue ID')
    if not isinstance(reason, str) or not reason.strip():
        raise ValueError('Beat focus requires a decision reason')
    if production.get('mapping_sha256') != digest(mapping):
        raise ValueError('Beat focus requires the sealed output mapping')
    verify_production(production)
    if production['pattern']['beat_sync'] == 'off':
        raise ValueError('Enable beat sync explicitly before beat focus')
    matches = [c for c in production['cues'] if c['id'] == request['cue_id'] and c['role'] == 'music']
    if len(matches) != 1:
        raise ValueError('Beat focus needs one existing music cue')
    cue = matches[0]
    if any(key in cue for key in ('phase_map', 'audio_retime')):
        raise ValueError('Captured music clocks require a fresh original music cue')
    assets = [a for a in production['assets'] if a['asset_id'] == cue['asset_id'] and a['kind'] == 'music']
    if len(assets) != 1:
        raise ValueError('Beat focus music asset is missing')
    asset = assets[0]
    beat_map = request['beat_map']
    if (not isinstance(beat_map, dict) or beat_map.get('source_sha256') != asset['sha256']
            or beat_map.get('source_bytes') != asset['bytes']
            or beat_map.get('analyzer_version') != ANALYZER_VERSION
            or beat_map.get('method') not in _METHODS):
        raise ValueError('Beat map must match the exact registered music bytes and analyzer')
    start, duration = beat_map.get('source_start'), beat_map.get('duration')
    if any(type(x) not in (int, float) or not math.isfinite(x) for x in (start, duration)):
        raise ValueError('Invalid analyzed music range')
    actual_duration = float(probe(asset['path'])['format']['duration'])
    if start < 0 or duration <= 0 or start + duration > actual_duration + 1/48000:
        raise ValueError('Analyzed music range exceeds actual media')
    beats = beat_map.get('beats')
    if (not isinstance(beats, list) or not beats or any(type(b) not in (int, float)
            or not math.isfinite(b) or not start <= b < start + duration for b in beats)
            or any(a >= b for a, b in zip(beats, beats[1:]))):
        raise ValueError('Beat positions must be ordered unique finite source times')
    protected = request['protected_intervals']
    if not isinstance(protected, list):
        raise ValueError('Explicit protected intervals must be a list')
    rate, count = _mapping_shape(mapping)
    intervals = []
    try:
        for pair in protected:
            if not isinstance(pair, list) or len(pair) != 2 or any(type(x) not in (str, int, float) for x in pair):
                raise ValueError
            a, b = (Fraction(str(x)) for x in pair)
            if not 0 <= a < b <= Fraction(count, 1)/rate:
                raise ValueError
            intervals.append((a, b))
    except (ValueError, ZeroDivisionError, OverflowError):
        raise ValueError('Invalid protected music-effect interval') from None
    mapped = map_beats(beat_map, [cue], mapping['fps'], protected)
    time_selection = []
    if request['version']==1:
        indices = request['beat_indices']
    else:
        requested = request['output_times']
        if not isinstance(requested, list) or not 1 <= len(requested) <= 32:
            raise ValueError('Choose 1..32 output times')
        def seconds(value):
            if type(value) not in (str, int, float):
                raise ValueError('Output times and distance must be rational seconds')
            try:
                return Fraction(str(value))
            except (ValueError, ZeroDivisionError, OverflowError):
                raise ValueError('Output times and distance must be rational seconds') from None
        limit = seconds(request['max_distance'])
        if not 0 <= limit <= 1:
            raise ValueError('Maximum beat distance must be within 0..1 seconds')
        indices = []
        for raw in requested:
            point = seconds(raw)
            if not 0 <= point < Fraction(count, 1)/rate:
                raise ValueError('Requested output time is outside the video')
            distances = [(abs(Fraction(b['frame'], 1)/rate-point), i)
                         for i,b in enumerate(mapped['beats'])]
            if not distances:
                raise ValueError('No mapped music beat near the requested time')
            distances.sort()
            distance, index = distances[0]
            if distance > limit:
                raise ValueError('No music beat within the requested maximum distance')
            if len(distances)>1 and distances[1][0]==distance:
                raise ValueError('Requested time is equally close to multiple beats; specify a clearer time')
            indices.append(index)
            time_selection.append({'requested_output_time': str(point), 'mapped_beat_index': index,
                                   'selected_peak_time': str(Fraction(mapped['beats'][index]['frame'], 1)/rate),
                                   'distance_seconds': str(distance), 'max_distance_seconds': str(limit)})
    window = request['window_frames']
    if (not isinstance(indices, list) or not 1 <= len(indices) <= 32
            or any(type(i) is not int or not 0 <= i < len(mapped['beats']) for i in indices)
            or len(indices) != len(set(indices))):
        raise ValueError('Choose 1..32 unique mapped beat indices')
    if type(window) is not int or not 3 <= window <= 301 or window % 2 != 1:
        raise ValueError('Beat focus window needs 3..301 odd frames for an exact peak')
    operations, anchors, windows = [], [], []
    for index in indices:
        beat = mapped['beats'][index]
        center = beat['frame']
        first, end = center - window//2, center + window//2 + 1
        if first < 0 or end > count or not beat['cut_eligible']:
            raise ValueError('Selected beat has no complete eligible effect window')
        if any(Fraction(first, 1)/rate < b and Fraction(end, 1)/rate > a for a, b in intervals):
            raise ValueError('Beat focus window overlaps a protected interval')
        if any(first < b and end > a for a, b in windows):
            raise ValueError('Beat focus windows overlap; select fewer beats or shorter windows')
        windows.append((first, end))
        operations += compile_template({'version': 1, 'id': f"{request['id']}-beat-{index}",
            'template': 'beat_focus', 'output_start': str(Fraction(first, 1)/rate),
            'output_end': str(Fraction(end, 1)/rate), 'strength': request['strength'],
            'reason': reason, 'reduced_motion': request['reduced_motion'], 'parameters': request['parameters']}, mapping)
        anchors.append({**deepcopy(beat), 'mapped_beat_index': index,
                        'peak_frame': center, 'first_frame': first, 'end_frame_exclusive': end})
    return operations, {'version': 1, 'kind': 'music_bound_beat_focus',
        'mapping_sha256': digest(mapping), 'cue': deepcopy(cue),
        'music_sha256': asset['sha256'], 'source_beat_map': deepcopy(beat_map),
        'mapped_beats': mapped, 'anchors': anchors, 'operations': deepcopy(operations),
        'musical_meter_verified': False, 'human_listening_review': False,
        'requires_review': True, **({'time_selection': time_selection} if request['version']==2 else {})}
