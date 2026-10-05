"""Immutable delivery bundles with explicit Final Cut and perceptual work remaining."""
from pathlib import Path
import shutil

from .common import fingerprint, read, write


def bundle(render, brief, target, folder, accepted=False):
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
    required = ['fcp_import', 'fcp_playback', 'fcp_grade', 'fcp_captions', 'fcp_mix'] if target == 'fcp' else []
    manifest = {'version': 1, 'render_id': render['id'], 'render_sha256': render['files']['video']['sha256'],
                'plan': render['plan'], 'project': render['project'], 'brief': brief,
                'render_kind': 'preview' if render['preview'] else 'full_resolution',
                'target': target, 'creative_review': 'accepted' if accepted else 'pending',
                'status': 'needs_manual_checks' if required else 'ready' if accepted and not render['preview'] else 'needs_review',
                'manual_checks_required': required, 'files': files,
                'fidelity': {'timeline': 'single-source flat ordered cuts', 'lut': 'separate_manual_FCP_application',
                             'captions': 'separate_SRT_import', 'spatial_masks': 'manual',
                             'audio': 'MP4 normalized; FCP mix requires its own final check'}}
    write(folder / 'delivery.json', manifest)
    return folder / 'delivery.json'
