"""Build the portable skill archive and checksums alongside uv's wheel/sdist."""
import argparse
import hashlib
import json
from pathlib import Path
import tomllib
import zipfile

ROOT = Path(__file__).resolve().parents[1]

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, default=ROOT/'dist')
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    version = tomllib.loads((ROOT/'pyproject.toml').read_text())['project']['version']
    tag = 'v' + version.replace('a', '-alpha.') if 'a' in version else 'v' + version
    # Explicit public distribution inventory; never walk private media/output trees.
    skill_files = [Path('SKILL.md'), Path('agents/openai.yaml')]
    archives = []
    for name in ('video-editing', 'tiktok'):
        skill = ROOT/'.agents/skills'/name
        archive = args.output/f'{name}-skill-{tag}.zip'
        with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED) as output:
            for relative in skill_files:
                output.write(skill/relative, Path(name)/relative)
            output.write(ROOT/'LICENSE', Path(name)/'LICENSE')
        archives.append(archive)
    plugin_archive = args.output/f'video-editing-claude-plugin-{tag}.zip'
    manifest = ROOT/'.claude-plugin/plugin.json'
    metadata = json.loads(manifest.read_text())
    if metadata['version'] != tag.removeprefix('v'):
        raise ValueError('Plugin and harness versions differ')
    with zipfile.ZipFile(plugin_archive, 'w', zipfile.ZIP_DEFLATED) as output:
        output.write(manifest, '.claude-plugin/plugin.json')
        for name in ('video-editing', 'tiktok'):
            skill = ROOT/'.agents/skills'/name
            for relative in skill_files:
                output.write(skill/relative, Path('.agents/skills')/name/relative)
        output.write(ROOT/'LICENSE', 'LICENSE')
    files = sorted(p for p in args.output.iterdir() if p.is_file() and p.suffix in ('.whl','.gz','.zip'))
    sums = args.output/'SHA256SUMS'
    sums.write_text(''.join(f'{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.name}\n' for p in files))
    for archive in archives:
        print(archive.name)
    print(plugin_archive.name)
    print(sums.name)

if __name__ == '__main__':
    main()
