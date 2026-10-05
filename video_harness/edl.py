"""Transcript-backed edit decisions and source-to-output word timing."""
import hashlib
import json
import math
import re
from pathlib import Path

from .common import fingerprint
from .pacing import keep_intervals

DEFAULTS = {
    'minimum_gap': 0.8,
    'minimum_cut': 0.2,
    'keep_after': 0.18,
    'keep_before': 0.16,
    'word_padding': 0.08,
    'minimum_retained_boundary_gap': 0.5,
}


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                     separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def _time(value, name):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f'Invalid {name}')
    return float(value)


def _range(value, duration, name):
    if isinstance(value, dict):
        start, end = value['start'], value['end']
    else:
        start, end = value
    start, end = _time(start, name), _time(end, name)
    if not 0 <= start < end <= duration:
        raise ValueError(f'Invalid {name}')
    return start, end


def _overlap(a, b):
    return a[0] < b[1] and b[0] < a[1]


def _transcript(transcript):
    if not isinstance(transcript, dict) or transcript.get('version') != 1 or not isinstance(transcript.get('source'), dict):
        raise ValueError('Expected version 1 transcript with source fingerprint')
    duration = _time(transcript.get('duration'), 'transcript duration')
    if duration <= 0:
        raise ValueError('Invalid transcript duration')
    for field in ('words', 'segments'):
        if not isinstance(transcript.get(field), list):
            raise ValueError(f'Missing transcript {field}')
        ids = set()
        previous_end = 0.0
        for item in transcript[field]:
            if not isinstance(item, dict) or not isinstance(item.get('text'), str):
                raise ValueError(f'Invalid transcript {field}')
            if not isinstance(item.get('id'), (str, int)) or isinstance(item.get('id'), bool) or item['id'] in ids:
                raise ValueError(f'Invalid or duplicate {field} id')
            ids.add(item['id'])
            start, end = _range(item, duration, field)
            if field == 'words' and start < previous_end:
                raise ValueError(f'Overlapping or unordered transcript {field}')
            previous_end = end
            if field == 'words':
                p = _time(item.get('probability'), 'word probability')
                if not 0 <= p <= 1:
                    raise ValueError('Invalid word probability')
    return duration


def _settings(cfg):
    editorial = cfg.get('editorial', {})
    settings = {key: _time(editorial.get(key, value), key) for key, value in DEFAULTS.items()}
    if any(value < 0 for value in settings.values()) or settings['minimum_gap'] <= 0 or settings['minimum_cut'] <= 0:
        raise ValueError('Invalid editorial settings')
    return settings


def build_plan(cfg, transcript, silences=None):
    """Propose disabled pause cuts; acoustic silence is required for cut eligibility."""
    duration = _transcript(transcript)
    source = fingerprint(cfg['source'])
    if source != transcript['source']:
        raise ValueError('Transcript source changed')
    settings = _settings(cfg)
    protected = cfg.get('editorial', {}).get('protected_ranges', [])
    for item in protected:
        _range(item, duration, 'protected range')
    acoustic = None if silences is None else sorted(_range(item, duration, 'silence') for item in silences)
    cuts = []
    words = transcript['words']
    for left, right in zip(words, words[1:]):
        gap = right['start'] - left['end']
        if gap < settings['minimum_gap']:
            continue
        after, before = settings['keep_after'], settings['keep_before']
        boundary = bool(re.search(r'[.!?。！？][\s”’"\']*$', left['text']))
        if boundary:
            extra = max(0, settings['minimum_retained_boundary_gap'] - after - before) / 2
            after += extra
            before += extra
        available = (left['end'] + after, right['start'] - before)
        spans = [available] if acoustic is None else [
            (max(available[0], start), min(available[1], end)) for start, end in acoustic
        ]
        for start, end in spans:
            if end - start + 1e-9 < settings['minimum_cut']:
                continue
            start, end = round(start, 6), round(end, 6)
            if end <= start:
                continue
            if any(_overlap((start, end), _range(item, duration, 'protected range')) for item in protected):
                continue
            cuts.append({'id': len(cuts) + 1, 'start': start, 'end': end,
                         'enabled': False, 'kind': 'pause',
                         'reason': 'Acoustic silence in transcript gap; review breathing and meaning.' if acoustic is not None
                                   else 'Transcript gap only; confirm acoustic silence before enabling.',
                         'previous_words': [left['text']], 'next_words': [right['text']], 'review_note': ''})
    plan = {'version': 2, 'source': source, 'duration': duration,
            'transcript_sha256': _digest(transcript), 'transcript': json.loads(json.dumps(transcript)),
            'cuts': cuts, 'protected_ranges': json.loads(json.dumps(protected)),
            'acoustic_intervals': acoustic,
            'status': 'review_required', 'editing_settings': settings,
            'warnings': ['transcript_only: acoustic silence has not been checked'] if acoustic is None else []}
    validate_plan(plan)
    return plan


