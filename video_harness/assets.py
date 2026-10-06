"""Local asset registration and fail-closed use-rights decisions."""
from __future__ import annotations

from copy import deepcopy
from datetime import date
from pathlib import Path
import math
import re
import json
import subprocess

from PIL import Image

from .common import fingerprint
from .patterns import resolve_asset_policy
from .render_cache import digest

KINDS = {'music', 'sfx', 'video', 'image'}
OPERATIONS = {'embedded_use', 'mixed_audio_handoff', 'raw_asset_handoff'}
MAX_ASSET_BYTES = 2 * 1024 * 1024 * 1024
_META = {'asset_id', 'kind', 'creator', 'source_url', 'acquired_on', 'license_url',
         'verified_on', 'evidence_path', 'credit', 'rights', 'cost', 'currency',
         'content_id', 'certificate_path', 'tags', 'title', 'description',
         'owned_by_user', 'ownership_evidence_path', 'characteristics'}
_RIGHTS = {'status', 'commercial', 'advertising', 'modification', 'destinations',
           'regions', 'attribution_required', *OPERATIONS}
_CHARACTERISTICS = {'scene', 'emotion', 'energy', 'energy_curve', 'vocals',
                    'density', 'beat_stability', 'framing'}
_CONTEXT = _CHARACTERISTICS | {'duration', 'dialogue_present'}
_LEVELS = {'low', 'medium', 'high'}


def _check_characteristics(value):
    if not isinstance(value, dict) or set(value) - _CHARACTERISTICS:
        raise ValueError('Invalid asset characteristics')
    for field, item in value.items():
        if not isinstance(item, dict) or set(item) != {'value', 'evidence'} or not isinstance(item['evidence'], str) or not item['evidence'].strip():
            raise ValueError(f'{field} needs explicit evidence')
        observed = item['value']
        if field in {'energy', 'density'} and observed not in _LEVELS:
            raise ValueError(f'Invalid {field}')
        if field == 'energy_curve' and (not isinstance(observed, list) or not observed or any(x not in _LEVELS for x in observed)):
            raise ValueError('Invalid energy_curve')
        if field == 'vocals' and observed not in {'none', 'present'}:
            raise ValueError('Invalid vocals')
        if field == 'beat_stability' and observed not in {'stable', 'variable'}:
            raise ValueError('Invalid beat_stability')
        if field in {'scene', 'emotion', 'framing'} and (not isinstance(observed, str) or not observed.strip()):
            raise ValueError(f'Invalid {field}')


def _check_request(request, limit):
    fields = {'kind', 'tags', 'operation'} | _CONTEXT
    if type(limit) is not int or not 1 <= limit <= 3 or not isinstance(request, dict) or set(request) - fields:
        raise ValueError('Invalid asset selection request')
    if request.get('kind') not in KINDS or not isinstance(request.get('tags', []), list) or any(not isinstance(x, str) for x in request.get('tags', [])):
        raise ValueError('Asset selection needs kind and optional string tags')
    if request.get('operation', 'embedded_use') not in OPERATIONS:
        raise ValueError('Invalid asset operation')
    if 'dialogue_present' in request and type(request['dialogue_present']) is not bool:
        raise ValueError('dialogue_present must be boolean')
    if 'duration' in request and (type(request['duration']) not in {int, float} or not math.isfinite(request['duration']) or request['duration'] <= 0):
        raise ValueError('duration must be positive seconds')
    _check_characteristics({k: {'value': v, 'evidence': 'request'} for k, v in request.items() if k in _CHARACTERISTICS})


def _media_kind(path: Path) -> str:
    with path.open('rb') as stream:
        head = stream.read(32)
    suffix = path.suffix.lower()
    if suffix == '.wav' and head.startswith(b'RIFF') and head[8:12] == b'WAVE':
        return 'music'
    if suffix == '.mp3' and (head.startswith(b'ID3') or (len(head) > 1 and head[0] == 255 and head[1] & 224 == 224)):
        return 'music'
    if suffix == '.flac' and head.startswith(b'fLaC'):
        return 'music'
    if suffix == '.ogg' and head.startswith(b'OggS'):
        return 'music'
    if suffix in {'.aif', '.aiff'} and head.startswith(b'FORM') and head[8:12] in {b'AIFF', b'AIFC'}:
        return 'music'
    if suffix in {'.m4a', '.mp4', '.mov'} and head[4:8] == b'ftyp':
        return 'video' if suffix in {'.mp4', '.mov'} else 'music'
    if suffix == '.png' and head.startswith(b'\x89PNG\r\n\x1a\n'):
        return 'image'
    if suffix in {'.jpg', '.jpeg'} and head.startswith(b'\xff\xd8\xff'):
        return 'image'
    raise ValueError('Unsupported or misidentified media file')


