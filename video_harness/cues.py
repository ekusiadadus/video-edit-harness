"""Deterministic placement and validation of licensed local edit assets."""

from __future__ import annotations

from fractions import Fraction
from pathlib import Path
import hashlib
import math
import json
import subprocess


ROLES = {"music", "sfx", "image", "video", "title"}
FIELDS = {"id", "asset_id", "role", "output_start", "output_end", "source_start",
          "source_end", "gain_db", "fade_in", "fade_out", "loop", "duck",
          "reason", "text", "position", "opacity", "beat_anchor"}


def _seconds(value, name):
    try:
        result = Fraction(str(value))
        # Frame-aligned JSON durations may be floats (e.g. 56/30 seconds).
        # Recover their rational value while preserving strict string precision.
        if isinstance(value, float) and math.isfinite(value):
            result = result.limit_denominator(1000000000)
    except (TypeError, ValueError, ZeroDivisionError) as exc:
        raise ValueError(f"invalid {name}") from exc
    if result.denominator > 1000000000 or not math.isfinite(float(result)):
        raise ValueError(f"invalid {name}")
    return result


def _asset_map(assets):
    if isinstance(assets, dict):
        return assets
    return {item["asset_id"]: item for item in assets}


def _check_asset(asset_id, assets, *, verify_hash=True):
    if asset_id not in assets:
        raise ValueError(f"unknown asset_id: {asset_id}")
    asset = assets[asset_id]
    path = Path(asset.get("path") or asset.get("local_path") or "")
    if not path.is_file():
        raise ValueError(f"asset missing: {asset_id}")
    expected = asset.get("sha256") or asset.get("file_sha256")
    if not expected or len(expected) != 64:
        raise ValueError(f"asset SHA-256 missing: {asset_id}")
    if verify_hash:
        sha = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(4 * 1024 * 1024), b""):
                sha.update(chunk)
        if sha.hexdigest() != expected:
            raise ValueError(f"asset SHA-256 mismatch: {asset_id}")
    return asset


def validate_cues(cues, assets, duration, fps=None):
    """Return canonical cues, rejecting stale assets and impossible time ranges.

    Times remain exact decimal/rational strings as supplied; frame quantization is
    checked when fps is given but left to the renderer rather than silently moved.
    """
    assets = _asset_map(assets)
    end = _seconds(duration, "duration")
    if end <= 0:
        raise ValueError("duration must be positive")
    if fps is not None and _seconds(fps, "fps") <= 0:
        raise ValueError("fps must be positive")
    normalized, seen, media_durations = [], set(), {}
    for original in cues:
        if set(original) - FIELDS:
            raise ValueError(f"unknown cue fields: {sorted(set(original) - FIELDS)}")
        cue = dict(original)
        cue_id = cue.get("id")
        if not isinstance(cue_id, str) or not cue_id.strip() or cue_id in seen:
            raise ValueError("cue ids must be nonempty and unique")
        seen.add(cue_id)
        role = cue.get("role")
        if role not in ROLES:
            raise ValueError(f"invalid cue role: {role}")
        asset_id = cue.get("asset_id")
        if role == "title" and asset_id is None:
            if not isinstance(cue.get("text"), str) or not cue["text"].strip():
                raise ValueError("title cue needs text")
        else:
            asset = _check_asset(asset_id, assets)
            kind = asset.get("kind")
            if kind and kind != role and not (kind == "audio" and role in {"music", "sfx"}):
                raise ValueError(f"asset kind does not match cue role: {asset_id}")
        start = _seconds(cue.get("output_start"), "output_start")
        stop = _seconds(cue.get("output_end"), "output_end")
        source_start = _seconds(cue.get("source_start", 0), "source_start")
        source_end = _seconds(cue.get("source_end", 0 if role in {"title", "image"} else None), "source_end")
        if start < 0 or stop <= start or stop > end or source_start < 0:
            raise ValueError(f"invalid output/source range: {cue_id}")
        if role not in {"title", "image"} and source_end <= source_start:
            raise ValueError(f"invalid source range: {cue_id}")
        if role not in {"title", "image"}:
            if asset_id not in media_durations:
                record = assets[asset_id]
                measured = subprocess.check_output(["ffprobe", "-v", "error", "-show_entries",
                                                    "format=duration", "-of", "json", record["path"]])
                value = json.loads(measured)["format"].get("duration")
                media_durations[asset_id] = _seconds(value, "asset duration")
            if source_end > media_durations[asset_id] + Fraction(1, 100):
                raise ValueError(f"source range exceeds asset duration: {cue_id}")
        if role == "image" and (source_start or source_end):
            raise ValueError("image cues have no source time range")
        if not cue.get("loop", False) and role in {"music", "sfx", "video"} and source_end - source_start < stop - start:
            raise ValueError(f"source too short without loop: {cue_id}")
        if role in {"image", "title"} and cue.get("loop"):
            raise ValueError(f"loop unsupported for {role}")
        for name in ("gain_db", "fade_in", "fade_out"):
            value = _seconds(cue.get(name, 0), name)
            if name != "gain_db" and value < 0:
                raise ValueError(f"negative {name}")
        if _seconds(cue.get("fade_in", 0), "fade_in") + _seconds(cue.get("fade_out", 0), "fade_out") > stop - start:
            raise ValueError(f"fades exceed cue duration: {cue_id}")
        for name in ("loop", "duck"):
            if name in cue and not isinstance(cue[name], bool):
                raise ValueError(f"{name} must be boolean")
        cue.setdefault("source_start", 0)
        cue.setdefault("gain_db", 0)
        cue.setdefault("fade_in", 0)
        cue.setdefault("fade_out", 0)
        cue.setdefault("loop", False)
        cue.setdefault("duck", role == "music")
        normalized.append(cue)
    return sorted(normalized, key=lambda item: (_seconds(item["output_start"], "output_start"), item["id"]))


