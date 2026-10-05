"""Operational acceptance evidence, with declared observation and model identity boundaries."""
from .common import read


def assess(session):
    state = session._load()
    session._verify(state, deep=True)
    brief = read(state['brief']['path'])
    latest = state['renders'][-1] if state['renders'] else None
    current = bool(latest and latest['plan'] == state['plan'] and latest['project'] == state['project'] and (not latest.get('brief') or latest['brief']==state['brief']))
    latest_duration = read(latest['files']['mapping']['path'])['duration'] if latest else None
    rendered_duration = latest_duration if current else None
    render_brief = read(latest['brief']['path']) if latest and latest.get('brief') else read(latest['plan']['path']).get('brief') if latest else None
    target = brief.get('target_duration_seconds')
    return {'session_id': state['id'], 'source': state['source'], 'brief': brief,
            'project': state['project'], 'transcript': state['transcript'],
            'plan': state['plan'], 'latest_render': latest,
            'latest_render_matches_current_inputs': current, 'latest_render_duration_seconds': latest_duration,
            'latest_render_brief': render_brief,
            'target_duration_seconds': target, 'rendered_duration_seconds': rendered_duration,
            'duration_difference_seconds': rendered_duration-target if rendered_duration is not None and target else None,
            'render_attempts': sum(h['event']=='render_started' for h in state['history']),
            'completed_renders': len(state['renders']),
            'render_elapsed_seconds': sum(r.get('elapsed_seconds') or 0 for r in state['renders']),
            'feedback_count': len(state['feedback']),
            'unresolved_feedback': [f['id'] for f in state['feedback'] if f['status']!='resolved'],
            'resumes': [h for h in state['history'] if h['event']=='resumed'],
            'actors': sorted({h['actor'] for h in state['history']}),
            'reviews': state['reviews'], 'deliveries': state['deliveries'],
            'completion': state.get('completion'),
            'synthetic': read(state['project']['path']).get('evidence_kind')=='synthetic',
            'api_cost': None,
            'evidence_limits': ['Actor fields record workflow attribution; they do not prove which model process executed a command.',
                                'No perceptual quality score is inferred from elapsed time or passing software tests.',
                                'API costs require provider billing evidence; unavailable costs are null.']}


def compare(sessions):
    rows = [assess(s) for s in sessions]
    if len(rows)<2:
        raise ValueError('Compare at least two independent sessions')
    source = rows[0]['source']
    brief = rows[0]['brief']
    if any(r['source']!=source or r['brief']!=brief for r in rows):
        raise ValueError('Comparison requires the same source and editing brief')
    return {'version': 1, 'same_source_and_brief': True, 'sessions': rows,
            'comparison_kind': 'operational_evidence_no_automatic_model_or_quality_ranking'}