def _verify_media(path: Path, kind: str) -> None:
    if kind == 'image':
        try:
            with Image.open(path) as image:
                image.verify()
            with Image.open(path) as image:
                if not 0 < image.width * image.height <= 100_000_000:
                    raise ValueError('Invalid image dimensions')
        except (OSError, SyntaxError) as exc:
            raise ValueError('Image decode failed') from exc
        return
    try:
        result = subprocess.run(['ffprobe', '-v', 'error', '-show_streams', '-show_format',
                                 '-of', 'json', str(path)], capture_output=True, text=True,
                                timeout=30, check=True)
        info = json.loads(result.stdout)
    except (OSError, subprocess.SubprocessError, ValueError) as exc:
        raise ValueError('Media probe failed') from exc
    streams = info.get('streams', [])
    if kind in {'music', 'sfx'} and not any(s.get('codec_type') == 'audio' for s in streams):
        raise ValueError('Audio stream missing')
    if kind == 'video' and not any(s.get('codec_type') == 'video' for s in streams):
        raise ValueError('Video stream missing')
    try:
        duration = float(info['format']['duration'])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError('Media duration missing') from exc
    if not math.isfinite(duration) or duration <= 0:
        raise ValueError('Invalid media duration')


def _day(value, label):
    if not isinstance(value, str):
        raise ValueError(f'{label} must be an ISO date')
    try:
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f'{label} must be an ISO date') from exc
    if parsed > date.today():
        raise ValueError(f'{label} is in the future')


def _url(value, label):
    if not isinstance(value, str) or not re.fullmatch(r'https://[^\s/@]+(?:/[^\s]*)?', value):
        raise ValueError(f'{label} must be an HTTPS URL')


def _validate_rights(rights):
    if not isinstance(rights, dict) or set(rights) != _RIGHTS:
        raise ValueError('Rights must declare every supported gate exactly')
    if rights['status'] not in {'verified', 'unknown', 'denied'}:
        raise ValueError('Invalid rights status')
    for field in ('commercial', 'advertising', 'modification', 'attribution_required', *OPERATIONS):
        if type(rights[field]) is not bool:
            raise ValueError(f'Rights {field} must be explicit boolean')
    for field in ('destinations', 'regions'):
        if not isinstance(rights[field], list) or any(not isinstance(x, str) or not x for x in rights[field]) or len(set(rights[field])) != len(rights[field]):
            raise ValueError(f'Invalid rights {field}')


