"""Immutable delivery bundles with explicit Final Cut and perceptual work remaining."""
from pathlib import Path
import shutil

from .common import fingerprint, read, write


def _copy_depth_provenance(render, folder, files):
    """Retain field lineage without distributing source footage or model weights."""
    if 'depth_evidence' not in render['files']:
        return
    from .depth_artifact import validate_depth
    evidence_ref = render['files']['depth_evidence']
    if fingerprint(evidence_ref['path']) != evidence_ref:
        raise ValueError('Depth render evidence changed before delivery')
    evidence = read(evidence_ref['path'])
    manifest_ref = evidence['setting']['manifest']
    if fingerprint(manifest_ref['path']) != manifest_ref:
        raise ValueError('Depth manifest changed before delivery')
    validate_depth(manifest_ref['path'])
    refs = {}
    lineage = []
    seen = set()
    def add(ref):
        if fingerprint(ref['path']) != ref:
            raise ValueError('Depth provenance changed before delivery')
        if Path(ref['path']).suffix == '.npy':
            refs[ref['sha256']] = ref
    def visit(ref):
        if ref['sha256'] in seen:
            return
        seen.add(ref['sha256'])
        add(ref)
        doc = read(ref['path'])
        item = {'manifest_sha256': ref['sha256'], 'version': doc['version'],
                'algorithm': doc['algorithm'], 'parent_sha256': doc.get('parent', {}).get('sha256'),
                'corrected_frames': doc.get('corrected_frames', []),
                'source_sha256': doc['source']['sha256'],
                'interval': [doc['start_frame'], doc['end_frame_exclusive']],
                'fps': doc['fps'], 'width': doc['width'], 'height': doc['height'],
                'source_frame_count': doc['source_frame_count'],
                'representation': doc['representation'], 'normalization': doc['normalization'],
                'rows': [{'frame': row['frame'], 'field_sha256': row['field']['sha256'],
                          'input_sha256': row['input']['sha256'], 'origin': row['origin'],
                          'minimum': row['minimum'], 'maximum': row['maximum']}
                         for row in doc['rows']]}
        if doc.get('inference'):
            model = doc['inference']['model']
            item['model'] = {key: model[key] for key in ('model_id', 'revision', 'license',
                                                       'device', 'runtime', 'config', 'processor', 'inference')}
            item['model']['files'] = {name: {'sha256': identity['sha256'], 'bytes': identity['bytes']}
                                      for name, identity in model['files'].items()}
            item['execution_sha256'] = doc['inference']['execution']['sha256']
            item['raw_fields'] = [{'frame': raw['frame'], 'sha256': raw['field']['sha256']}
                                  for raw in doc['inference']['raw_fields']]
            item['normalization_range'] = [doc['inference']['minimum'], doc['inference']['maximum']]
            item['temporal_consistency'] = doc['inference']['temporal_consistency']
        lineage.append(item)
        for row in doc['rows']:
            add(row['field']); add(row['input'])
        if doc.get('inference'):
            for raw in doc['inference']['raw_fields']:
                add(raw['field'])
        if doc.get('parent'):
            visit(doc['parent'])
    visit(manifest_ref)
    provenance_dir = folder / 'depth-provenance'
    provenance_dir.mkdir()
    entries = []
    for sha, ref in sorted(refs.items()):
        source = Path(ref['path'])
        relative = 'depth-provenance/' + sha + source.suffix
        target = folder / relative
        shutil.copy2(source, target)
        if fingerprint(target)['sha256'] != sha or fingerprint(source) != ref:
            raise ValueError('Depth provenance changed during copy')
        files['depth_provenance_' + sha] = fingerprint(target)
        entries.append({'path': relative, 'sha256': sha, 'bytes': ref['bytes']})
    image = evidence['image_asset']
    image_identity = {key: image[key] for key in ('asset_id', 'sha256', 'bytes', 'record_sha256')}
    summary = {'version': 1, 'render_sha256': render['files']['video']['sha256'],
               'graded_source_sha256': evidence['base']['sha256'],
               'manifest_sha256': manifest_ref['sha256'],
               'original_evidence_sha256': evidence_ref['sha256'],
               'image_asset': image_identity,
               'parameters': evidence['parameters'],
               'lineage': lineage,
               'raw_image': 'external_reference_only',
               'model_weights': 'external_reference_only',
               'rerenderable_from_bundle_alone': False, 'entries': entries}
    write(folder / 'depth-provenance.json', summary)
    files['depth_provenance'] = fingerprint(folder / 'depth-provenance.json')
    write(folder / 'depth-evidence.json', {'version': 1, 'render_sha256': summary['render_sha256'],
        'original_evidence_sha256': summary['original_evidence_sha256'],
        'graded_source_sha256': summary['graded_source_sha256'],
        'manifest_sha256': summary['manifest_sha256'],
        'image_asset': image_identity, 'parameters': summary['parameters'],
        'provenance_sha256': files['depth_provenance']['sha256'],
        'review_required': True, 'adopted': False})
    files['depth_evidence'] = fingerprint(folder / 'depth-evidence.json')


