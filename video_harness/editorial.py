"""Explicit, transcript anchored story decisions. No semantic inference occurs here."""

import copy

from .common import fingerprint
from .edl import _digest, _settings, _transcript, validate_plan


def make_brief(cfg, data=None):
    """Normalize only supplied editorial intent; unknown fields stay unresolved."""
    supplied = {**cfg.get('editorial', {}), **(data or {})}
    goals = supplied.get('goals')
    if goals is None:
        goal = supplied.get('goal')
        goals = [{'id': 'goal-1', 'text': goal}] if isinstance(goal, str) and goal.strip() else []
    brief = {'version': 1, 'audience': supplied.get('audience'),
             'target_duration_seconds': supplied.get('target_duration_seconds'),
             'goals': copy.deepcopy(goals),
             'must_keep_word_ids': copy.deepcopy(supplied.get('must_keep_word_ids', []))}
    for key in ('style', 'reference', 'priority', 'protect', 'review', 'acceptable_omissions', 'must_keep_claims'):
        if key in supplied:
            brief[key] = copy.deepcopy(supplied[key])
        elif key in cfg:
            brief[key] = copy.deepcopy(cfg[key])
    if brief['target_duration_seconds'] is not None:
        value = brief['target_duration_seconds']
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 < value < float('inf'):
            raise ValueError('Invalid target duration')
    if not isinstance(brief['goals'], list) or not isinstance(brief['must_keep_word_ids'], list):
        raise ValueError('Invalid brief goals or must-keep words')
    ids = [g.get('id') for g in brief['goals'] if isinstance(g, dict)]
    if len(ids) != len(brief['goals']) or len(set(ids)) != len(ids) or any(not isinstance(g.get('id'), str) or not g['id'].strip() or not isinstance(g.get('text'), str) or not g['text'].strip() for g in brief['goals']):
        raise ValueError('Brief goals require unique IDs and nonempty text')
    if len(set(brief['must_keep_word_ids'])) != len(brief['must_keep_word_ids']):
        raise ValueError('Duplicate must-keep word ID')
    if 'editing_pattern' in cfg or 'editing_pattern' in supplied:
        from .production import frozen_pattern, freeze_pattern
        brief['editing_pattern'] = frozen_pattern(freeze_pattern({**cfg, **supplied}, refresh='editing_pattern' in supplied))
    if 'asset_policy' in cfg or 'asset_policy' in supplied:
        from .patterns import resolve_asset_policy
        brief['asset_policy'] = resolve_asset_policy({**cfg, **supplied})
    return brief


def pack_transcript(transcript, brief):
    """Offer exact anchors and timing for an editorial reader, without invented chapters."""
    _transcript(transcript)
    words = transcript['words']
    return {'version': 1, 'source': copy.deepcopy(transcript['source']),
            'duration': transcript['duration'], 'brief': copy.deepcopy(brief),
            'words': [{'id': w['id'], 'start': w['start'], 'end': w['end'], 'text': w['text']}
                      for w in words],
            'phrases': [{'id': s['id'], 'start': s['start'], 'end': s['end'],
                         'text': s['text'],
                         'word_ids': [w['id'] for w in words if s['start'] <= w['start'] and w['end'] <= s['end']]}
                        for s in transcript['segments']],
            'chapter_candidates': []}


def _span(words, item, duration):
    by_id = {w['id']: index for index, w in enumerate(words)}
    try:
        first, last = by_id[item['start_word_id']], by_id[item['end_word_id']]
    except (KeyError, TypeError):
        raise ValueError('Unknown span word anchor') from None
    if first > last:
        raise ValueError('Reversed span word anchors')
    before, after = item.get('pad_before', .08), item.get('pad_after', .08)
    for value in (before, after):
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 <= value < float('inf'):
            raise ValueError('Invalid span padding')
    start = max(0., words[first]['start'] - before)
    end = min(duration, words[last]['end'] + after)
    # Padding must never select an adjacent word accidentally.
    if first:
        start = max(start, words[first - 1]['end'])
    if last + 1 < len(words):
        end = min(end, words[last + 1]['start'])
    return start, end