def register_asset(path, metadata: dict) -> dict:
    """Capture immutable evidence pointers; never copy or download media."""
    original_path = Path(path).expanduser()
    if original_path.is_symlink():
        raise ValueError('Asset symlink is not allowed')
    path = original_path.resolve(strict=True)
    if not path.is_file() or not 0 < path.stat().st_size <= MAX_ASSET_BYTES:
        raise ValueError('Asset must be a bounded regular local file')
    if not isinstance(metadata, dict) or set(metadata) - _META:
        raise ValueError('Unknown asset metadata field')
    required = {'asset_id', 'kind', 'creator', 'source_url', 'acquired_on', 'license_url', 'verified_on', 'credit', 'rights', 'cost', 'currency', 'content_id'}
    if required - set(metadata):
        raise ValueError('Asset metadata is incomplete')
    if not isinstance(metadata['asset_id'], str) or not re.fullmatch(r'[a-zA-Z][a-zA-Z0-9_-]{0,63}', metadata['asset_id']):
        raise ValueError('Invalid asset_id')
    kind = _media_kind(path)
    if metadata['kind'] not in KINDS or (metadata['kind'] != kind and not (kind == 'music' and metadata['kind'] == 'sfx')):
        raise ValueError('Asset kind conflicts with file type')
    _verify_media(path, metadata['kind'])
    for field in ('creator', 'credit'):
        if not isinstance(metadata[field], str) or not metadata[field].strip():
            raise ValueError(f'Asset {field} is required')
    for field in ('source_url', 'license_url'):
        _url(metadata[field], field)
    for field in ('acquired_on', 'verified_on'):
        _day(metadata[field], field)
    if type(metadata['cost']) not in (int, float) or not math.isfinite(metadata['cost']) or metadata['cost'] < 0:
        raise ValueError('Invalid asset cost')
    if not isinstance(metadata['currency'], str) or not re.fullmatch(r'[A-Z]{3}', metadata['currency']):
        raise ValueError('Invalid asset currency')
    if metadata['content_id'] not in {'none', 'registered', 'unknown'}:
        raise ValueError('Invalid Content ID state')
    if 'tags' in metadata and (not isinstance(metadata['tags'], list) or any(not isinstance(t, str) for t in metadata['tags'])):
        raise ValueError('Invalid asset tags')
    if 'characteristics' in metadata:
        _check_characteristics(metadata['characteristics'])
    owned = metadata.get('owned_by_user', False)
    if type(owned) is not bool or (owned and not metadata.get('ownership_evidence_path')):
        raise ValueError('User ownership requires explicit boolean and evidence path')
    _validate_rights(metadata['rights'])
    if metadata['rights']['status'] == 'verified' and not metadata.get('evidence_path'):
        raise ValueError('Verified rights require a saved evidence file')
    evidence = {}
    for key in ('evidence_path', 'certificate_path', 'ownership_evidence_path'):
        if metadata.get(key) is not None:
            evidence_file = Path(metadata[key]).expanduser().resolve(strict=True)
            if not evidence_file.is_file():
                raise ValueError(f'{key} must refer to a file')
            evidence[key] = fingerprint(evidence_file)
    record = {'schema_version': 1, 'owned_by_user': owned, **deepcopy(metadata), 'path': str(path),
              'sha256': fingerprint(path)['sha256'], 'bytes': path.stat().st_size,
              'evidence': evidence}
    record['record_sha256'] = digest(record)
    return record


def validate_asset(record: dict, policy: dict, operation: str = 'embedded_use') -> dict:
    """Check bytes and rights; pending Content ID permits local embedded review only."""
    if operation not in OPERATIONS or not isinstance(record, dict) or record.get('schema_version') != 1:
        raise ValueError('Invalid asset record or operation')
    policy = resolve_asset_policy({'asset_policy': policy})
    if record.get('record_sha256') != digest({k: v for k, v in record.items() if k != 'record_sha256'}):
        raise ValueError('Asset record changed')
    path = Path(record['path'])
    if not path.is_file() or fingerprint(path)['sha256'] != record.get('sha256') or path.stat().st_size != record.get('bytes'):
        raise ValueError('Asset bytes changed')
    for ref in record.get('evidence', {}).values():
        if fingerprint(ref['path']) != ref:
            raise ValueError('Asset rights evidence changed')
    _validate_rights(record.get('rights'))
    rights = record['rights']
    if rights['status'] != 'verified' or not rights[operation]:
        raise ValueError(f'Asset {operation} right is not verified')
    if record['kind'] in {'music', 'sfx'} and operation != 'raw_asset_handoff' and not rights['modification']:
        raise ValueError('Audio mixing or cue trimming requires modification rights')
    if not policy['destinations'] or not set(policy['destinations']) <= set(rights['destinations']):
        raise ValueError('Asset destination rights do not cover requested outlets')
    if policy['usage'] != 'personal' and not rights['commercial']:
        raise ValueError('Commercial use is not permitted')
    if policy['advertising'] and not rights['advertising']:
        raise ValueError('Advertising use is not permitted')
    if policy['region'] and rights['regions'] and policy['region'] not in rights['regions']:
        raise ValueError('Region is not permitted')
    if rights['attribution_required'] and (policy['attribution'] != 'allowed' or not record.get('credit')):
        raise ValueError('Required attribution cannot be fulfilled')
    if record.get('currency') != policy['currency'] or record.get('cost', float('inf')) > policy['budget']:
        raise ValueError('Asset exceeds budget or uses another currency')
    if record.get('content_id') == 'unknown' and not (
            policy['content_id_check'] == 'pending_local_review' and operation == 'embedded_use'):
        raise ValueError('Content ID state is unknown')
    if record.get('content_id') == 'registered' and not record.get('certificate_path'):
        raise ValueError('Content ID evidence is missing')
    return deepcopy(record)


