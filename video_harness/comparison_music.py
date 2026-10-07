"""Bounded BGM corrections from an exact render; source/SFX settings stay intact."""
from copy import deepcopy
import math
from pathlib import Path
from fractions import Fraction

from .common import fingerprint, read, probe
from .render_cache import digest


def music_controls(cfg, production, render):
    if any('phase_map' in cue or 'audio_retime' in cue for cue in production.get('cues', [])):
        return []
    if any('content_map' in event for event in (cfg.get('video_effects') or {}).get('events', [])):
        return []
    gain_allowed = cfg.get('audio', {}).get('normalize') is False
    # With music alone, final normalization cancels a scalar gain adjustment.
    # Use only the report sealed in the exact render, never an unbound side file.
    result = read(render['files']['result']['path'])
    for name in ('mix-evidence.json', 'production-mix.json'):
        expected = result.get('artifacts', {}).get(name)
        if expected is None:
            continue
        path = Path(render['path']) / name
        if fingerprint(path)['sha256'] != expected:
            raise ValueError('Comparison music mix evidence changed')
        rms = read(path).get('speech_rms')
        if type(rms) in (int, float) and math.isfinite(rms) and rms > 0:
            gain_allowed = True
    choices = replacement_choices(cfg) if (any('source_start' in cue for cue in production.get('cues', []))
                                             and not any('beat_anchor' in cue for cue in production.get('cues', []))) else []
    return [{'source_start': cue.get('source_start', '0'), 'replacement_choices': choices,
             'id': cue['id'], 'asset_id': cue['asset_id'], 'gain_db': float(cue['gain_db']),
             'adjustable_gain': gain_allowed and -60 <= float(cue['gain_db']) <= 12,
             'minimum_gain_db': -60, 'maximum_gain_db': 12}
            for cue in production.get('cues', []) if cue['role'] == 'music']


def replacement_choices(cfg):
    from .assets import validate_asset
    from .patterns import resolve_asset_policy
    policy = resolve_asset_policy(cfg)
    choices = []
    for asset in cfg.get('assets', []):
        if asset.get('kind') != 'music':
            continue
        try:
            validate_asset(asset, policy)
        except ValueError:
            continue
        choices.append({'asset_id': asset['asset_id'], 'asset_sha256': asset['sha256'],
                        'label': asset.get('title') or asset['asset_id']})
    return choices


def revise_music(cfg, mapping, production, render, operations, *, allow_replace=False):
    controls = {row['id']: row for row in music_controls(cfg, production, render)}
    if (not isinstance(operations, list) or not operations
            or production.get('mapping_sha256') != digest(mapping)):
        raise ValueError('Comparison BGM corrections need the sealed output timeline')
    cues = deepcopy(production['cues'])
    by_id = {cue['id']: cue for cue in cues}
    removed, seen = set(), set()
    for op in operations:
        if not isinstance(op, dict) or not isinstance(op.get('id'), str):
            raise ValueError('Invalid comparison BGM operation')
        identifier = op['id']
        if identifier not in controls or identifier in seen:
            raise ValueError('Comparison BGM needs a unique existing music cue')
        seen.add(identifier)
        if op.get('action') == 'remove' and set(op) == {'id', 'action'}:
            removed.add(identifier)
        elif op.get('action') == 'gain' and set(op) == {'id', 'action', 'gain_db'}:
            gain = op['gain_db']
            if (not controls[identifier]['adjustable_gain'] or type(gain) not in (int, float)
                    or not math.isfinite(gain) or not -60 <= gain <= 12):
                raise ValueError('BGM gain requires supported source audio and finite -60..12 dB')
            by_id[identifier]['gain_db'] = gain
        elif (allow_replace and op.get('action') == 'replace' and set(op) ==
              {'action', 'id', 'asset_id', 'asset_sha256', 'source_start', 'gain_db'}):
            if any('beat_anchor' in cue for cue in cues):
                raise ValueError('Replacement requires rebuilding existing beat-anchored cues')
            choice = next((a for a in controls[identifier]['replacement_choices']
                           if a['asset_id'] == op['asset_id'] and a['asset_sha256'] == op['asset_sha256']), None)
            if choice is None:
                raise ValueError('Replacement must use a current authorized registered music SHA')
            if not isinstance(op['source_start'], str):
                raise ValueError('Replacement source start must be an exact rational string')
            try:
                start = Fraction(op['source_start'])
            except (ValueError, ZeroDivisionError):
                raise ValueError('Invalid replacement source start') from None
            cue = by_id[identifier]
            end = start + Fraction(str(cue['source_end'])) - Fraction(str(cue['source_start']))
            gain = op['gain_db']
            if (type(gain) not in (int, float) or not math.isfinite(gain) or not -60 <= gain <= 12
                    or (gain != cue['gain_db'] and not controls[identifier]['adjustable_gain'])):
                raise ValueError('Invalid or unsupported replacement gain')
            asset = next(a for a in cfg['assets'] if a['asset_id'] == op['asset_id'])
            duration = Fraction(str(probe(asset['path'])['format']['duration']))
            if start < 0 or end > duration:
                raise ValueError('Replacement music is too short for the retained source trim')
            cue.update(asset_id=op['asset_id'], source_start=str(start), source_end=str(end), gain_db=gain)
        else:
            raise ValueError('Comparison BGM supports only gain/off or version-5 registered replacement')
    return {'version': 1, 'mapping_sha256': digest(mapping),
            'cues': [cue for cue in cues if cue['id'] not in removed]}