def build_story_plan(cfg, transcript, brief, spec):
    duration = _transcript(transcript)
    source = fingerprint(cfg['source'])
    if source != transcript['source']:
        raise ValueError('Transcript source changed')
    if not isinstance(spec, dict) or not isinstance(spec.get('chapters'), list):
        raise ValueError('Story requires chapters')
    sequence = []
    for chapter in spec['chapters']:
        chapter_id = chapter['id']
        for span in chapter['spans']:
            start, end = _span(transcript['words'], span, duration)
            sequence.append({'id': span['id'], 'start': start, 'end': end,
                             'chapter_id': chapter_id, 'reason': span['reason'],
                             'goal_ids': copy.deepcopy(span.get('goal_ids', chapter.get('goal_ids', []))),
                             'fade_in_seconds': span.get('fade_in_seconds', 0),
                             'fade_out_seconds': span.get('fade_out_seconds', 0),
                             'start_word_id': span['start_word_id'], 'end_word_id': span['end_word_id']})
    plan = {'version': 3, 'source': source, 'duration': duration,
            'transcript_sha256': _digest(transcript), 'transcript': copy.deepcopy(transcript),
            'editing_settings': _settings(cfg), 'protected_ranges': copy.deepcopy(cfg.get('editorial', {}).get('protected_ranges', [])),
            'cuts': [], 'acoustic_intervals': None, 'brief': copy.deepcopy(brief),
            'chapters': copy.deepcopy(spec['chapters']), 'sequence': sequence,
            'omissions': copy.deepcopy(spec.get('omissions', [])),
            'omitted_word_ids': [], 'status': 'review_required', 'review': None,
            'warnings': []}
    retained = {w['id'] for w in transcript['words'] if any(s['start'] <= w['start'] and w['end'] <= s['end'] for s in sequence)}
    plan['omitted_word_ids'] = [w['id'] for w in transcript['words'] if w['id'] not in retained]
    validate_plan(plan)
    return plan


def approve_story(plan, actor, note):
    if not str(actor).strip() or not str(note).strip():
        raise ValueError('Review requires actor and note')
    result = copy.deepcopy(plan)
    validate_plan(result)
    if result['version'] != 3:
        raise ValueError('Story approval requires version 3')
    result['status'] = 'reviewed_selection'
    result['review'] = {'actor': actor, 'note': note}
    validate_plan(result)
    return result