def validate_plan(plan, verify_source=False):
    """Return kept source intervals after validating all edit decisions."""
    if plan.get('version') not in (2, 3):
        raise ValueError('Expected version 2 or 3 edit plan')
    transcript = plan.get('transcript')
    duration = _transcript(transcript)
    if _time(plan.get('duration'), 'plan duration') != duration or plan.get('source') != transcript['source']:
        raise ValueError('Plan and transcript source or duration differ')
    if _digest(transcript) != plan.get('transcript_sha256'):
        raise ValueError('Transcript evidence changed')
    if verify_source and fingerprint(plan['source']['path']) != plan['source']:
        raise ValueError('Source changed since transcription')
    settings = plan.get('editing_settings')
    if not isinstance(settings, dict):
        raise ValueError('Missing editing settings')
    padding = _time(settings.get('word_padding'), 'word padding')
    if padding < 0:
        raise ValueError('Invalid word padding')
    protected = [_range(item, duration, 'protected range') for item in plan.get('protected_ranges', [])]
    acoustic = plan.get('acoustic_intervals')
    if acoustic is not None:
        acoustic = [_range(item, duration, 'silence') for item in acoustic]
    words = transcript['words']
    word_ids = {word['id'] for word in words}
    cuts = plan.get('cuts')
    if not isinstance(cuts, list):
        raise ValueError('Invalid cuts')
    if plan['version'] == 3 and cuts:
        raise ValueError('Version 3 sequence cannot also contain cuts')
    ids = set()
    for cut in cuts:
        if not isinstance(cut, dict) or not isinstance(cut.get('id'), int) or isinstance(cut.get('id'), bool) or cut['id'] in ids:
            raise ValueError('Invalid or duplicate cut id')
        ids.add(cut['id'])
        start, end = _range(cut, duration, 'cut')
        if type(cut.get('enabled')) is not bool or cut.get('kind') not in ('pause', 'speech'):
            raise ValueError('Invalid cut decision')
        if any(_overlap((start, end), span) for span in protected):
            raise ValueError('Cut overlaps protected range')
        if cut['enabled'] and not str(cut.get('review_note', '')).strip():
            raise ValueError('Enabled cut requires review note')
        overlapping = [word for word in words if _overlap((start, end), (word['start'], word['end']))]
        if cut['kind'] == 'pause':
            if any(_overlap((start, end), (max(0, word['start'] - padding), min(duration, word['end'] + padding))) for word in words):
                raise ValueError('Pause cut overlaps padded word')
            if cut['enabled'] and (acoustic is None or not any(a <= start < end <= b for a, b in acoustic)):
                raise ValueError('Enabled pause requires acoustic silence evidence')
        else:
            removed = cut.get('removed_word_ids')
            if not cut['enabled'] or not isinstance(removed, list) or len(set(removed)) != len(removed) or set(removed) != {w['id'] for w in overlapping} or not set(removed) <= word_ids:
                raise ValueError('Speech cut requires exact removed word ids')
            if any(not start <= word['start'] < word['end'] <= end for word in overlapping):
                raise ValueError('Speech cut would remove part of a word')
    if plan['version'] == 3:
        return _validate_sequence(plan, protected)
    return keep_intervals(plan)


