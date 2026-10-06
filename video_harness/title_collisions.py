"""Check measured title cards against other title cards on output frames.

The first frame of each title is transparent in the effects renderer's fade-in.
Every later original frame is treated as visible, including frames in either fade.
Mapped titles may begin visibly; held original first frames remain transparent.
"""

from __future__ import annotations

from fractions import Fraction
import math

from .video_effects import _frame, _time


def _bounds(value, description):
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        raise ValueError(f'{description} requires four normalized coordinates')
    if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v)
           for v in value):
        raise ValueError(f'{description} requires finite numeric coordinates')
    x0, y0, x1, y1 = value
    if not (0 <= x0 < x1 <= 1 and 0 <= y0 < y1 <= 1):
        raise ValueError(f'{description} must be inside the frame with positive area')
    return tuple(value)


def _intersects(a, b):
    # Ignore floating arithmetic noise at shared pixel edges, not a margin.
    return (min(a[2], b[2])-max(a[0], b[0]) > 1e-12 and
            min(a[3], b[3])-max(a[1], b[1]) > 1e-12)


def check_title_collisions(events, title_assets, *, fps):
    """Return evidence for visible title pairs, rejecting any measured overlap.

    Intervals use output frames and exclusive ends. ``frame_positions``, when
    supplied, must cover the event's declared interval exactly; tracked titles
    always require it. Returned times are exact rational strings for JSON.
    Only declared event intervals and measured asset bounds are considered.
    """
    try:
        rate = Fraction(str(fps))
    except (TypeError, ValueError, ZeroDivisionError) as exc:
        raise ValueError('Title collision FPS must be a positive rational') from exc
    if rate <= 0:
        raise ValueError('Title collision FPS must be a positive rational')
    if not isinstance(events, (list, tuple)) or not isinstance(title_assets, (list, tuple)):
        raise ValueError('Title events and assets must be sequences')

    selected = []
    seen = set()
    for event in events:
        if not isinstance(event, dict):
            raise ValueError('Title event must be an object')
        if event.get('type') not in {'keyword_title', 'tracked_title'}:
            continue
        event_id = event.get('id')
        if not isinstance(event_id, str) or not event_id.strip() or event_id in seen:
            raise ValueError('Title event IDs must be nonempty and unique')
        seen.add(event_id)
        first = _frame(_time(event.get('output_start'), f'{event_id} start'), rate, f'{event_id} start')
        last = _frame(_time(event.get('output_end'), f'{event_id} end'), rate, f'{event_id} end')
        if first < 0 or last <= first:
            raise ValueError(f'Title {event_id} has an invalid output interval')
        selected.append((event, first, last))

    assets = {}
    for asset in title_assets:
        if not isinstance(asset, dict) or not isinstance(asset.get('event_id'), str):
            raise ValueError('Measured title asset needs an event_id')
        event_id = asset['event_id']
        if event_id in assets:
            raise ValueError(f'Duplicate measured title asset for {event_id}')
        assets[event_id] = asset

    prepared = []
    for event, first, last in selected:
        event_id = event['id']
        if event_id not in assets:
            raise ValueError(f'Missing measured title asset for {event_id}')
        asset = assets[event_id]
        fixed = _bounds(asset.get('bounds'), f'Title {event_id} bounds')
        positions = None
        if 'frame_positions' in asset:
            rows = asset['frame_positions']
            if not isinstance(rows, (list, tuple)):
                raise ValueError(f'Title {event_id} frame_positions must be a sequence')
            positions = {}
            for row in rows:
                if not isinstance(row, dict) or type(row.get('frame')) is not int:
                    raise ValueError(f'Title {event_id} position needs an integer frame')
                frame = row['frame']
                if frame in positions:
                    raise ValueError(f'Duplicate position for title {event_id} at frame {frame}')
                if not first <= frame < last:
                    raise ValueError(f'Title {event_id} position outside interval at frame {frame}')
                positions[frame] = _bounds(row.get('bounds'), f'Title {event_id} frame {frame} bounds')
            for frame in range(first, last):
                if frame not in positions:
                    raise ValueError(f'Missing position for title {event_id} at frame {frame}')
        if event['type'] == 'tracked_title' and positions is None:
            raise ValueError(f'Missing positions for tracked title {event_id}')
        if event.get('parameters', {}).get('motion') == 'rise' and positions is None:
            raise ValueError(f'Missing positions for rising title {event_id}')
        phase = event.get('phase_map')
        if phase is not None:
            if event['type'] != 'keyword_title' or not isinstance(phase, dict) or set(phase) != {'version', 'original_frame_count', 'frames'}:
                raise ValueError(f'Title {event_id} has an invalid phase map')
            count, frames = phase['original_frame_count'], phase['frames']
            if type(phase['version']) is not int or phase['version'] != 1 or type(count) is not int or not 1 <= count <= 4096:
                raise ValueError(f'Title {event_id} has an invalid phase map')
            if not isinstance(frames, list) or len(frames) != last-first or len(frames) > 4096 or any(type(value) is not int or not 0 <= value < count for value in frames):
                raise ValueError(f'Title {event_id} has an invalid phase map')
            if any(left > right for left, right in zip(frames, frames[1:])):
                raise ValueError(f'Title {event_id} has an invalid phase map')
            visible = next((first + offset for offset, old in enumerate(frames) if old > 0), last)
        else:
            visible = first + 1
        prepared.append((event_id, first, last, fixed, positions, visible))

    evidence = []
    for index, (first_id, first_start, first_end, first_bounds, first_positions, first_visible) in enumerate(prepared):
        for second_id, second_start, second_end, second_bounds, second_positions, second_visible in prepared[index + 1:]:
            start, end = max(first_visible, second_visible), min(first_end, second_end)
            if start >= end:
                continue
            for frame in range(start, end):
                a = first_positions[frame] if first_positions is not None else first_bounds
                b = second_positions[frame] if second_positions is not None else second_bounds
                if _intersects(a, b):
                    instant = str(Fraction(frame, 1) / rate)
                    raise ValueError(
                        f'Title collision: {first_id} and {second_id} at frame {frame} '
                        f'(output time {instant}s)')
            evidence.append({
                'event_ids': [first_id, second_id],
                'output_start': str(Fraction(start, 1) / rate),
                'output_end': str(Fraction(end, 1) / rate),
                'status': 'no_detected_conflict',
                'frames_checked': end - start,
            })
    return evidence
