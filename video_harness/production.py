"""Bind optional creative additions to exact assets and an output timeline.

The legacy natural render never invokes the mixer. Rights are checked before
placement, and explicit cue plans cannot be reused against a changed mapping.
"""
from copy import deepcopy
from pathlib import Path

from .assets import validate_asset
from .common import probe
from .cues import plan_cues, validate_cues
from .patterns import resolve_asset_policy, resolve_pattern
from .render_cache import digest


def frozen_pattern(cfg):
    snapshot = cfg.get('_editing_pattern_snapshot')
    if snapshot is None:
        return resolve_pattern(cfg)
    from .patterns import _VALUES
    import re
    if not isinstance(snapshot, dict) or set(snapshot) != {'schema_version', 'id', 'definition_sha256', 'description', *_VALUES}:
        raise ValueError('Invalid frozen editing pattern')
    if type(snapshot['schema_version']) is not int or snapshot['schema_version'] != 1 or snapshot['id'] not in {
            'natural', 'gentle_vlog', 'clear_explainer', 'cinematic_story', 'beat_montage', 'playful_short'}:
        raise ValueError('Unsupported frozen editing pattern')
    if not isinstance(snapshot['description'], str) or not snapshot['description'].strip():
        raise ValueError('Invalid frozen pattern description')
    setting = cfg.get('editing_pattern', {})
    if not isinstance(setting, dict) or setting.get('id', 'natural') != snapshot['id'] or any(
            key in setting and setting[key] != snapshot[key] for key in _VALUES):
        raise ValueError('Editing settings differ from their frozen snapshot; revise through the session')
    if not isinstance(snapshot['definition_sha256'], str) or not re.fullmatch('[0-9a-f]{64}', snapshot['definition_sha256']):
        raise ValueError('Invalid frozen definition SHA')
    for key, values in _VALUES.items():
        if snapshot[key] not in values:
            raise ValueError('Invalid frozen pattern setting')
    if snapshot['id'] == 'natural' or snapshot['intensity'] == 'off':
        if any(snapshot[k] != 'off' for k in ('music', 'sfx', 'visual_assets', 'beat_sync')):
            raise ValueError('Frozen natural pattern cannot add effects')
    return deepcopy(snapshot)


def freeze_pattern(cfg, refresh=False):
    result = deepcopy(cfg)
    if 'editing_pattern' in result:
        result['_editing_pattern_snapshot'] = resolve_pattern(result) if refresh else frozen_pattern(result)
    return result


