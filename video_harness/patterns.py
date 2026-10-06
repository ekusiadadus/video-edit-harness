"""Versioned, optional editing direction independent of color presets."""
from __future__ import annotations

from copy import deepcopy
from datetime import date
from pathlib import Path
import json
import re

from .common import CHECKOUT_ROOT, IS_CHECKOUT, PACKAGE_ROOT
from .render_cache import digest

_ROOT = CHECKOUT_ROOT / 'editing_patterns' if IS_CHECKOUT else PACKAGE_ROOT / 'data' / 'editing_patterns'
_FIELDS = {'schema_version', 'id', 'intensity', 'music', 'sfx', 'visual_assets', 'beat_sync', 'selection'}
_VALUES = {
    'intensity': {'off', 'low', 'medium', 'high'},
    'music': {'off', 'intro_outro', 'chapter', 'continuous', 'selected'},
    'sfx': {'off', 'selected', 'accent'},
    'visual_assets': {'off', 'own_only', 'licensed'},
    'beat_sync': {'off', 'visual_only', 'selected'},
    'selection': {'manual', 'auto_preview'},
}
_POLICY_FIELDS = {'budget', 'currency', 'destinations', 'usage', 'attribution', 'network', 'search_network', 'download_network', 'region', 'advertising', 'content_id_check'}
_DESTINATIONS = {'youtube', 'instagram', 'tiktok', 'reels', 'shorts', 'web', 'other'}


def _object(value, label):
    if not isinstance(value, dict):
        raise ValueError(f'{label} must be an object')
    return value


def resolve_pattern(cfg: dict) -> dict:
    """Freeze definition and resolved values; absence means the legacy natural path."""
    setting = _object(_object(cfg, 'project').get('editing_pattern', {}), 'editing_pattern')
    unknown = set(setting) - _FIELDS
    if unknown:
        raise ValueError(f'Unknown editing_pattern fields: {sorted(unknown)}')
    if setting.get('schema_version', 1) != 1 or type(setting.get('schema_version', 1)) is not int:
        raise ValueError('Unsupported editing_pattern schema_version')
    name = setting.get('id', 'natural')
    if not isinstance(name, str) or not re.fullmatch(r'[a-z][a-z0-9_]*', name):
        raise ValueError('Invalid editing pattern id')
    path = _ROOT / f'{name}.json'
    if not path.is_file():
        raise ValueError(f'Unknown editing pattern: {name}')
    definition = json.loads(path.read_text())
    if definition.get('schema_version') != 1 or definition.get('id') != name or set(definition) != {'schema_version', 'id', 'description', 'defaults'}:
        raise ValueError('Invalid editing pattern definition')
    defaults = _object(definition['defaults'], 'pattern defaults')
    if set(defaults) != set(_VALUES):
        raise ValueError('Invalid pattern defaults')
    resolved = {**defaults, **{k: v for k, v in setting.items() if k in _VALUES}}
    for key, allowed in _VALUES.items():
        if resolved[key] not in allowed:
            raise ValueError(f'Invalid editing_pattern {key}')
    if name == 'natural' and any(resolved[k] != 'off' for k in ('music', 'sfx', 'visual_assets', 'beat_sync')):
        raise ValueError('natural pattern cannot add assets or beat sync')
    if resolved['intensity'] == 'off' and any(resolved[k] != 'off' for k in ('music', 'sfx', 'visual_assets', 'beat_sync')):
        raise ValueError('off intensity cannot add effects')
    return {'schema_version': 1, 'id': name, 'definition_sha256': digest(definition),
            'description': definition['description'], **deepcopy(resolved)}


def reset_to_natural(cfg: dict) -> dict:
    """Return a new project setting that clears earlier pattern overrides."""
    result = deepcopy(_object(cfg, 'project'))
    result.pop('_editing_pattern_snapshot', None)
    result['editing_pattern'] = {'schema_version': 1, 'id': 'natural'}
    resolve_pattern(result)
    return result


def resolve_asset_policy(cfg: dict) -> dict:
    """Strict policy for new assets; a missing policy forbids external assets."""
    supplied = _object(_object(cfg, 'project').get('asset_policy', {}), 'asset_policy')
    unknown = set(supplied) - _POLICY_FIELDS
    if unknown:
        raise ValueError(f'Unknown asset_policy fields: {sorted(unknown)}')
    result = {'budget': 0, 'currency': 'JPY', 'destinations': [], 'usage': 'personal',
              'attribution': 'allowed', 'network': 'off', 'search_network': 'off',
              'download_network': 'off', 'region': None, 'advertising': False,
              'content_id_check': 'required'}
    result.update(deepcopy(supplied))
    if type(result['budget']) not in (int, float) or not 0 <= result['budget'] < float('inf'):
        raise ValueError('Invalid asset budget')
    if not isinstance(result['currency'], str) or not re.fullmatch(r'[A-Z]{3}', result['currency']):
        raise ValueError('Invalid currency')
    destinations = result['destinations']
    if not isinstance(destinations, list) or any(not isinstance(item, str) or item not in _DESTINATIONS for item in destinations) or len(set(destinations)) != len(destinations):
        raise ValueError('Asset destinations must be explicit supported values')
    if supplied and not destinations:
        raise ValueError('Asset destinations must be explicit supported values')
    if result['usage'] not in {'personal', 'commercial', 'monetized'} or result['attribution'] not in {'allowed', 'forbidden'} or any(result[key] not in {'off', 'on'} for key in ('network', 'search_network', 'download_network')):
        raise ValueError('Invalid asset policy value')
    if not isinstance(result['content_id_check'], str) or result['content_id_check'] not in {'required', 'pending_local_review'}:
        raise ValueError('Invalid Content ID check policy')
    if type(result['advertising']) is not bool or (result['region'] is not None and (not isinstance(result['region'], str) or not re.fullmatch(r'[A-Z]{2}', result['region']))):
        raise ValueError('Invalid region or advertising')
    return result


def save_preference(path, selection: dict, *, explicit: bool, actor: str, reason: str) -> dict:
    """Persist a user-directed default once; existing preference files stay immutable."""
    if explicit is not True or actor not in {'human', 'codex', 'claude_code', 'automation'} or not isinstance(reason, str) or not reason.strip():
        raise ValueError('Saving a lasting preference requires explicit direction, actual actor and reason')
    resolved = resolve_pattern({'editing_pattern': selection})
    record = {'version': 1, 'saved_on': date.today().isoformat(), 'actor': actor,
              'reason': reason.strip(), 'pattern': resolved}
    with Path(path).open('x', encoding='utf-8') as stream:
        json.dump(record, stream, ensure_ascii=False, indent=2)
    return record


def reuse_preference(path) -> dict:
    """Return stored resolution without silently refreshing its definition."""
    record = json.loads(Path(path).read_text())
    if (set(record) != {'version', 'saved_on', 'actor', 'reason', 'pattern'}
            or type(record['version']) is not int or record['version'] != 1
            or record['actor'] not in {'human', 'codex', 'claude_code', 'automation'}
            or not isinstance(record['reason'], str) or not record['reason'].strip()):
        raise ValueError('Invalid saved preference')
    try:
        date.fromisoformat(record['saved_on'])
        from .production import frozen_pattern
        pattern = _object(record['pattern'], 'saved preference pattern')
        setting = {key: pattern[key] for key in ('schema_version', 'id', *_VALUES)}
        frozen_pattern({'editing_pattern': setting, '_editing_pattern_snapshot': pattern})
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError('Invalid saved preference') from exc
    return deepcopy(pattern)