def _validate_sequence(plan, protected):
    """Validate exact transcript partition and preserve editorial playback order."""
    if plan.get('status') not in ('review_required', 'reviewed_selection'):
        raise ValueError('Invalid story review status')
    if plan['status'] == 'reviewed_selection':
        review = plan.get('review')
        if not isinstance(review, dict) or not str(review.get('actor', '')).strip() or not str(review.get('note', '')).strip():
            raise ValueError('Reviewed selection requires actor and note')
    brief = plan.get('brief')
    if not isinstance(brief, dict) or brief.get('version') != 1:
        raise ValueError('Missing story brief')
    goals = brief.get('goals')
    if not isinstance(goals, list) or any(not isinstance(g, dict) or not isinstance(g.get('id'), str) or not g['id'] or not isinstance(g.get('text'), str) or not g['text'].strip() for g in goals):
        raise ValueError('Invalid story goals')
    goal_ids = [g['id'] for g in goals]
    if len(set(goal_ids)) != len(goal_ids):
        raise ValueError('Duplicate story goal id')
    sequence = plan.get('sequence')
    if not isinstance(sequence, list) or not sequence:
        raise ValueError('Empty or invalid story sequence')
    words = plan['transcript']['words']
    all_ids = {w['id'] for w in words}
    seen_ids, retained, ranges = set(), set(), []
    for item in sequence:
        if not isinstance(item, dict) or not isinstance(item.get('id'), (str, int)) or isinstance(item.get('id'), bool) or item['id'] in seen_ids:
            raise ValueError('Invalid or duplicate sequence id')
        seen_ids.add(item['id'])
        start, end = _range(item, plan['duration'], 'sequence')
        if not str(item.get('chapter_id', '')).strip() or not str(item.get('reason', '')).strip():
            raise ValueError('Sequence needs chapter and reason')
        ids = item.get('goal_ids')
        if not isinstance(ids, list) or not ids or len(set(ids)) != len(ids) or not set(ids) <= set(goal_ids):
            raise ValueError('Sequence needs valid goal ids')
        for fade_key in ('fade_in_seconds', 'fade_out_seconds'):
            fade = _time(item.get(fade_key, 0), fade_key)
            if fade < 0 or fade > .2 or fade > end - start:
                raise ValueError('Invalid sequence fade')
        if any(_overlap((start, end), other) for other in ranges):
            raise ValueError('Overlapping sequence ranges')
        ranges.append((start, end))
        covered = [w for w in words if _overlap((start, end), (w['start'], w['end']))]
        if not covered or any(not start <= w['start'] < w['end'] <= end for w in covered):
            raise ValueError('Sequence has no complete anchored words')
        if item.get('start_word_id') != covered[0]['id'] or item.get('end_word_id') != covered[-1]['id']:
            raise ValueError('Sequence word anchors do not match retained words')
        if start + item.get('fade_in_seconds', 0) > min(w['start'] for w in covered) + 1e-9 or end - item.get('fade_out_seconds', 0) < max(w['end'] for w in covered) - 1e-9:
            raise ValueError('Sequence fade overlaps retained words')
        for word in covered:
            if word['id'] in retained:
                raise ValueError('Duplicate retained word')
            retained.add(word['id'])
    omitted = plan.get('omitted_word_ids')
    if not isinstance(omitted, list) or len(set(omitted)) != len(omitted) or set(omitted) != all_ids - retained:
        raise ValueError('Omitted word ids must match exact unselected words')
    must_keep = brief.get('must_keep_word_ids', [])
    if not isinstance(must_keep, list) or not set(must_keep) <= retained:
        raise ValueError('Must-keep words were omitted')
    if any(not any(a <= p and q <= b for a, b in ranges) for p, q in protected):
        raise ValueError('Protected range is not fully retained')
    omissions = plan.get('omissions', [])
    if not isinstance(omissions, list):
        raise ValueError('Invalid omission evidence')
    evidenced = set()
    for omission in omissions:
        ids = omission.get('word_ids') if isinstance(omission, dict) else None
        goals = omission.get('goal_ids') if isinstance(omission, dict) else None
        if not isinstance(ids, list) or not ids or len(set(ids)) != len(ids) or not set(ids) <= set(omitted) or evidenced.intersection(ids) or not str(omission.get('reason', '')).strip() or not isinstance(goals, list) or not goals or not set(goals) <= set(goal_ids):
            raise ValueError('Omission needs exact words, reason and goals')
        evidenced.update(ids)
    if evidenced != set(omitted):
        raise ValueError('Omission evidence does not cover omitted words')
    return ranges


