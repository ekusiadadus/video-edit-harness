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