def _duration(path):
    try:
        raw = subprocess.check_output(['ffprobe', '-v', 'error', '-show_entries',
                                       'format=duration', '-of', 'json', str(path)], timeout=30)
        value = float(json.loads(raw)['format']['duration'])
        return value if math.isfinite(value) and value > 0 else None
    except (OSError, subprocess.SubprocessError, KeyError, TypeError, ValueError):
        return None


def score_asset(record, request):
    """Score declared observations only. The caller must establish eligibility first."""
    wanted = set(request.get('tags', []))
    overlap = sorted(wanted & set(record.get('tags', [])))
    score = len(overlap)
    reasons = [f"matched tags: {', '.join(overlap) if overlap else 'none'}"]
    unknown = []
    observed = record.get('characteristics', {})
    for field in sorted(_CHARACTERISTICS & set(request)):
        item = observed.get(field)
        if item is None:
            unknown.append(field)
            continue
        target, actual = request[field], item['value']
        if target == actual:
            score += 3
            reasons.append(f'{field} matches ({item["evidence"]})')
        else:
            reasons.append(f'{field} differs: requested {target}, observed {actual}')
    if request.get('dialogue_present'):
        vocals = observed.get('vocals')
        density = observed.get('density')
        if vocals and vocals['value'] == 'none':
            score += 3
            reasons.append('instrumental music fits spoken dialogue')
        elif vocals and vocals['value'] == 'present':
            score -= 4
            reasons.append('vocals may compete with spoken dialogue')
        else:
            unknown.append('vocals')
        if density and density['value'] == 'low':
            score += 2
            reasons.append('low density fits spoken dialogue')
        elif density and density['value'] == 'high':
            score -= 2
            reasons.append('high density may compete with spoken dialogue')
        elif density is None:
            unknown.append('density')
    if 'duration' in request:
        length = _duration(record['path']) if record.get('kind') != 'image' else None
        if length is None:
            unknown.append('duration')
        elif length >= request['duration']:
            score += 3
            reasons.append(f'duration fits without loop ({length:g}s)')
        else:
            score -= 2
            reasons.append(f'duration requires loop or trim ({length:g}s)')
    return {'score': score, 'reasons': reasons, 'unknown': sorted(set(unknown)),
            'inferred': False}


def rank_assets(records, request: dict, policy: dict, limit: int = 3) -> dict:
    """Rights-first, explainable ranking with a persistent no-addition choice."""
    _check_request(request, limit)
    ranked, excluded = [], []
    for record in records:
        asset_id = record.get('asset_id', '<unknown>')
        if record.get('kind') != request['kind']:
            excluded.append({'asset_id': asset_id, 'reason': 'kind mismatch'})
            continue
        try:
            valid = validate_asset(record, policy, request.get('operation', 'embedded_use'))
        except (ValueError, KeyError, OSError) as exc:
            excluded.append({'asset_id': asset_id, 'reason': str(exc)})
            continue
        fit = score_asset(valid, request)
        valid['selection_reason'] = 'Eligible rights; ' + '; '.join(fit['reasons'])
        ranked.append({'asset': valid, 'asset_id': asset_id, 'sha256': valid['sha256'],
                       'verified_on': valid.get('verified_on'), 'score': fit['score'],
                       'reasons': fit['reasons'], 'unknown': fit['unknown'],
                       'inferred': fit['inferred']})
    ranked.sort(key=lambda item: (-item['score'], item['asset_id']))
    for item in ranked[limit:]:
        excluded.append({'asset_id': item['asset_id'], 'reason': 'outside comparison limit'})
    return {'request': deepcopy(request), 'candidates': ranked[:limit], 'excluded': excluded,
            'no_addition': {'asset_id': None, 'reason': 'Keep original picture and sound'}}


def select_assets(records, request: dict, policy: dict, limit: int = 3) -> list[dict]:
    """Compatibility list API for the rights-first ranking report."""
    return [item['asset'] for item in rank_assets(records, request, policy, limit)['candidates']]