def resolve_production(cfg, mapping):
    pattern = frozen_pattern(cfg)
    from .composition import resolve_guides
    composition = resolve_guides(cfg['composition_guides'], mapping) if 'composition_guides' in cfg else None
    from .video_effects import resolve_effects
    effects = resolve_effects(cfg.get('video_effects'), mapping, cfg.get('assets', []))
    if effects['events'] and (pattern['id'] == 'natural' or pattern['intensity'] == 'off'):
        raise ValueError('Requested video effects conflict with natural/off; select an enabled editing pattern')
    policy = resolve_asset_policy(cfg)
    records = cfg.get('assets', [])
    if not isinstance(records, list):
        raise ValueError('assets must be a list of registered records')
    ids = [a.get('asset_id') for a in records if isinstance(a, dict)]
    if len(ids) != len(records) or any(not isinstance(i, str) for i in ids) or len(set(ids)) != len(ids):
        raise ValueError('assets need unique asset IDs')
    mapping_sha = digest(mapping)
    source_assets = []
    if mapping.get('edit_basis') == 'visual':
        used_sources = {row['asset_id'] for row in mapping['sequence']}
        source_assets = [validate_asset(a, policy) for a in records if a['asset_id'] in used_sources]
        if {a['asset_id'] for a in source_assets} != used_sources:
            raise ValueError('Visual mapping refers to an unregistered source asset')
    # Selecting natural intentionally clears every previous creative addition.
    if pattern['id'] == 'natural' or pattern['intensity'] == 'off':
        result = {'version': 1, 'pattern': pattern, 'policy': policy,
                'mapping_sha256': mapping_sha, 'assets': [], 'source_assets': source_assets, 'cues': [],
                'reasons': ['Additional music, effects, visuals and beat sync are off.']}
        if composition is not None:
            result['composition'] = composition
        return result
    assets = {}
    for record in records:
        asset = validate_asset(record, policy)
        if asset['kind'] != 'image':
            media = probe(asset['path'])
            asset['duration'] = float(media['format']['duration'])
        assets[asset['asset_id']] = asset
    explicit = cfg.get('cue_plan')
    duration = mapping['duration']
    if explicit is not None:
        if not isinstance(explicit, dict) or set(explicit) != {'version', 'mapping_sha256', 'cues'} or explicit['version'] != 1:
            raise ValueError('cue_plan needs version, mapping_sha256 and cues')
        if explicit['mapping_sha256'] != mapping_sha:
            raise ValueError('Cue plan is stale: output timeline changed')
        cues = validate_cues(explicit['cues'], assets, duration)
        reasons = ['Explicit timeline-bound cue plan.']
    else:
        context = deepcopy(cfg.get('asset_selection_request', {}))
        context.setdefault('dialogue_present', mapping.get('edit_basis') != 'visual')
        # Ranking validates the sealed registry, not runtime-enriched copies.
        # Adding measured duration to a record invalidates its record digest.
        proposed = plan_cues(pattern, records, mapping, duration=duration,
                             asset_selection_request=context, asset_policy=policy)
        cues, reasons = proposed['cues'], proposed['reasons']
    for cue in cues:
        enabled = {'music': pattern['music'], 'sfx': pattern['sfx'],
                   'image': pattern['visual_assets'], 'video': pattern['visual_assets'],
                   'title': pattern['visual_assets']}[cue['role']]
        if enabled == 'off':
            raise ValueError('Cue contradicts disabled pattern setting: ' + cue['role'])
        if cue.get('asset_id') and cue['role'] in {'image', 'video'} and pattern['visual_assets'] == 'own_only':
            # Self ownership must be supplied as a registry fact, not inferred
            # from an image filename or the provider of the license.
            if not assets[cue['asset_id']].get('owned_by_user', False):
                raise ValueError('Pattern permits user-owned visual assets only')
    used = {c['asset_id'] for c in cues if c.get('asset_id')}
    for event in effects['events']:
        if event['type'] in {'keyword_title','tracked_title'} and pattern['visual_assets'] == 'off':
            raise ValueError('Keyword title contradicts disabled visual assets')
        if event['type'] == 'comparison_wipe':
            asset_id = event['parameters']['asset_id']
            if pattern['visual_assets'] == 'off':
                raise ValueError('Comparison contradicts disabled visual assets')
            if pattern['visual_assets'] == 'own_only' and not assets[asset_id].get('owned_by_user', False):
                raise ValueError('Pattern permits user-owned visual assets only')
            used.add(asset_id)
    result = {'version': 1, 'pattern': pattern, 'policy': policy,
            'mapping_sha256': mapping_sha,
            'source_assets': source_assets,
            'assets': [deepcopy(next(a for a in records if a['asset_id'] == i)) for i in sorted(used)],
            'cues': cues, 'reasons': reasons}
    if effects['events']:
        result['effects'] = effects
    if composition is not None:
        result['composition'] = composition
    if explicit is None and proposed.get('selection_report') is not None:
        result['selection_report'] = proposed['selection_report']
    return result


def mix_key(production):
    """Include rights and definitions as well as media bytes in cache identity."""
    return digest(production)


