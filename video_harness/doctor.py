"""Read-only diagnostics for the skill checkout and local tools."""

import json
import os
from pathlib import Path
import re
import shutil

from . import __version__
from .common import ROOT

FONT_PATHS = (
    '/System/Library/Fonts/ヒラギノ角ゴシック W3.ttc',
    '/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc',
    '/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc',
)
REQUIRED_COMMANDS = ('session', 'preview', 'render', 'transcribe', 'tiktok-export')
SESSION_ACTIONS = ('start', 'status', 'cloud-policy', 'transcribe', 'transcript',
                   'plan', 'approve', 'render', 'review-page', 'feedback',
                   'package', 'finish', 'resume', 'handoff', 'revise', 'review',
                   'register-vertical', 'review-vertical', 'audition-junctions',
                   'inspect', 'delivery-check')


def _release_version(version):
    return re.sub(r'a(\d+)$', r'-alpha.\1', version)


def report():
    root = Path(ROOT)
    manifest_path = root / '.claude-plugin/plugin.json'
    manifest = json.loads(manifest_path.read_text()) if manifest_path.is_file() else None
    installed_version = _release_version(__version__)
    declared_version = manifest.get('version') if isinstance(manifest, dict) else None
    skills = {name: (root / '.agents/skills' / name / 'SKILL.md').is_file()
              for name in ('video-editing', 'tiktok', 'youtube')}
    skill_versions = {}
    for name, present in skills.items():
        if present:
            body = (root / '.agents/skills' / name / 'SKILL.md').read_text()
            match = re.search(r'v(\d+\.\d+\.\d+-alpha\.\d+)', body)
            skill_versions[name] = match.group(1) if match else None
        else:
            skill_versions[name] = None
    commands = {name: False for name in REQUIRED_COMMANDS}
    session_actions = {name: False for name in SESSION_ACTIONS}
    try:
        from .cli import parser
        from .workflow_cli import parser as session_parser
        import argparse
        for action in parser()._actions:
            if isinstance(action, argparse._SubParsersAction):
                commands = {name: name in action.choices for name in REQUIRED_COMMANDS}
                break
        for action in session_parser()._actions:
            if isinstance(action, argparse._SubParsersAction):
                session_actions = {name: name in action.choices for name in SESSION_ACTIONS}
                break
    except ImportError:
        pass
    credentials = {
        'openai': bool(os.getenv('OPENAI_API_KEY')),
        'azure': all(bool(os.getenv(key)) for key in (
            'AZURE_OPENAI_API_KEY', 'AZURE_OPENAI_ENDPOINT',
            'AZURE_OPENAI_TRANSCRIPTION_DEPLOYMENT', 'AZURE_OPENAI_TIMESTAMP_DEPLOYMENT')),
    }
    findings = []
    if declared_version and declared_version != installed_version:
        findings.append('Plugin version differs from runtime; check skill command compatibility before editing')
    if declared_version is None:
        findings.append('No local plugin manifest found; external skill version cannot be checked')
    if not all(commands.values()):
        findings.append('Runtime lacks one or more commands used by the platform skills')
    if not all(session_actions.values()):
        findings.append('Runtime lacks one or more session actions used by the platform skills')
    if not all(skills.values()):
        findings.append('One or more checkout skill folders are missing; verify VIDEO_EDIT_HARNESS_ROOT')
    for name, version in skill_versions.items():
        if version and version != installed_version:
            findings.append(f'{name} skill declares {version} while runtime is {installed_version}; check command compatibility')
    tools = {name: shutil.which(name) for name in ('ffmpeg', 'ffprobe', 'uv')}
    if not tools['ffmpeg'] or not tools['ffprobe']:
        findings.append('FFmpeg and ffprobe are required for media work')
    font = next((path for path in FONT_PATHS if Path(path).is_file()), None)
    if font is None:
        findings.append('No bundled-path CJK font found; pass --font for Japanese subtitle burn-in')
    return {
        'runtime_version': __version__, 'checkout_root': str(root),
        'plugin_version': declared_version, 'skill_paths_present': skills,
        'skill_declared_versions': skill_versions,
        'required_commands': commands, 'session_actions': session_actions,
        'tools': tools, 'cjk_font': font,
        'credentials_configured': credentials, 'free_gb': round(shutil.disk_usage(root).free / 1e9, 2),
        'findings': findings,
    }
