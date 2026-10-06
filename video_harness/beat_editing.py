"""Review-required visual cut proposals on mapped beats; speech plans stay fixed."""
from __future__ import annotations

from copy import deepcopy
from fractions import Fraction
import math
from pathlib import Path

from .cues import _seconds
from .render_cache import digest
from .visual import _video_info, validate_visual_edl


ACTORS = {'human', 'codex', 'claude_code', 'automation'}


def _time(value, label):
    value = str(value)
    return _seconds(value[:-1] if value.endswith('s') else value, label)


def _parameters(max_shift, min_hold, allowed_intervals, duration):
    shift = _time(max_shift, 'max_shift')
    hold = _time(min_hold, 'min_hold')
    if shift <= 0 or hold <= 0:
        raise ValueError('max_shift and min_hold must be positive')
    if not isinstance(allowed_intervals, (list, tuple)) or not allowed_intervals:
        raise ValueError('Explicit nonspoken allowed_intervals are required')
    intervals = []
    for item in allowed_intervals:
        if not isinstance(item, (list, tuple)) or len(item) != 2:
            raise ValueError('Invalid allowed interval')
        first, last = (_time(value, 'allowed interval') for value in item)
        if not 0 <= first < last <= duration:
            raise ValueError('Allowed interval exceeds current output')
        intervals.append((first, last))
    intervals.sort()
    if any(left[1] > right[0] for left, right in zip(intervals, intervals[1:])):
        raise ValueError('Allowed intervals overlap')
    return shift, hold, intervals


def _within_same_allowed(original, target, intervals):
    return any(start < original < end and start < target < end for start, end in intervals)


def _crosses_protected(original, target, protected):
    low, high = sorted((original, target))
    return any(low < end and high > start for start, end in protected)


def _source_end(first, original_end, source_rate, output_rate, target_length, upper):
    """Find a real source frame whose rendered output length equals target frames."""
    center = Fraction(first, 1) + Fraction(target_length, 1) * source_rate / output_rate
    near = math.floor(center)
    feasible = []
    for frame in range(max(first + 1, near - 3), min(upper, near + 3) + 1):
        if round(Fraction(frame - first, 1) * output_rate / source_rate) == target_length:
            feasible.append(frame)
    return min(feasible, key=lambda frame: (abs(frame - original_end), frame)) if feasible else None


def annotate_speech_beats(plan, mapped_beats):
    """Mark mapped beats for v2/v3 inspection without modifying speech timing."""
    if not isinstance(plan, dict) or plan.get('version') not in (2, 3):
        raise ValueError('Speech beat annotation requires v2/v3 plan')
    if not isinstance(mapped_beats, dict) or not isinstance(mapped_beats.get('beats'), list):
        raise ValueError('Invalid mapped beats')
    return {'kind': 'marks_only', 'plan_sha256': digest(plan),
            'beatmap_sha256': digest(mapped_beats),
            'marks': [{'frame': item['frame'], 'frame_time': item['frame_time'],
                       'protected_speech': item.get('protected_speech', True)}
                      for item in mapped_beats['beats']],
            'timing_changed': False}