def verify_production(production, operation='embedded_use'):
    if 'composition' in production:
        composition = production['composition']
        if not isinstance(composition, dict) or composition.get('version') != 1 or not production.get('mapping_sha256') or composition.get('mapping_sha256') != production['mapping_sha256']:
            raise ValueError('Composition guides are stale')
        from .composition import guide_track
        for guide in composition.get('guides',[]):
            if 'track_path' in guide:guide_track(guide)
    if production.get('effects', {}).get('events'):
        if production['effects'].get('mapping_sha256') != production.get('mapping_sha256'):
            raise ValueError('Video effects are stale against the production mapping')
        from .video_effects import _tracking_data
        from fractions import Fraction
        import json
        for event in production['effects']['events']:
            if event['type'] in {'tracked_zoom','tracked_title'}:
                doc=json.loads(Path(event['parameters']['track_path']).read_text())
                _tracking_data(event,Fraction(doc['fps']))
    assets = {a['asset_id']: a for a in production.get('source_assets', []) + production['assets']}
    audio_source_ids = {a['asset_id'] for a in production.get('source_assets', [])}
    audio_source_ids.update(c['asset_id'] for c in production.get('cues', [])
                            if c.get('role') in {'music', 'sfx'} and c.get('asset_id'))
    for asset in assets.values():
        if operation == 'mixed_audio_handoff':
            if asset['kind'] == 'image':
                continue
            if asset['kind'] == 'video' and asset['asset_id'] not in audio_source_ids:
                # Overlay/comparison picture does not contribute its audio.
                continue
            if asset['kind'] == 'video' and not any(s['codec_type'] == 'audio' for s in probe(asset['path'])['streams']):
                continue
        validate_asset(asset, production['policy'], operation)
    return deepcopy(production)


def prepare_fcp_handoff(cfg, production, out):
    """Prepare a legal explicit handoff, without claiming GUI fidelity."""
    from .common import fingerprint, read, run, write
    from .fcp import export_timeline
    from .production_fcp import export_production_xml
    out = Path(out)
    mode = cfg.get('fcp_handoff', 'mix')
    if mode not in ('mix', 'editable', 'video_only'):
        raise ValueError('Invalid fcp_handoff mode')
    if mode == 'editable' and production.get('effects', {}).get('events'):
        raise ValueError('Video effects require burned mix/video_only handoff; editable FCP effects are unsupported')
    if mode == 'editable' and cfg.get('retime'):
        raise ValueError('Retime requires burned mix/video_only handoff; editable FCP time changes are unsupported')
    if mode == 'editable' and cfg.get('audio_cuts') is not None:
        raise ValueError('J/L audio cuts require baked mix/video_only handoff; editable FCP audio cuts are unsupported')
    verify_production(production)
    operation = 'raw_asset_handoff' if mode == 'editable' else 'mixed_audio_handoff'
    if mode != 'video_only':
        try:
            verify_production(production, operation)
        except ValueError:
            if 'fcp_handoff' in cfg:
                raise ValueError('Requested FCP handoff is not licensed: ' + operation)
            mode = 'video_only'
    pcm = None
    base = out / 'timeline.fcpxml'
    output = out / 'production-timeline.fcpxml'
    if mode == 'mix':
        # Preserve finished pixels without carrying an audio stream into FCP.
        # FCP has been observed omitting srcEnable=video on import/export, so
        # the dependency itself must be silent to prevent double playback.
        duration = read(out / 'frame-mapping.json')['duration']
        pcm = out / 'final-mix.wav'
        run(['ffmpeg', '-v', 'error', '-nostdin', '-n', '-i', str(out / 'video.mp4'),
             '-vn', '-t', str(duration), '-ar', '48000', '-ac', '2', '-c:a', 'pcm_s16le',
             str(pcm)], out / 'final-mix.log')
        picture = out / 'finished-picture.mp4'
        run(['ffmpeg', '-v', 'error', '-nostdin', '-n', '-i', str(out / 'video.mp4'),
             '-map', '0:v:0', '-c:v', 'copy', '-an', '-map_metadata', '-1',
             '-movflags', '+faststart', str(picture)], out / 'finished-picture.log')
        if any(s['codec_type'] == 'audio' for s in probe(picture)['streams']):
            raise ValueError('Finished picture unexpectedly contains audio')
        base = out / 'finished-picture.fcpxml'
        export_timeline(picture, probe(picture), [(0, duration)], base,
                        cfg.get('name', 'Production Mix'))
    evidence = export_production_xml(base, production, pcm, output, mode)
    if mode == 'mix':
        evidence['picture'] = 'Finished graded MP4, including overlays; do not apply look.cube again.'
        evidence['picture_file'] = fingerprint(picture)
    evidence['rights_operation'] = operation if mode != 'video_only' else 'embedded_use'
    write(out / 'fcp-production.json', evidence)
    return evidence


def production_sources(production):
    return {a['asset_id']: a for a in production['assets']}
