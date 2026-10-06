"""Immutable, dated editorial observations; no automatic refresh."""
from __future__ import annotations

from copy import deepcopy
from datetime import date
from pathlib import Path
import json
import re
from urllib.parse import urlparse

from .common import CHECKOUT_ROOT, IS_CHECKOUT, PACKAGE_ROOT
from .render_cache import digest

_ROOT = CHECKOUT_ROOT / 'trend_profiles' if IS_CHECKOUT else PACKAGE_ROOT / 'data' / 'trend_profiles'


_FIELDS = {'version', 'id', 'source_url', 'observed_on', 'region', 'audience',
           'purpose', 'interpretation', 'review_after'}
_PLATFORMS = {'youtube', 'instagram', 'tiktok', 'web'}


def _validate(profile: dict, *, as_of: str | None = None) -> tuple[date, date, date]:
    if not isinstance(profile, dict) or set(profile) not in (_FIELDS, _FIELDS | {'platform'}) or type(profile['version']) is not int or profile['version'] != 1:
        raise ValueError('Invalid trend profile schema')
    if 'platform' in profile and profile['platform'] not in _PLATFORMS:
        raise ValueError('Invalid trend platform')
    if not isinstance(profile['id'], str) or not re.fullmatch(r'[a-z][a-z0-9_]*', profile['id']):
        raise ValueError('Invalid trend profile id')
    for key in ('region', 'audience', 'purpose', 'interpretation'):
        if not isinstance(profile[key], str) or not profile[key].strip():
            raise ValueError(f'Invalid trend {key}')
    if not isinstance(profile['source_url'], str):
        raise ValueError('Invalid trend source URL')
    parsed = urlparse(profile['source_url'])
    if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError('Invalid trend source URL')
    try:
        today = date.fromisoformat(as_of) if as_of else date.today()
        observed = date.fromisoformat(profile['observed_on'])
        review = date.fromisoformat(profile['review_after'])
    except (TypeError, ValueError) as exc:
        raise ValueError('Invalid trend dates') from exc
    if observed > today or review < observed:
        raise ValueError('Invalid trend date order')
    return today, observed, review


def import_trend_profile(folder, profile: dict) -> dict:
    """Save one reviewed observation in an append-only local catalog."""
    today, _, review = _validate(profile)
    root = Path(folder)
    root.mkdir(parents=True, exist_ok=True)
    path = root / f"{profile['id']}.json"
    with path.open('x', encoding='utf-8') as stream:
        json.dump(profile, stream, ensure_ascii=False, indent=2)
    return {**deepcopy(profile), 'definition_sha256': digest(profile),
            'stale': today > review, 'path': str(path.resolve())}


def load_trend_profile(name: str, *, as_of: str | None = None, root=None) -> dict:
    if not isinstance(name, str) or not name.replace('_', '').isalnum() or '/' in name:
        raise ValueError('Invalid trend profile id')
    profile = json.loads(((Path(root) if root is not None else _ROOT) / (name + '.json')).read_text())
    if not isinstance(profile, dict) or profile.get('id') != name:
        raise ValueError('Invalid trend profile')
    today, _, review = _validate(profile, as_of=as_of)
    return {**deepcopy(profile), 'definition_sha256': digest(profile), 'stale': today > review}


def scope_trend_profile(profile: dict, *, platform: str, purpose: str,
                        as_of: str | None = None) -> dict:
    """Validate a declared trend scope; historical observations cannot silently direct an edit."""
    if not isinstance(profile, dict):
        raise ValueError('Invalid trend profile')
    source = {key: value for key, value in profile.items()
              if key not in {'definition_sha256', 'stale', 'path'}}
    today, _, review = _validate(source, as_of=as_of)
    if 'definition_sha256' in profile and profile['definition_sha256'] != digest(source):
        raise ValueError('Trend profile hash mismatch')
    if source.get('platform') != platform or source['purpose'] != purpose:
        raise ValueError('Trend profile platform or purpose does not match this edit')
    if today > review:
        raise ValueError('Trend profile is past its review date')
    return {**deepcopy(source), 'definition_sha256': digest(source), 'stale': False}