def suggest_beat_revision(plan, mapping, mapped_beats, assets, max_shift, min_hold,
                          allowed_intervals, actor, reason):
    """Optimize all visual cut suggestions together; return (proposed plan, evidence).

    Each visual segment keeps its source first frame. Only its end frame may
    change, so no word, source in-point or shot order is invented. No revision
    is approved by this function.
    """
    if not isinstance(plan, dict) or plan.get('version') != 4 or plan.get('edit_basis') != 'visual':
        raise ValueError('Beat cut revisions require visual v4 EDL; speech plans permit marks only')
    if actor not in ACTORS or not isinstance(reason, str) or not reason.strip():
        raise ValueError('Beat revision requires actual actor and reason')
    if not isinstance(mapping, dict) or mapping.get('edit_basis') != 'visual' or not isinstance(mapping.get('sequence'), list):
        raise ValueError('Source-bound visual frame mapping is required')
    if mapping.get('retime'):
        raise ValueError('Beat cut revision needs pre-retime mapping; replan cuts before the ramp')
    if not isinstance(mapped_beats, dict) or not isinstance(mapped_beats.get('beats'), list):
        raise ValueError('Mapped beat evidence is required')
    normalized = validate_visual_edl(plan, assets)
    sequence = normalized['sequence']
    rows = mapping['sequence']
    if len(rows) != len(sequence) or len(sequence) < 2:
        raise ValueError('Mapping must cover at least two visual shots')
    output_rate = _time(mapping.get('fps'), 'mapping fps')
    beat_rate = _time(mapped_beats.get('fps'), 'beat fps')
    if output_rate <= 0 or beat_rate != output_rate:
        raise ValueError('Beat map and frame mapping FPS differ')
    duration = _time(mapping.get('duration'), 'mapping duration')
    shift, hold, intervals = _parameters(max_shift, min_hold, allowed_intervals, duration)
    shift_frames = math.floor(shift * output_rate)
    hold_frames = math.ceil(hold * output_rate)
    if shift_frames < 1:
        raise ValueError('max_shift is smaller than one output frame')
    by_id = {item['asset_id']: item for item in assets}
    info = {key: _video_info(asset['path']) for key, asset in by_id.items() if key in {s['asset_id'] for s in sequence}}
    previous_end = 0
    for span, row in zip(sequence, rows):
        if row.get('id') != span['id'] or row.get('asset_id') != span['asset_id'] or row.get('source_sha256') != by_id[span['asset_id']]['sha256']:
            raise ValueError('Visual mapping does not match plan or source')
        if row.get('source_path') is not None and Path(row['source_path']).resolve() != Path(by_id[span['asset_id']]['path']).resolve():
            raise ValueError('Visual mapping source path changed')
        if row.get('source_first_frame') != span['source_first_frame'] or row.get('source_end_frame_exclusive') != span['source_end_frame_exclusive']:
            raise ValueError('Visual mapping source frame binding changed')
        if _time(row.get('source_fps'), 'source fps') != _time(span['source_fps'], 'source fps'):
            raise ValueError('Visual mapping source FPS changed')
        for label, frame in (('source_start', span['source_first_frame']),
                             ('source_end', span['source_end_frame_exclusive'])):
            if label in row and _time(row[label], label) != Fraction(frame, 1) / Fraction(span['source_fps']):
                raise ValueError('Visual mapping source time differs from frame')
        if row.get('output_first_frame') != previous_end or type(row.get('output_end_frame_exclusive')) is not int:
            raise ValueError('Visual mapping output frames are not contiguous')
        for label, frame in (('output_start', previous_end), ('output_end', row['output_end_frame_exclusive'])):
            if label in row and _time(row[label], label) != Fraction(frame, 1) / output_rate:
                raise ValueError('Visual mapping output time differs from frame')
        expected = round(Fraction(span['source_end_frame_exclusive'] - span['source_first_frame'], 1)
                         * output_rate / Fraction(span['source_fps']))
        if row['output_end_frame_exclusive'] - previous_end != expected:
            raise ValueError('Visual mapping output length differs from source frames')
        previous_end = row['output_end_frame_exclusive']
    if previous_end != mapping.get('frame_count') or abs(Fraction(previous_end, 1) / output_rate - duration) > Fraction(1, 1000):
        raise ValueError('Visual mapping duration changed')
    protected = [(_time(a, 'protected start'), _time(b, 'protected end'))
                 for a, b in mapped_beats.get('protected_intervals', [])]
    eligible = set()
    for item in mapped_beats['beats']:
        if type(item.get('frame')) is not int or item.get('cut_eligible') is not True or item.get('protected_speech') is True or item.get('loop_seam_nearby') is True:
            continue
        frame = item['frame']
        if frame < 0 or abs(_time(item.get('frame_time'), 'beat frame time') - Fraction(frame, 1) / output_rate) > Fraction(1, 1000):
            raise ValueError('Mapped beat frame/time mismatch')
        if not any(a <= Fraction(frame, 1) / output_rate < b for a, b in protected):
            eligible.add(frame)
    # Dynamic programming over cumulative cut frames. Local greedy choices can
    # make a later beat unreachable, so score complete feasible paths instead.
    states = {0: ((), (), (), ())}  # output frame -> (source ends, snapped, errors, cuts)
    decisions = []
    for index, (span, row) in enumerate(zip(sequence[:-1], rows[:-1])):
        original = row['output_end_frame_exclusive']
        original_time = Fraction(original, 1) / output_rate
        candidates = {original}
        candidates.update(frame for frame in eligible if abs(frame - original) <= shift_frames
                          and _within_same_allowed(original_time, Fraction(frame, 1) / output_rate, intervals)
                          and not _crosses_protected(original_time, Fraction(frame, 1) / output_rate, protected))
        next_states = {}
        upper = info[span['asset_id']]['frame_count']
        if upper is None:
            upper = math.floor(info[span['asset_id']]['duration'] * info[span['asset_id']]['fps'])
        if span['asset_id'] == sequence[index + 1]['asset_id'] and span['source_end_frame_exclusive'] <= sequence[index + 1]['source_first_frame']:
            upper = min(upper, sequence[index + 1]['source_first_frame'])
        for previous, (ends, snaps, errors, cuts) in states.items():
            for cut in sorted(candidates):
                length = cut - previous
                if length < hold_frames:
                    continue
                end = _source_end(span['source_first_frame'], span['source_end_frame_exclusive'],
                                  Fraction(span['source_fps']), output_rate, length, upper)
                if end is None:
                    continue
                snap = cut in eligible and _within_same_allowed(original_time, Fraction(cut, 1) / output_rate, intervals)
                trial = (ends + (end,), snaps + (snap,), errors + (abs(cut - original),), cuts + (cut,))
                score = (-sum(trial[1]), sum(trial[2]), tuple(trial[2]), trial[3], trial[0])
                current = next_states.get(cut)
                if current is None or score < (-sum(current[1]), sum(current[2]), tuple(current[2]), current[3], current[0]):
                    next_states[cut] = trial
        if not next_states:
            raise ValueError(f'No safe source-frame revision for cut {span["id"]}')
        states = next_states
        decisions.append({'cut_id': span['id'], 'original_frame': original,
                          'candidate_frames': sorted(candidates)})
    last = sequence[-1]
    last_frames = rows[-1]['output_end_frame_exclusive'] - rows[-1]['output_first_frame']
    feasible = [(cut, state) for cut, state in states.items() if last_frames >= hold_frames]
    if not feasible:
        raise ValueError('Final shot violates minimum hold')
    _, chosen = min(feasible, key=lambda entry: (-sum(entry[1][1]), sum(entry[1][2]),
                                                  tuple(entry[1][2]), entry[1][3], entry[1][0]))
    revised = deepcopy(normalized)
    old = revised.pop('review', None)
    revised['status'] = 'proposed'
    revised['revision'] = {'actor': actor, 'reason': reason.strip(), 'kind': 'beat_cut_proposal',
                           'parent_plan_sha256': digest(plan), 'mapping_sha256': digest(mapping),
                           'beatmap_sha256': digest(mapped_beats)}
    for segment, end in zip(revised['sequence'][:-1], chosen[0]):
        segment['source_end_frame_exclusive'] = end
        segment['source_end'] = str(Fraction(end, 1) / Fraction(segment['source_fps']))
    revised = validate_visual_edl(revised, assets)
    evidence = {'version': 1, 'kind': 'visual_beat_cut_proposal', 'actor': actor,
                'reason': reason.strip(), 'plan_sha256': digest(plan),
                'mapping_sha256': digest(mapping), 'beatmap_sha256': digest(mapped_beats),
                'source_assets': {aid: by_id[aid]['sha256'] for aid in sorted(info)},
                'max_shift': str(shift), 'min_hold': str(hold),
                'allowed_intervals': [[str(a), str(b)] for a, b in intervals],
                'cuts': [{**decision, 'suggested_frame': chosen[3][i],
                          'source_end_frame': chosen[0][i], 'snapped': chosen[1][i]}
                         for i, decision in enumerate(decisions)],
                'status': 'review_required', 'prior_review': old,
                'new_plan_sha256': digest(revised),
                'note': 'New output mapping and cue positions must be regenerated after review.'}
    return revised, evidence