def bundle(render, brief, target, folder, accepted=False, derivative=None):
    production = None
    prepared_fcp = None
    if render['files'].get('production'):
        reference = render['files']['production']
        if fingerprint(reference['path']) != reference:
            raise ValueError('Production evidence changed before delivery')
        production = read(reference['path'])
        if production.get('policy', {}).get('content_id_check') == 'pending_local_review':
            raise ValueError('Local review only: resolve Content ID checks before distribution delivery')
        from .production import verify_production
        verify_production(production)
        if target == 'fcp':
            from .delivery_production import preflight
            prepared_fcp = preflight(render, production)
    audio_allowed = True
    if production:
        try:
            verify_production(production, 'mixed_audio_handoff')
        except ValueError:
            audio_allowed = False
    folder = Path(folder).resolve()
    folder.mkdir(parents=True, exist_ok=False)
    files = {}
    labels = ['video', 'audio', 'xml', 'subtitles', 'lut', 'mapping', 'plan']
    labels += [key for key in ('transitions', 'pre_transition_mapping', 'motion_template') if key in render['files']]
    for label in labels:
        if production and (label == 'xml' or label == 'audio' and not audio_allowed):
            continue
        original = Path(render['files'][label]['path'])
        if fingerprint(original) != render['files'][label]:
            raise ValueError('Delivery source changed: ' + label)
        copied = folder / original.name
        shutil.copy2(original, copied)
        files[label] = fingerprint(copied)
        if files[label]['sha256'] != render['files'][label]['sha256'] or fingerprint(original) != render['files'][label]:
            raise ValueError('Delivery source changed during copy: ' + label)
    render_path = Path(render['path'])
    _copy_depth_provenance(render, folder, files)
    if prepared_fcp:
        from .delivery_production import copy_dependencies, verify_dependencies
        files.update(copy_dependencies(prepared_fcp, folder))
        verify_dependencies(folder)
    if production:
        # Export attribution without publishing private catalog/evidence paths.
        credit_assets = {a['asset_id']: a for a in production.get('source_assets', []) + production['assets']}
        credits = [{'asset_id': a['asset_id'], 'credit': a['credit'],
                    'source_url': a['source_url'], 'license_url': a['license_url'],
                    'rights': a['rights'], 'verified_on': a['verified_on'], 'content_id': a['content_id'],
                    'sha256': a['sha256']} for a in credit_assets.values()]
        write(folder / 'credits.json', {'version': 1, 'assets': credits})
        files['credits'] = fingerprint(folder / 'credits.json')
    for name in ('fcp-delivery.json', 'audio-output-measure.json', 'cache-report.json'):
        if (render_path / name).is_file():
            shutil.copy2(render_path / name, folder / name)
            files[name] = fingerprint(folder / name)
    instructions = [
        '1. Import timeline.fcpxml into a new FCP project and confirm media links and cut timing.',
        '2. Apply look.cube. For Apple Log, disable the Camera LUT to avoid double conversion.',
        '3. Import subtitles.srt and inspect wording and readability.',
        '4. Reproduce any fixed spatial masks from fcp-delivery.json.',
        '5. Check the final FCP mix after editing; its source audio is not the normalized MP4 mix.',
        '6. Export FCPXML after manual edits and import it through the supported flat timeline workflow.',
        '7. Record actual GUI/playback/grade/caption/audio checks; XML validation does not perform them.',
    ]
    if production:
        instructions = [
            'This bundle delivers the reviewed MP4 with its final creative additions.',
            'No editable production FCPXML is included in this delivery mode.',
            'Publish the attribution in credits.json where the asset license requires it.',
            'Separated audio is omitted when mixed_audio_handoff is not permitted.',
            'Do not redistribute raw assets from the local catalog.',
        ]
    if prepared_fcp:
        instructions = [
            'Import timeline.fcpxml. Media URLs are relative to this file; keep the media folder beside it.',
            'Mode: ' + prepared_fcp['mode'],
            'Finished-picture mix mode already includes its grade and overlays. Do not apply look.cube again.'
            if prepared_fcp['mode'] == 'mix' else 'Editable mode keeps source picture; apply and inspect grade, overlays and final mix.',
            'Publish the required attribution from credits.json.',
            'GUI import, playback and re-export checks remain outstanding.',
        ] + prepared_fcp['evidence']['manual_remaining']
    (folder / 'FCP-INSTRUCTIONS.txt').write_text('\n'.join(instructions) + '\n')
    files['instructions'] = fingerprint(folder / 'FCP-INSTRUCTIONS.txt')
    portrait = None
    if derivative is not None:
        source = Path(derivative['video']['path'])
        if fingerprint(source) != derivative['video']:
            raise ValueError('Portrait output changed before delivery')
        target_file = folder / 'portrait-video.mp4'
        shutil.copy2(source, target_file)
        files['portrait_video'] = fingerprint(target_file)
        if files['portrait_video']['sha256'] != derivative['video']['sha256']:
            raise ValueError('Portrait output changed during delivery')
        portrait = {'derivative_id': derivative['id'], 'render_sha256': derivative['render_sha256'],
                    'video_sha256': derivative['video']['sha256'], 'framing': derivative['framing'],
                    'subtitles_sha256': (derivative.get('subtitles_source') or {}).get('sha256'),
                    'font_sha256': (derivative.get('font_source') or {}).get('sha256')}
    required = ['fcp_import', 'fcp_playback', 'fcp_grade', 'fcp_captions', 'fcp_mix'] if target == 'fcp' else []
    manifest = {'version': 1, 'render_id': render['id'], 'render_sha256': render['files']['video']['sha256'],
                'plan': render['plan'], 'project': render['project'], 'brief': brief,
                'render_kind': 'preview' if render['preview'] else 'full_resolution',
                'target': target, 'creative_review': 'accepted' if accepted else 'pending',
                'status': 'needs_manual_checks' if required else 'ready' if accepted and not render['preview'] else 'needs_review',
                'manual_checks_required': required, 'files': files, 'portrait': portrait,
                'file_paths': {label: str(Path(ref['path']).relative_to(folder)) for label, ref in files.items()},
                'fidelity': {'timeline': 'single-source flat ordered cuts', 'lut': 'separate_manual_FCP_application',
                             'captions': 'separate_SRT_import', 'spatial_masks': 'manual',
                             'audio': 'MP4 normalized; FCP mix requires its own final check'}}
    if prepared_fcp:
        manifest['fidelity'] = {'mode': prepared_fcp['mode'],
                                'timeline': 'production layers with bundled relative media references',
                                'picture': 'finished graded picture' if prepared_fcp['mode'] == 'mix' else 'original picture plus editable cues',
                                'audio': 'final PCM replacement' if prepared_fcp['mode'] == 'mix' else 'editable gains; ducking and final mix require review',
                                'manual_remaining': prepared_fcp['evidence']['manual_remaining']}
    write(folder / 'delivery.json', manifest)
    return folder / 'delivery.json'