def revise_story(plan, operations, actor, note):
    """Apply explicit span operations; all revisions return to review_required.

    remove: {op,id,reason,goal_ids}; restore/add: {op,span,chapter_id};
    retime: {op,id,start_word_id,end_word_id,reason,goal_ids,...padding/fades};
    reorder: {op,ids:[all sequence ids in desired order],reason,goal_ids}.
    Every omission resulting from removal needs an explicit omission evidence row.
    """
    if not str(actor).strip() or not str(note).strip() or not isinstance(operations, list) or not operations:
        raise ValueError('Revision requires operations, actor and note')
    validate_plan(plan)
    if plan['version'] != 3:
        raise ValueError('Story revision requires version 3')
    result = copy.deepcopy(plan)
    words = result['transcript']['words']
    for operation in operations:
        kind = operation['op']
        if kind == 'remove':
            match = next((s for s in result['sequence'] if s['id'] == operation['id']), None)
            if match is None:
                raise ValueError('Unknown sequence id')
            result['sequence'].remove(match)
            result.setdefault('removed_spans', []).append(match)
            ids = [w['id'] for w in words if match['start'] <= w['start'] and w['end'] <= match['end']]
            result['omissions'].append({'word_ids': ids, 'reason': operation['reason'], 'goal_ids': operation['goal_ids']})
        elif kind in ('restore', 'add'):
            span = operation.get('span')
            if kind == 'restore' and span is None:
                span = next((s for s in result.get('removed_spans', []) if s['id'] == operation['id']), None)
            if span is None:
                raise ValueError('Missing span')
            if 'start_word_id' in span:
                start, end = _span(words, span, result['duration'])
                span = {**span, 'start': start, 'end': end}
            span = {**span, 'chapter_id': operation.get('chapter_id', span.get('chapter_id')),
                    'fade_in_seconds': span.get('fade_in_seconds', 0), 'fade_out_seconds': span.get('fade_out_seconds', 0)}
            result['sequence'].insert(operation.get('index', len(result['sequence'])), copy.deepcopy(span))
            restored = {w['id'] for w in words if span['start'] <= w['start'] and w['end'] <= span['end']}
            result['omissions'] = [{**o, 'word_ids': [i for i in o['word_ids'] if i not in restored]} for o in result['omissions']]
            result['omissions'] = [o for o in result['omissions'] if o['word_ids']]
        elif kind == 'retime':
            match = next((s for s in result['sequence'] if s['id'] == operation['id']), None)
            if match is None:
                raise ValueError('Unknown sequence id')
            match.update({key: operation[key] for key in ('start_word_id', 'end_word_id', 'reason', 'goal_ids', 'pad_before', 'pad_after', 'fade_in_seconds', 'fade_out_seconds') if key in operation})
            match['start'], match['end'] = _span(words, match, result['duration'])
        elif kind == 'reorder':
            ids = operation['ids']
            if len(ids) != len(result['sequence']) or set(ids) != {s['id'] for s in result['sequence']}:
                raise ValueError('Reorder must list every sequence id exactly once')
            result['sequence'] = [next(s for s in result['sequence'] if s['id'] == item) for item in ids]
        else:
            raise ValueError('Unknown story operation')
        if not str(operation.get('reason', '')).strip() or not operation.get('goal_ids'):
            raise ValueError('Story operation requires reason and goal ids')
    retained = {w['id'] for w in words if any(s['start'] <= w['start'] and w['end'] <= s['end'] for s in result['sequence'])}
    result['omitted_word_ids'] = [w['id'] for w in words if w['id'] not in retained]
    omitted = set(result['omitted_word_ids'])
    result['omissions'] = [{**o, 'word_ids': [i for i in o['word_ids'] if i in omitted]}
                           for o in result['omissions']]
    result['omissions'] = [o for o in result['omissions'] if o['word_ids']]
    evidenced = {i for o in result['omissions'] for i in o['word_ids']}
    missing = [i for i in result['omitted_word_ids'] if i not in evidenced]
    if missing:
        last = operations[-1]
        result['omissions'].append({'word_ids': missing, 'reason': last['reason'],
                                    'goal_ids': copy.deepcopy(last['goal_ids'])})
    result['status'] = 'review_required'
    result['review'] = None
    result.setdefault('revisions', []).append({'actor': actor, 'note': note, 'operations': copy.deepcopy(operations), 'parent_sha256': _digest(plan)})
    validate_plan(result)
    return result


def revise_pause_plan(plan, operations, actor, note):
    """Revise v2 cut decisions with exact speech word evidence.

    enable/disable: {op,id,reason}; retime: {op,id,start,end,reason};
    add_speech: {op,start,end,removed_word_ids,reason}.
    Disabling a speech cut removes it because v2 permits only enabled speech cuts.
    """
    if not str(actor).strip() or not str(note).strip() or not isinstance(operations, list) or not operations:
        raise ValueError('Cut revision requires operations, actor and note')
    validate_plan(plan)
    if plan['version'] != 2:
        raise ValueError('Pause revision requires version 2')
    result = copy.deepcopy(plan)
    for operation in operations:
        kind = operation['op']
        reason = operation.get('reason')
        if not isinstance(reason, str) or not reason.strip():
            raise ValueError('Cut operation requires reason')
        if kind == 'add_speech':
            identifiers = [c['id'] for c in result['cuts']]
            result['cuts'].append({'id': max(identifiers, default=0) + 1,
                                   'start': operation['start'], 'end': operation['end'],
                                   'kind': 'speech', 'enabled': True,
                                   'removed_word_ids': copy.deepcopy(operation['removed_word_ids']),
                                   'review_note': reason})
            continue
        cut = next((c for c in result['cuts'] if c['id'] == operation['id']), None)
        if cut is None:
            raise ValueError('Unknown cut id')
        if kind == 'enable':
            cut['enabled'] = True
            cut['review_note'] = reason
        elif kind == 'disable':
            if cut['kind'] == 'speech':
                result['cuts'].remove(cut)
            else:
                cut['enabled'] = False
                cut['review_note'] = reason
        elif kind == 'retime':
            cut['start'], cut['end'] = operation['start'], operation['end']
            cut['review_note'] = reason
        else:
            raise ValueError('Unknown cut operation')
    result.setdefault('revisions', []).append({'actor': actor, 'note': note,
                                                'operations': copy.deepcopy(operations),
                                                'parent_sha256': _digest(plan)})
    validate_plan(result)
    return result
