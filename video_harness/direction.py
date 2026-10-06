"""Pure, reviewable resolution of structured editorial direction."""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path

from .patterns import _FIELDS, _VALUES, resolve_pattern, reuse_preference
from .production import frozen_pattern
from .trends import scope_trend_profile

_REQUEST_FIELDS = {'editing_pattern', 'trend_requested', 'platform', 'purpose'}


def _setting(value, label):
    if not isinstance(value, dict) or set(value) - _FIELDS:
        raise ValueError(f'Invalid {label} fields')
    if 'schema_version' in value and (type(value['schema_version']) is not int or value['schema_version'] != 1):
        raise ValueError(f'Invalid {label} schema_version')
    for key, allowed in _VALUES.items():
        if key in value and (not isinstance(value[key], str) or value[key] not in allowed):
            raise ValueError(f'Invalid {label} {key}')
    if 'id' in value:
        if value['id'] not in {'natural', 'gentle_vlog', 'clear_explainer', 'cinematic_story', 'beat_montage', 'playful_short'}:
            raise ValueError(f'Invalid {label} id')
        if value['id'] == 'natural' and any(value.get(k, 'off') != 'off' for k in ('music', 'sfx', 'visual_assets', 'beat_sync')):
            raise ValueError(f'Invalid {label}: natural cannot add effects')
    return deepcopy(value)


def _saved_preference(value):
    if value is None:
        return None
    if not isinstance(value, (str, Path)):
        raise ValueError('preference must be an explicitly saved preference path')
    return reuse_preference(value)


def resolve_direction(project: dict, *, request: dict | None = None,
                      preference: str | Path | None = None,
                      trend: dict | None = None, as_of: str | None = None) -> dict:
    """Resolve request > project > saved preference > pattern > natural.

    Inputs are structured by the calling skill/UI; this function does not infer
    creative intent from free text. Its project changes remain a proposal.
    """
    if not isinstance(project, dict):
        raise ValueError('project must be an object')
    request = {} if request is None else request
    if not isinstance(request, dict) or set(request) - _REQUEST_FIELDS:
        raise ValueError('Unknown direction request fields')
    explicit = _setting(request.get('editing_pattern', {}), 'request editing_pattern')
    configured = _setting(project.get('editing_pattern', {}), 'project editing_pattern')
    saved = _saved_preference(preference)
    selected_id = explicit.get('id', configured.get('id', saved['id'] if saved else 'natural'))

    # A newly selected pattern clears effect overrides belonging to a different
    # pattern. This also makes an explicit natural reset reliable.
    use_request = explicit if explicit.get('id', selected_id) == selected_id else {}
    use_project = configured if configured.get('id', selected_id) == selected_id else {}
    use_saved = saved if saved and saved['id'] == selected_id else None
    if explicit.get('id') and explicit['id'] != configured.get('id'):
        use_project = {}
    if configured.get('id') and configured['id'] != (saved['id'] if saved else configured['id']):
        use_saved = None

    # Reuse the old immutable definition when a saved preference supplies the
    # base. Likewise preserve an existing session snapshot when its ID matches.
    existing = frozen_pattern(project) if project.get('_editing_pattern_snapshot') else None
    if existing and existing['id'] == selected_id and not explicit.get('id'):
        base = existing
        base_source = 'project_snapshot'
    elif use_saved:
        base = deepcopy(use_saved)
        base_source = 'saved_preference'
    else:
        base = resolve_pattern({'editing_pattern': {'id': selected_id}})
        base_source = 'pattern_default'

    merged = {key: base[key] for key in _VALUES}
    provenance = {'id': ('current_request' if 'id' in use_request else
                         'project_setting' if 'id' in use_project else
                         'saved_preference' if use_saved else 'global_natural')}
    for key in _VALUES:
        for source, layer in (('current_request', use_request),
                              ('project_setting', use_project),
                              ('saved_preference', use_saved or {})):
            if key in layer:
                merged[key] = deepcopy(layer[key])
                provenance[key] = source
                break
        else:
            provenance[key] = base_source
    setting = {'schema_version': 1, 'id': selected_id, **merged}
    snapshot = {**deepcopy(base), **merged}
    # Validate all combinations without looking up an old definition.
    frozen_pattern({'editing_pattern': setting, '_editing_pattern_snapshot': snapshot})
    changes = {'editing_pattern': setting, '_editing_pattern_snapshot': snapshot}

    wants_trend = request.get('trend_requested', False)
    if type(wants_trend) is not bool:
        raise ValueError('trend_requested must be boolean')
    if trend is not None and not wants_trend:
        raise ValueError('Trend profile supplied without an explicit trend request')
    trend_snapshot = None
    candidates = []
    if wants_trend:
        if trend is None or not isinstance(request.get('platform'), str) or not isinstance(request.get('purpose'), str):
            raise ValueError('Explicit trend direction needs a profile, platform, and purpose')
        trend_snapshot = scope_trend_profile(trend, platform=request['platform'],
                                             purpose=request['purpose'], as_of=as_of)
        natural = resolve_pattern({'editing_pattern': {'id': 'natural'}})
        moderated = deepcopy(snapshot) if selected_id != 'natural' else resolve_pattern({'editing_pattern': {'id': 'gentle_vlog'}})
        candidates = [
            {'kind': 'natural', 'pattern_snapshot': natural, 'requires_adoption': True},
            {'kind': 'moderated', 'pattern_snapshot': moderated, 'requires_adoption': True},
        ]
    elif 'platform' in request or 'purpose' in request:
        raise ValueError('Platform and purpose only apply to an explicit trend request')
    return {'project_changes': changes, 'pattern_snapshot': snapshot,
            'provenance': provenance, 'trend_snapshot': trend_snapshot,
            'candidates': candidates, 'requires_review': True}
