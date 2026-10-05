"""Immutable delivery bundles with explicit Final Cut and perceptual work remaining."""
from pathlib import Path
import shutil

from .common import fingerprint, read, write


def bundle(render, brief, target, folder, accepted=False, derivative=None):
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=False)
    files = {}
    for label in ('video', 'audio', 'xml', 'subtitles', 'lut', 'mapping', 'plan'):
        original = Path(render['files'][label]['path'])
        if fingerprint(original) != render['files'][label]:
            raise ValueError('Delivery source changed: ' + label)
        copied = folder / original.name
        shutil.copy2(original, copied)
        files[label] = fingerprint(copied)
        if files[label]['sha256'] != render['files'][label]['sha256'] or fingerprint(original) != render['files'][label]:
            raise ValueError('Delivery source changed during copy: ' + label)
    render_path = Path(render['path'])
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
                'fidelity': {'timeline': 'single-source flat ordered cuts', 'lut': 'separate_manual_FCP_application',
                             'captions': 'separate_SRT_import', 'spatial_masks': 'manual',
                             'audio': 'MP4 normalized; FCP mix requires its own final check'}}
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
    for ref in manifest['files'].values():
        name = Path(ref['path']).name
        if listed.get(name) != ref['sha256']:
            raise ValueError('Delivery manifest file changed: ' + name)
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
