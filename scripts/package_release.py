"""Build the portable skill archive and checksums alongside uv's wheel/sdist."""
import argparse
import hashlib
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
    skill = ROOT/'.agents/skills/video-editing'
    archive = args.output/f'video-editing-skill-{tag}.zip'
    with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED) as output:
        for path in sorted(skill.rglob('*')):
            if path.is_file() and '__pycache__' not in path.parts:
                output.write(path, Path('video-editing')/path.relative_to(skill))
        output.write(ROOT/'LICENSE', 'video-editing/LICENSE')
    files = sorted(p for p in args.output.iterdir() if p.is_file() and p.suffix in ('.whl','.gz','.zip'))
    sums = args.output/'SHA256SUMS'
    sums.write_text(''.join(f'{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.name}\n' for p in files))
    print(archive.name)
    print(sums.name)

if __name__ == '__main__':
    main()
