"""Bounded BGM corrections from an exact render; source/SFX settings stay intact."""
from copy import deepcopy
import math
from pathlib import Path

from .common import fingerprint, read
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
    return [{'id': cue['id'], 'asset_id': cue['asset_id'], 'gain_db': float(cue['gain_db']),
             'adjustable_gain': gain_allowed and -60 <= float(cue['gain_db']) <= 12,
             'minimum_gain_db': -60, 'maximum_gain_db': 12}
            for cue in production.get('cues', []) if cue['role'] == 'music']


def revise_music(cfg, mapping, production, render, operations):
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
        else:
            raise ValueError('Comparison BGM supports only gain and off')
    return {'version': 1, 'mapping_sha256': digest(mapping),
            'cues': [cue for cue in cues if cue['id'] not in removed]}
