"""Read-only release inventory audit; no extraction or network access."""
import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import tarfile
import zipfile

PRIVATE_DIRS = {'output', 'media', 'sessions', 'cache', 'baselines', '.venv',
                'release-assets', 'dist', 'build', '__pycache__'}
MEDIA_SUFFIXES = {'.mp4', '.mov', '.wav', '.mp3', '.m4a', '.aif', '.flac', '.fcpbundle'}
PATTERNS = {'natural', 'gentle_vlog', 'clear_explainer', 'cinematic_story',
            'beat_montage', 'playful_short'}


def audit_member(name, body, secrets=()):
    path = PurePosixPath(name)
    if path.is_absolute() or '..' in path.parts or '\\' in name:
        raise ValueError('Unsafe archive member path')
    if PRIVATE_DIRS.intersection(path.parts) or path.name in {'.env', 'state.json', 'session.json'}:
        raise ValueError('Private workspace member: ' + name)
    if path.suffix.lower() in MEDIA_SUFFIXES and 'docs/demo' not in str(path):
        raise ValueError('Unapproved media member: ' + name)
    if any(secret in body for secret in secrets):
        # Report only the member, never a matched credential or its name/value.
        raise ValueError('Configured credential found in archive member: ' + name)
    return {'name': name, 'bytes': len(body), 'sha256': hashlib.sha256(body).hexdigest()}


def audit(folder):
    folder = Path(folder).resolve()
    manifest = json.loads((folder / 'RELEASE-MANIFEST.json').read_text())
    tag=manifest['version']
    package_version=tag.removeprefix('v').replace('-alpha.','a')
    required={f'video_edit_harness-{package_version}-py3-none-any.whl',
              f'video_edit_harness-{package_version}.tar.gz',
              *(f'{name}-skill-{tag}.zip' for name in ('video-editing','tiktok','youtube')),
              f'video-editing-claude-plugin-{tag}.zip'}
    if {entry['name'] for entry in manifest['artifacts']}!=required or len(manifest['artifacts'])!=len(required):
        raise ValueError('Release inventory must contain exactly the wheel, sdist, three skills and plugin')
    secrets = [v.encode() for key, v in os.environ.items()
               if any(token in key.upper() for token in ('API_KEY', 'TOKEN', 'PASSWORD', 'SECRET'))
               and len(v) >= 8]
    inventory = []
    for entry in manifest['artifacts']:
        name = entry['name']
        if PurePosixPath(name).name != name:
            raise ValueError('Invalid artifact path')
        archive = folder / name
        raw = archive.read_bytes()
        if len(raw) != entry['bytes'] or hashlib.sha256(raw).hexdigest() != entry['sha256']:
            raise ValueError('Artifact differs from release manifest: ' + name)
        members = []
        if name.endswith(('.zip', '.whl')):
            with zipfile.ZipFile(archive) as stream:
                for item in stream.infolist():
                    if not item.is_dir():
                        members.append(audit_member(item.filename, stream.read(item), secrets))
        elif name.endswith('.tar.gz'):
            with tarfile.open(archive) as stream:
                for item in stream.getmembers():
                    if item.issym() or item.islnk():
                        # Public source artifacts need no links: reject them
                        # rather than extracting or following archive paths.
                        raise ValueError('Archive link requires explicit review: ' + item.name)
                    if item.isfile():
                        members.append(audit_member(item.name, stream.extractfile(item).read(), secrets))
        else:
            raise ValueError('Unknown release artifact type')
        names = {m['name'] for m in members}
        if name.endswith('.whl'):
            for pattern in PATTERNS:
                if f'video_harness/data/editing_patterns/{pattern}.json' not in names:
                    raise ValueError('Wheel lacks editing pattern: ' + pattern)
            for module in ('production', 'production_cli', 'production_import', 'beat_editing', 'video_effects',
                           'assets','comparison','tracking','tracking_pose','retime','retime_audio','retime_mapping'):
                if f'video_harness/{module}.py' not in names:
                    raise ValueError('Wheel lacks production module: ' + module)
            if len([n for n in names if n.startswith('video_harness/data/trend_profiles/')]) < 2:
                raise ValueError('Wheel lacks trend observations')
        inventory.append({**entry, 'members': members})
    sums = (folder / 'SHA256SUMS').read_text().splitlines()
    for line in sums:
        sha, name = line.split('  ', 1)
        if PurePosixPath(name).name != name or hashlib.sha256((folder / name).read_bytes()).hexdigest() != sha:
            raise ValueError('Release checksum mismatch')
    expected = {e['name'] for e in manifest['artifacts']} | {'RELEASE-MANIFEST.json'}
    if {line.split('  ', 1)[1] for line in sums} != expected:
        raise ValueError('Checksum inventory differs from release manifest')
    return {'status': 'pass', 'version': manifest['version'], 'artifacts': inventory,
            'scope': 'Archive paths, media inventory, configured credential bytes, packaged definitions and checksums. No proof of all possible secrets or GUI behavior.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('folder', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = audit(args.folder)
    args.output.write_text(json.dumps(result, indent=2) + '\n')
    print('Release artifact audit passed:', len(result['artifacts']), 'artifacts')


if __name__ == '__main__':
    main()