def verify_completion(folder):
    """Verify a finished bundle without access to its originating session."""
    folder = Path(folder)
    completion = read(folder / 'completion.json')
    listed = {}
    for entry in completion['files']:
        relative = Path(entry['path'])
        if relative.is_absolute() or '..' in relative.parts:
            raise ValueError('Unsafe completed delivery path')
        candidate = folder / relative
        if str(relative) in listed or not candidate.is_file() or fingerprint(candidate)['sha256'] != entry['sha256']:
            raise ValueError('Completed delivery file changed: ' + entry['path'])
        listed[str(relative)] = entry['sha256']
    actual = {str(path.relative_to(folder)) for path in folder.rglob('*') if path.is_file() and path != folder / 'completion.json'}
    if set(listed) != actual:
        raise ValueError('Completed delivery file inventory changed')
    manifest = read(folder / 'delivery.json')
    if completion['render_id'] != manifest['render_id'] or completion['render_sha256'] != manifest['render_sha256']:
        raise ValueError('Completion does not match delivery render')
    if completion.get('portrait') != manifest.get('portrait') or completion.get('portrait_video_sha256') != (
            manifest.get('portrait') or {}).get('video_sha256'):
        raise ValueError('Completion portrait does not match delivery')
    for label, ref in manifest['files'].items():
        name = manifest.get('file_paths', {}).get(label, Path(ref['path']).name)
        if listed.get(name) != ref['sha256']:
            raise ValueError('Delivery manifest file changed: ' + name)
    if manifest['files'].get('fcp_dependencies'):
        from .delivery_production import verify_dependencies
        verify_dependencies(folder)
    def proof(key):
        relative = completion['evidence'].get(key)
        if not isinstance(relative, str) or relative not in listed or not relative.startswith('evidence/'):
            raise ValueError('Completion proof missing: ' + key)
        return read(folder / relative)
    project = proof('project')
    expected_status = 'synthetic_complete' if project.get('evidence_kind') == 'synthetic' else 'complete'
    if completion['status'] != expected_status or completion.get('manual_checks_remaining') != []:
        raise ValueError('Completion status contradicts project or pending checks')
    creative = proof('creative_review')
    if (creative.get('render_id') != completion['render_id'] or not creative.get('passed')
            or creative.get('report', {}).get('render_sha256') != completion['render_sha256']):
        raise ValueError('Creative review does not match completed render')
    if manifest['files'].get('depth_evidence'):
        if not any(check.get('id') == 'depth_contours' and check.get('status') == 'pass'
                   for check in creative.get('report', {}).get('checks', [])):
            raise ValueError('Completed depth render lacks passing contour review')
        provenance = read(folder / manifest['file_paths']['depth_provenance'])
        depth_proof = read(folder / manifest['file_paths']['depth_evidence'])
        if (provenance['render_sha256'] != completion['render_sha256']
                or provenance['manifest_sha256'] not in {entry['manifest_sha256'] for entry in provenance['lineage']}
                or depth_proof['provenance_sha256'] != manifest['files']['depth_provenance']['sha256']
                or depth_proof['original_evidence_sha256'] != provenance['original_evidence_sha256']):
            raise ValueError('Completed depth provenance differs from render')
    required = manifest['manual_checks_required']
    recorded = {key.removeprefix('delivery_check_') for key in completion['evidence']
                if key.startswith('delivery_check_')}
    if (set(completion['checks']) != recorded or not set(required) <= recorded
            or any(completion['checks'][key] != 'pass' for key in required)):
        raise ValueError('Completion checks contradict delivery requirements')
    for check, status in completion['checks'].items():
        observation = proof('delivery_check_' + check)
        if (observation.get('check') != check or observation.get('status') != status
                or observation.get('delivery_id') != completion['delivery_id']
                or observation.get('render_sha256') != completion['render_sha256']):
            raise ValueError('Delivery check proof contradicts completion: ' + check)
    if manifest.get('portrait'):
        portrait = proof('portrait_review')
        if (not portrait.get('passed') or portrait.get('derivative_id') != manifest['portrait']['derivative_id']
                or portrait.get('video_sha256') != manifest['portrait']['video_sha256']
                or listed.get('portrait-video.mp4') != manifest['portrait']['video_sha256']):
            raise ValueError('Portrait review contradicts completion')
    return completion