def plan_cues(pattern, assets, mapping, duration=None, fps=None, *,
              asset_selection_request=None, asset_policy=None):
    """Propose restrained cues from explicit policy and observed output anchors.

    This is mechanical placement evidence, not selection, review or adoption.
    Unresolved choices are reported as pending instead of silently claiming that
    a requested effect has been supplied.
    """
    from .patterns import resolve_pattern

    assets = _asset_map(assets)
    if not isinstance(mapping, dict):
        raise ValueError('output mapping is required')
    supplied = pattern if isinstance(pattern, dict) else {'id': pattern}
    name = supplied.get('id', 'natural')
    resolved = resolve_pattern({'editing_pattern': {key: value for key, value in supplied.items()
                                                    if key in {'schema_version', 'id', 'intensity', 'music',
                                                               'sfx', 'visual_assets', 'beat_sync', 'selection'}}})
    total = _seconds(duration if duration is not None else mapping.get('duration'), 'duration')
    if total <= 0:
        raise ValueError('duration must be positive')
    reasons, pending, cues = [], [], []
    selection_report = None
    if name == 'natural' or resolved['intensity'] == 'off':
        return {'cues': [], 'reasons': ['Additional music, effects and visual assets are off.'],
                'pending': [], 'pattern': name}

    def asset_duration(asset_id):
        asset = _check_asset(asset_id, assets)
        probe = subprocess.check_output(['ffprobe', '-v', 'error', '-show_entries',
                                         'format=duration', '-of', 'json', asset['path']])
        measured = _seconds(json.loads(probe)['format'].get('duration'), 'asset duration')
        if measured <= 0:
            raise ValueError(f'asset duration missing: {asset_id}')
        return measured

    def moment(value, label):
        return _seconds(value[:-1] if isinstance(value,str) and value.endswith('s') else value, label)

    # Chapter/section starts must come from the rendered mapping. Every row is
    # checked against the output duration; shot cuts without an explicit section
    # identity are not treated as narrative transitions.
    transitions, anchors, previous_section = [], [], None
    rows = mapping.get('sequence', [])
    if rows is not None and not isinstance(rows, list):
        raise ValueError('mapping sequence must be a list')
    for row in rows or []:
        if not isinstance(row, dict):
            raise ValueError('invalid mapping row')
        start = moment(row.get('output_start'), 'output_start')
        stop = moment(row.get('output_end'), 'output_end')
        if not 0 <= start < stop <= total:
            raise ValueError('mapping row outside output')
        anchor_id = row.get('id')
        section = row.get('chapter_id') or row.get('section_id')
        anchors.append((row, start, stop, section))
        if isinstance(section, str) and section and section != previous_section:
            transitions.append((start, stop, section))
            previous_section = section
    actual_transitions = [(start, stop, section) for start, stop, section in transitions if start > 0]

    music_policy = resolved['music']
    if music_policy == 'off':
        reasons.append('Additional music disabled by explicit pattern policy.')
    elif music_policy == 'selected':
        pending.append('Music is selected-only; provide an explicit cue plan and chosen asset.')
    else:
        from .assets import rank_assets, score_asset
        context = dict(asset_selection_request or supplied.get('asset_selection_request') or {})
        context.setdefault('kind', 'music')
        context.setdefault('duration', float(total if music_policy == 'continuous' else min(total / 5, Fraction(8))))
        context.setdefault('dialogue_present', True)
        if context['kind'] != 'music':
            raise ValueError('music selection context must request music')
        if asset_policy is not None:
            report = rank_assets(list(assets.values()), context, asset_policy)
            selection_report = report
            candidates = [item['asset_id'] for item in report['candidates']]
        else:
            # Legacy cue callers provide already chosen local files without a
            # rights record. Verify their bytes before considering context.
            eligible = []
            for key, asset in assets.items():
                if asset.get('kind') not in {'music', 'audio'} or not Path(asset.get('path', '')).is_file():
                    continue
                _check_asset(key, assets)
                eligible.append((score_asset(asset, context)['score'], key))
            candidates = [key for _, key in sorted(eligible, key=lambda item: (-item[0], item[1]))]
        requested = supplied.get('asset_id')
        if requested and requested not in candidates:
            raise ValueError('requested music asset unavailable')
        if not candidates:
            pending.append('No eligible local music asset; music proposal pending asset selection.')
        else:
            chosen = requested or candidates[0]
            length = asset_duration(chosen)
            if music_policy == 'intro_outro':
                span = min(total / 5, Fraction(8))
                placements = [(Fraction(0), span), (total - span, total)] if total > 2 * span else [(Fraction(0), total)]
            elif music_policy == 'continuous':
                placements = [(Fraction(0), total)]
            elif music_policy == 'chapter':
                placements = [(start, min(stop, start + Fraction(2))) for start, stop, _ in actual_transitions]
                if not placements:
                    pending.append('Chapter music needs actual chapter boundaries in the output mapping.')
            else:
                raise ValueError('Unsupported music policy')
            for index, (start, stop) in enumerate(placements, 1):
                span = stop - start
                cue_reason = f'{music_policy} music proposal from context-ranked local asset; review suitability.'
                cues.append({'id': f'music-{index:02d}', 'asset_id': chosen, 'role': 'music',
                             'output_start': str(start), 'output_end': str(stop), 'source_start': '0',
                             'source_end': str(min(length, span)), 'gain_db': 0,
                             'fade_in': str(min(Fraction(1, 2), span / 4)),
                             'fade_out': str(min(Fraction(1, 2), span / 4)),
                             'loop': length < span, 'duck': True, 'reason': cue_reason})
            if placements:
                reasons.append(f'{music_policy} music proposed from {chosen}; suitability and mix need review.')
                if asset_policy is not None:
                    reasons.append(f"Music selection report: {len(report['candidates'])} eligible, {len(report['excluded'])} excluded; no-addition comparison remains available.")

    sfx_policy = resolved['sfx']
    if sfx_policy == 'selected':
        pending.append('Effects are selected-only; provide explicit cue positions and chosen asset.')
    elif sfx_policy == 'accent':
        sounds = sorted(key for key, asset in assets.items() if asset.get('kind') == 'sfx')
        if not actual_transitions:
            pending.append('Effect accents need actual section boundaries in the output mapping.')
        elif not sounds:
            pending.append('Effect accents need an eligible local SFX asset.')
        else:
            chosen = sounds[0]
            length = asset_duration(chosen)
            for index, (start, stop, section) in enumerate(actual_transitions[:3], 1):
                span = min(Fraction(1, 4), length, stop - start)
                if span <= 0:
                    continue
                cues.append({'id': f'sfx-{index:02d}', 'asset_id': chosen, 'role': 'sfx',
                             'output_start': str(start), 'output_end': str(start + span),
                             'source_start': '0', 'source_end': str(span), 'gain_db': -6,
                             'fade_in': 0, 'fade_out': str(min(span / 4, Fraction(1, 20))),
                             'duck': False, 'reason': f'Sparse accent at observed section {section} boundary; review context.'})
            reasons.append(f'Sparse effect accents proposed at {min(len(actual_transitions), 3)} observed boundaries.')

    visual_policy = resolved['visual_assets']
    if visual_policy != 'off':
        added = 0
        for row, start, stop, section in anchors:
            row_id = row.get('id')
            if not isinstance(row_id, str) or not row_id:
                continue
            matched = sorted((key for key, asset in assets.items()
                              if asset.get('kind') in {'image', 'video'}
                              and key != row.get('asset_id')
                              and (visual_policy != 'own_only' or asset.get('owned_by_user') is True)
                              and (f'sequence:{row_id}' in asset.get('tags', [])
                                   or isinstance(section, str) and f'chapter:{section}' in asset.get('tags', [])
                                   and any(at == start and sid == section for at, _, sid in transitions))))
            if not matched:
                continue
            chosen = matched[0]
            asset = _check_asset(chosen, assets)
            span = min(Fraction(2), stop - start)
            if asset['kind'] == 'video':
                span = min(span, asset_duration(chosen))
            if span <= 0:
                continue
            added += 1
            cues.append({'id': f'visual-{added:02d}', 'asset_id': chosen, 'role': asset['kind'],
                         'output_start': str(start), 'output_end': str(start + span),
                         'source_start': '0', 'source_end': str(span) if asset['kind'] == 'video' else '0',
                         'loop': False, 'position': 'top',
                         'reason': f'Asset explicitly tagged for observed sequence {row_id}; visual context needs review.'})
            if added >= 3:
                break
        if added:
            reasons.append(f'{added} explicitly anchored visual asset cue(s) proposed; subject and caption clearance need review.')
        else:
            pending.append('Visual assets need explicit sequence:/chapter: asset tags matching the output mapping.')

    if not cues and not pending:
        reasons.append('No additional cue requested by resolved policy.')
    reasons.extend(pending)
    result = {'cues': validate_cues(cues, assets, total, fps), 'reasons': reasons,
              'pending': pending, 'pattern': name}
    if selection_report is not None:
        result['selection_report'] = selection_report
    return result
