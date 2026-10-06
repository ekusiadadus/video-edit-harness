"""Render-bound feedback with explicit source/output time correspondence."""
from math import isfinite


def seconds(value):
    if isinstance(value, bool):
        raise ValueError('Invalid feedback time')
    if isinstance(value, str) and ':' in value:
        parts = value.split(':')
        if len(parts) not in (2, 3):
            raise ValueError('Time must be seconds, MM:SS, or HH:MM:SS')
        nums = [float(p) for p in parts]
        if any(n < 0 or not isfinite(n) for n in nums) or any(n >= 60 for n in nums[1:]):
            raise ValueError('Invalid clock time')
        result = sum(n * 60 ** i for i, n in enumerate(reversed(nums)))
    else:
        result = float(value)
    if not isfinite(result) or result < 0:
        raise ValueError('Invalid feedback time')
    return result


def map_output(mapping, start, end=None):
    start = seconds(start)
    end = start if end is None else seconds(end)
    total = float(mapping['duration'])
    if end < start or end > total + 1e-6:
        raise ValueError('Feedback time is outside this render')
    if mapping.get('retime') and mapping.get('edit_basis') != 'visual':
        return _map_speech_retime(mapping, start, end)
    if 'transitions' in mapping:
        from .transition_feedback import map_transition_output
        return map_transition_output(mapping, start, end)
    if mapping.get('edit_basis') == 'visual':
        return _map_visual(mapping, start, end)
    rows, boundaries, cursor = [], [], 0.0
    spans = mapping['keep']
    identities = mapping.get('sequence_ids', [f'span-{i + 1}' for i in range(len(spans))])
    if not isinstance(identities, list) or len(identities) != len(spans) or len(set(identities)) != len(identities):
        raise ValueError('Invalid sequence identities in render mapping')
    if any(not isfinite(a) or not isfinite(b) or a < 0 or b <= a for a, b in spans) or abs(sum(b-a for a,b in spans)-total) > 1e-5:
        raise ValueError('Invalid source ranges in render mapping')
    for i, ((a, b), identity) in enumerate(zip(spans, identities)):
        length = b - a
        last = cursor + length
        if i and abs(start - cursor) < 1e-6:
            boundaries.append({'output_time': cursor, 'left_source_end': spans[i - 1][1],
                               'right_source_start': a, 'left_sequence_id': identities[i - 1],
                               'right_sequence_id': identity})
        lo, hi = max(start, cursor), min(end, last)
        point = start == end and (cursor <= start < last or i == len(spans) - 1 and abs(start - last) < 1e-6)
        if hi > lo or point:
            if point:
                lo = hi = start
            rows.append({'sequence_id': identity, 'output_start': lo, 'output_end': hi,
                         'source_start': a + lo - cursor, 'source_end': a + hi - cursor})
        cursor = last
    if not rows:
        raise ValueError('No source span corresponds to feedback time')
    return {'output_start': start, 'output_end': end, 'source_spans': rows, 'boundaries': boundaries}


def _map_speech_retime(mapping, start, end):
    """Inspect discrete source frames without assuming a linear retimed timeline."""
    from fractions import Fraction
    from math import floor, ceil
    rate = Fraction(mapping['fps'])
    frames = mapping['retime']['frames']
    if len(frames) != mapping['frame_count'] or not frames:
        raise ValueError('Invalid retimed frame correspondence')
    if not 0 <= start <= float(mapping['duration']):
        raise ValueError('Feedback time is outside this render')
    first = min(floor(Fraction(str(start))*rate), len(frames)-1)
    last = first+1 if start == end else min(ceil(Fraction(str(end))*rate), len(frames))
    groups = []
    for index in range(first,last):
        frame = frames[index]
        if frame['output_frame'] != index:
            raise ValueError('Invalid retimed output frame index')
        if (not groups or groups[-1][-1]['source_span_id'] != frame['source_span_id'] or
                frame['source_frame'] - groups[-1][-1]['source_frame'] not in (0,1)):
            groups.append([])
        groups[-1].append(frame)
    rows=[]
    for group in groups:
        a,b=group[0],group[-1]
        rows.append({'sequence_id':a['source_span_id'],
                     'output_start':max(start,float(Fraction(a['output_frame'],1)/rate)),
                     'output_end':min(end,float(Fraction(b['output_frame']+1,1)/rate)),
                     'source_start':float(Fraction(a['source_frame'],1)/rate),
                     'source_end':float(Fraction(b['source_frame']+(0 if start==end else 1),1)/rate)})
    boundaries=[]
    for row in mapping.get('sequence',[])[1:]:
        position=float(Fraction(row['output_first_frame'],1)/rate)
        if abs(start-position)<1e-6:
            boundaries.append({'output_time':position,'right_sequence_id':row['id']})
    return {'output_start':start,'output_end':end,'source_spans':rows,
            'boundaries':boundaries,'frame_correspondence':frames[first:last],
            'source_time_scope':'discrete observed frame coverage'}


def _map_visual(mapping, start, end):
    from fractions import Fraction
    sequence = mapping.get('sequence')
    if not isinstance(sequence, list) or not sequence:
        raise ValueError('Visual mapping requires actual source sequence')
    rows, boundaries, seen, cursor = [], [], set(), 0.0
    previous = None
    for index, segment in enumerate(sequence):
        ident = segment.get('id')
        if not isinstance(ident, str) or not ident or ident in seen:
            raise ValueError('Invalid visual mapping IDs')
        seen.add(ident)
        a, b, lo, hi = [float(Fraction(str(segment[key]).removesuffix('s'))) for key in
                         ('source_start', 'source_end', 'output_start', 'output_end')]
        if any(not isfinite(v) for v in (a, b, lo, hi)) or a < 0 or b <= a or hi <= lo or abs(lo - cursor) > 1e-6:
            raise ValueError('Invalid visual source/output ranges')
        if not segment.get('asset_id') or not segment.get('source_sha256') or not segment.get('source_path'):
            raise ValueError('Visual mapping must identify each source')
        if previous is not None and abs(start - lo) < 1e-6:
            boundaries.append({'output_time': lo, 'left_sequence_id': previous['id'],
                               'right_sequence_id': ident, 'left_asset_id': previous['asset_id'],
                               'right_asset_id': segment['asset_id']})
        first, last = max(start, lo), min(end, hi)
        point = start == end and (lo <= start < hi or index == len(sequence) - 1 and abs(start - hi) < 1e-6)
        if last > first or point:
            if point:
                first = last = start
            scale = (b - a) / (hi - lo)
            rows.append({'sequence_id': ident, 'asset_id': segment['asset_id'],
                         'source_path': segment['source_path'], 'source_sha256': segment['source_sha256'],
                         'output_start': first, 'output_end': last,
                         'source_start': a + (first - lo) * scale, 'source_end': a + (last - lo) * scale})
        cursor, previous = hi, segment
    if abs(cursor - float(mapping['duration'])) > 1e-6 or not rows:
        raise ValueError('Visual mapping does not cover this output')
    return {'output_start': start, 'output_end': end, 'source_spans': rows, 'boundaries': boundaries}
