"""Prepare an offline, source-verified public sample from a release fixture ZIP."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from video_harness.common import fingerprint
from video_harness.transcript import save_transcript

FILES = {'sample.mp4', 'timing.json', 'provenance.json', 'LICENSE'}
MAX_FIXTURE_BYTES = 32 * 1024 * 1024


def prepare(fixture, output):
    fixture, output = Path(fixture).resolve(), Path(output).resolve()
    with zipfile.ZipFile(fixture) as archive:
        entries = archive.infolist()
        if {e.filename for e in entries} != FILES or len(entries) != len(FILES):
            raise ValueError('Fixture must contain exactly sample.mp4, timing.json, provenance.json and LICENSE')
        if sum(e.file_size for e in entries) > MAX_FIXTURE_BYTES:
            raise ValueError('Fixture is larger than the supported public sample')
        payloads = {name: archive.read(name) for name in FILES}
    provenance = json.loads(payloads['provenance.json'])
    if provenance.get('source_kind') != 'synthetic':
        raise ValueError('This helper accepts only the synthetic public sample')
    digest = hashlib.sha256(payloads['sample.mp4']).hexdigest()
    if digest != provenance.get('source_sha256'):
        raise ValueError('Fixture source hash does not match its provenance')
    timing = json.loads(payloads['timing.json'])
    if timing.get('source_sha256') != digest:
        raise ValueError('Word timing belongs to a different source')
    if provenance.get('voice', {}).get('language') not in ('ja', 'en') or timing.get('language') != provenance['voice']['language']:
        raise ValueError('Fixture voice and measured transcript languages must agree (ja or en)')
    output.mkdir(parents=True, exist_ok=False)
    for name, data in payloads.items():
        (output / name).write_bytes(data)
    data = {k: timing[k] for k in ('version','duration','language','backend','words','segments','semantic_text','warnings')}
    data['source'] = fingerprint(output / 'sample.mp4')
    sealed = save_transcript(output / 'transcript', data)
    project = {
        'name': 'Public desk sample', 'source': str(output / 'sample.mp4'),
        'input_color': 'rec709', 'evidence_kind': 'synthetic', 'use_case': 'indoor_talk',
        'style': 'natural', 'preview': {'start': 0, 'duration': data['duration']},
        'audio': {'normalize': True, 'target_lufs': -18, 'true_peak_db': -1.5, 'loudness_range': 7},
        'editorial': {'goal': 'Keep both practical tips; shorten the long pause without cutting speech'},
        'cloud_permission': {'source_sha256': digest, 'policy': 'deny', 'providers': [],
                             'basis': 'Offline public fixture has existing measured word timing; no upload required'}
    }
    (output / 'project.json').write_text(json.dumps(project, ensure_ascii=False, indent=2)+'\n')
    result = {'project': str(output / 'project.json'), 'source': data['source'],
              'transcript': str(sealed), 'cloud_upload': 'denied',
              'note': 'API-measured word timing is resealed for this verified local copy; no ASR is run.'}
    (output / 'prepared.json').write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n')
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--fixture', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(prepare(args.fixture, args.output), ensure_ascii=False, indent=2))
