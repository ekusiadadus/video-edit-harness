"""Pure, review-gated grouping of observed word-timed caption cues.

The plan binds to spelling and occurrence order, while timing is validated
separately so an editor can remap the same observed words onto a new timeline.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections import defaultdict


_MAX_CUES = 100_000
_OPENING_JA = set('([{「『【〈《〔〖〘〚')
_CLOSING_JA = set('、。，．！？!?)]}」』】〉》〕〗〙〛')


def _digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(',', ':'), allow_nan=False).encode('utf-8')).hexdigest()


def _word_id(value):
    if isinstance(value, bool) or not isinstance(value, (str, int)) or (
            isinstance(value, str) and not value):
        raise ValueError('word_id must be a nonempty string or integer (not bool)')
    return value


def _occurrence(value):
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError('occurrence_index must be a nonnegative integer')
    return value


def _number(value, name, *, positive=False):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f'{name} must be finite')
    if positive and value <= 0:
        raise ValueError(f'{name} must be positive')
    return value


def _ref(cue):
    return {'word_id': _cue_id(cue), 'occurrence_index': cue['occurrence_index']}


def _cue_id(cue):
    has_id, has_word_id = 'id' in cue, 'word_id' in cue
    if not (has_id or has_word_id):
        raise ValueError('cue requires id or word_id')
    word_id = _word_id(cue['id'] if has_id else cue['word_id'])
    if has_id and has_word_id and (type(cue['word_id']) is not type(word_id)
                              or cue['word_id'] != word_id):
        raise ValueError('cue id and word_id disagree')
    return word_id


def _key(ref):
    # The type tag keeps integer 1 distinct from string "1" (and bool is rejected).
    return (type(ref['word_id']).__name__, ref['word_id'], ref['occurrence_index'])


def annotate_occurrences(cues):
    """Copy cues and give each word ID an unambiguous occurrence index.

    Explicit indices survive edits/reordering. Missing indices take the first
    unused nonnegative index for that ID, in current stream order.
    """
    if not isinstance(cues, (list, tuple)) or len(cues) > _MAX_CUES:
        raise ValueError('cues must be an array of at most 100000 words')
    used = defaultdict(set)
    for cue in cues:
        if not isinstance(cue, dict):
            raise ValueError('cue must be an object')
        word_id = _cue_id(cue)
        if 'occurrence_index' in cue:
            occurrence = _occurrence(cue['occurrence_index'])
            key = (type(word_id).__name__, word_id)
            if occurrence in used[key]:
                raise ValueError('duplicate word occurrence')
            used[key].add(occurrence)
    next_index = defaultdict(int)
    annotated = []
    for cue in cues:
        word_id = _cue_id(cue)
        key = (type(word_id).__name__, word_id)
        if 'occurrence_index' in cue:
            occurrence = cue['occurrence_index']
        else:
            occurrence = next_index[key]
            while occurrence in used[key]:
                occurrence += 1
            used[key].add(occurrence)
            next_index[key] = occurrence + 1
        annotated.append({**cue, 'occurrence_index': occurrence})
    return annotated


def _validated_cues(cues):
    annotated = annotate_occurrences(cues)
    previous_start = previous_end = None
    for cue in annotated:
        start = _number(cue.get('start'), 'cue start')
        end = _number(cue.get('end'), 'cue end')
        if (start < 0 or end <= start or
                (previous_start is not None and
                 (start < previous_start or end < previous_end))):
            raise ValueError('cues must have positive times with monotonic starts and ends')
        if not isinstance(cue.get('text'), str) or not cue['text'].strip():
            raise ValueError('cue text must be nonempty')
        previous_start, previous_end = start, end
    return annotated


def caption_stream_sha256(cues):
    """Hash the ordered, path-free spelling and identity stream; omit timing."""
    annotated = annotate_occurrences(cues)
    stream = []
    for cue in annotated:
        if not isinstance(cue.get('text'), str) or not cue['text'].strip():
            raise ValueError('cue text must be nonempty')
        stream.append({'word_id': _cue_id(cue), 'occurrence_index': cue['occurrence_index'],
                       'text': cue['text']})
    return _digest(stream)


def _joined_texts(cues):
    # Reuse the existing language-aware whitespace rule without a module import cycle.
    from .edl import _join_caption

    text = ''
    boundary_positions = []
    for cue in cues:
        previous = text.rstrip()
        next_text = cue['text'].lstrip()
        boundary_positions.append(len(previous))
        text = _join_caption(text, next_text)
    return text, boundary_positions[1:]


def _validate_plan(plan, stream_hash):
    if not isinstance(plan, dict) or set(plan) != {
            'version', 'word_stream_sha256', 'language', 'protected_phrases',
            'groups', 'reading'}:
        raise ValueError('caption plan has invalid fields')
    if type(plan['version']) is not int or plan['version'] != 1:
        raise ValueError('caption plan version must be 1')
    if plan['word_stream_sha256'] != stream_hash:
        raise ValueError('caption word stream changed')
    if plan['language'] not in ('ja', 'en'):
        raise ValueError('caption language must be ja or en')
    phrases = plan['protected_phrases']
    if not isinstance(phrases, list) or any(not isinstance(p, str) or not p.strip() for p in phrases):
        raise ValueError('protected_phrases must contain nonempty strings')
    groups = plan['groups']
    if not isinstance(groups, list) or len(groups) > _MAX_CUES:
        raise ValueError('groups must be an array of at most 100000 groups')
    reading = plan['reading']
    if not isinstance(reading, dict) or set(reading) != {'minimum_seconds', 'maximum_units_per_second'}:
        raise ValueError('reading requires minimum_seconds and maximum_units_per_second')
    _number(reading['minimum_seconds'], 'minimum_seconds', positive=True)
    _number(reading['maximum_units_per_second'], 'maximum_units_per_second', positive=True)
    return phrases, groups, reading


def group_reviewed_captions(cues, plan, junctions=()):
    """Apply an exact reviewed grouping; diagnostics still require human review."""
    annotated = _validated_cues(cues)
    stream_hash = caption_stream_sha256(annotated)
    phrases, groups, reading = _validate_plan(plan, stream_hash)
    if not isinstance(junctions, (list, tuple)):
        raise ValueError('junctions must be an array')
    points = sorted(_number(point, 'junction') for point in junctions)
    expected = [_key(_ref(cue)) for cue in annotated]
    observed = []
    seen_ids = set()
    captions = []
    diagnostics = []
    metric = 'nonspace_unicode_codepoints' if plan['language'] == 'ja' else 'whitespace_words'
    offset = 0
    for group in groups:
        if not isinstance(group, dict) or set(group) != {'id', 'word_refs', 'reason'}:
            raise ValueError('caption group has invalid fields')
        group_id, refs, reason = group['id'], group['word_refs'], group['reason']
        if not isinstance(group_id, str) or not group_id.strip() or group_id in seen_ids:
            raise ValueError('caption group IDs must be unique nonempty strings')
        seen_ids.add(group_id)
        if not isinstance(reason, str) or not reason.strip():
            raise ValueError('caption group requires a reason')
        if not isinstance(refs, list) or not refs or len(refs) > _MAX_CUES:
            raise ValueError('caption group requires word_refs')
        keys = []
        for ref in refs:
            if not isinstance(ref, dict) or set(ref) != {'word_id', 'occurrence_index'}:
                raise ValueError('word_ref has invalid fields')
            _word_id(ref['word_id'])
            _occurrence(ref['occurrence_index'])
            keys.append(_key(ref))
        if keys != expected[offset:offset + len(keys)]:
            raise ValueError('caption groups contain unknown, duplicate, or out-of-order word refs')
        observed.extend(keys)
        subset = annotated[offset:offset + len(keys)]
        offset += len(keys)
        start, end = subset[0]['start'], subset[-1]['end']
        if any(start < point < end for point in points):
            raise ValueError('caption group crosses an edit junction')
        text, _ = _joined_texts(subset)
        duration = end - start
        units = len(''.join(text.split())) if plan['language'] == 'ja' else len(text.split())
        rate = units / duration
        caption = {'start': start, 'end': end, 'text': text,
                   'word_refs': [_ref(cue) for cue in subset],
                   'group_id': group_id, 'reason': reason}
        captions.append(caption)
        if len(captions) > 1 and captions[-2]['end'] > start:
            diagnostics.append({'code': 'overlapping_captions',
                                'previous_group_id': captions[-2]['group_id'],
                                'group_id': group_id,
                                'overlap_seconds': captions[-2]['end'] - start})
        if duration < reading['minimum_seconds']:
            diagnostics.append({'code': 'short_duration', 'group_id': group_id,
                                'seconds': duration, 'minimum_seconds': reading['minimum_seconds']})
        if rate > reading['maximum_units_per_second']:
            diagnostics.append({'code': 'fast_reading', 'group_id': group_id,
                                'metric': metric, 'units': units, 'units_per_second': rate,
                                'maximum_units_per_second': reading['maximum_units_per_second']})
        if plan['language'] == 'ja' and text:
            if text[0] in _CLOSING_JA:
                diagnostics.append({'code': 'leading_closing_punctuation', 'group_id': group_id})
            if text[-1] in _OPENING_JA:
                diagnostics.append({'code': 'trailing_opening_punctuation', 'group_id': group_id})
    if observed != expected:
        raise ValueError('caption groups are missing word refs')
    complete_text, boundaries = _joined_texts(annotated)
    group_boundaries = []
    consumed = 0
    for group in groups[:-1]:
        consumed += len(group['word_refs'])
        group_boundaries.append(boundaries[consumed - 1])
    for phrase in phrases:
        for match in re.finditer(re.escape(phrase), complete_text):
            if any(match.start() < boundary < match.end() for boundary in group_boundaries):
                raise ValueError(f'protected phrase split across caption groups: {phrase}')
    return {'captions': captions, 'diagnostics': diagnostics, 'language': plan['language'],
            'word_stream_sha256': stream_hash, 'plan_sha256': _digest(plan),
            'status': 'review_required', 'reading_metric': metric}