def derive_edit(plan):
    keeps = validate_plan(plan)
    duration = round(sum(end - start for start, end in keeps), 6)
    return {'keep': keeps, 'duration': duration,
            'removed_seconds': round(plan['duration'] - duration, 6),
            'cuts_enabled': [cut['id'] for cut in plan['cuts'] if cut['enabled']]}


def remap_subtitles(plan, keep=None):
    """Return surviving transcript words with their times on the edited timeline."""
    validated = validate_plan(plan)
    keeps = validated
    if keep is not None:
        keeps = []
        for index, span in enumerate(keep):
            limit = plan['duration'] + (0.05 if index == len(keep) - 1 else 0)
            keeps.append(_range(span, limit, 'aligned keep'))
    if keep is not None and (len(keeps) != len(validated) or any(abs(a - original_start) > 0.05 or abs(b - original_end) > 0.05
                            for (a, b), (original_start, original_end) in zip(keeps, validated))
                            or (plan['version'] == 2 and any(left[1] > right[0] for left, right in zip(keeps, keeps[1:])))):
        raise ValueError('Aligned keep differs from reviewed keep intervals')
    cues = []
    offset = 0.0
    for start, end in keeps:
        for word in plan['transcript']['words']:
            if start <= word['start'] and word['end'] <= end:
                cues.append({'id': word['id'], 'start': round(offset + word['start'] - start, 6),
                             'end': round(offset + word['end'] - start, 6), 'text': word['text']})
            elif plan['version'] == 3 and _overlap((start, end), (word['start'], word['end'])):
                raise ValueError('Aligned keep would partially drop a retained word')
        offset += end - start
    if plan['version'] == 3 and {c['id'] for c in cues} != {w['id'] for w in plan['transcript']['words']} - set(plan['omitted_word_ids']):
        raise ValueError('Aligned keep would drop a retained word')
    return cues


def _srt_time(seconds):
    milliseconds = round(seconds * 1000)
    hours, remainder = divmod(milliseconds, 3600000)
    minutes, remainder = divmod(remainder, 60000)
    secs, milliseconds = divmod(remainder, 1000)
    return f'{hours:02}:{minutes:02}:{secs:02},{milliseconds:03}'


def _join_caption(previous, current):
    left, right = previous.rstrip(), current.lstrip()
    if not left:
        return right
    if not right:
        return left
    if re.search(r'[A-Za-z0-9]$', left) and re.match(r'[A-Za-z0-9]', right):
        return left + ' ' + right
    return left + right


def group_captions(cues, junctions=(), max_chars=24, max_duration=4.0, gap=0.6):
    """Group timed word cues into readable phrases without crossing an edit junction."""
    captions = []
    current = None
    for cue in cues:
        start, end = _time(cue['start'], 'cue start'), _time(cue['end'], 'cue end')
        if not 0 <= start < end or not isinstance(cue.get('text'), str):
            raise ValueError('Invalid subtitle cue')
        candidate = _join_caption(current['text'], cue['text']) if current else cue['text'].strip()
        boundary = current and (
            start - current['end'] >= gap or
            end - current['start'] > max_duration or
            len(candidate) > max_chars or
            re.search(r'[.!?。！？][”’"\']*$', current['text']) or
            any(current['end'] <= point <= start for point in junctions)
        )
        if boundary:
            captions.append(current)
            current = None
        if current is None:
            current = {'start': start, 'end': end, 'text': cue['text'].strip()}
        else:
            current['end'] = end
            current['text'] = candidate
    if current:
        captions.append(current)
    return captions


def write_srt(plan, path, keep=None):
    cues = remap_subtitles(plan, keep=keep)
    keeps = validate_plan(plan) if keep is None else keep
    junctions = []
    elapsed = 0.0
    for start, end in keeps[:-1]:
        elapsed += end - start
        junctions.append(elapsed)
    cues = group_captions(cues, junctions=junctions)
    body = ''.join(f"{index}\n{_srt_time(cue['start'])} --> {_srt_time(cue['end'])}\n{cue['text']}\n\n"
                   for index, cue in enumerate(cues, 1))
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open('x') as stream:
        stream.write(body)
    return target
