"""Local pattern, registry and timeline placement operations."""
import argparse
import json
from pathlib import Path

from .common import read, write


def main(argv=None):
    parser = argparse.ArgumentParser(prog='video-harness production')
    sub = parser.add_subparsers(dest='action', required=True)
    cmd = sub.add_parser('resolve', help='Resolve editing direction without rendering')
    cmd.add_argument('project', type=Path)
    cmd = sub.add_parser('register', help='Register a local asset and supplied rights evidence')
    cmd.add_argument('source', type=Path)
    cmd.add_argument('--metadata', type=Path, required=True)
    cmd.add_argument('--output', type=Path, required=True)
    cmd = sub.add_parser('validate', help='Check current bytes and operation-specific rights')
    cmd.add_argument('asset', type=Path)
    cmd.add_argument('--policy', type=Path, required=True)
    cmd.add_argument('--operation', choices=('embedded_use', 'mixed_audio_handoff', 'raw_asset_handoff'), default='embedded_use')
    cmd = sub.add_parser('select', help='Rank eligible registered assets')
    cmd.add_argument('catalog', type=Path)
    cmd.add_argument('--policy', type=Path, required=True)
    cmd.add_argument('--request', type=Path, required=True)
    cmd = sub.add_parser('cues', help='Resolve additions against an exact rendered frame mapping')
    cmd.add_argument('project', type=Path)
    cmd.add_argument('mapping', type=Path)
    cmd.add_argument('--output', type=Path, required=True)
    cmd = sub.add_parser('search', help='Opt-in official Pexels metadata search; no source upload')
    cmd.add_argument('query', help='Explicit public search terms only')
    cmd.add_argument('--kind', choices=('image', 'video'), required=True)
    cmd.add_argument('--policy', type=Path, required=True)
    cmd.add_argument('--output', type=Path, required=True)
    cmd = sub.add_parser('fetch', help='Separately permitted download of one selected Pexels candidate')
    cmd.add_argument('candidate', type=Path, help='Single candidate JSON from search results')
    cmd.add_argument('--policy', type=Path, required=True)
    cmd.add_argument('--folder', type=Path, required=True)
    cmd.add_argument('--output', type=Path, required=True, help='Receipt; does not establish license approval')
    cmd = sub.add_parser('trend', help='Inspect an immutable observation and its expiry')
    cmd.add_argument('id')
    cmd.add_argument('--root', type=Path)
    cmd = sub.add_parser('import-trend', help='Save a new immutable researched observation')
    cmd.add_argument('profile', type=Path)
    cmd.add_argument('--root', type=Path, required=True)
    cmd = sub.add_parser('beats', help='Analyze music locally; no transcription or upload')
    cmd.add_argument('source', type=Path)
    mode = cmd.add_mutually_exclusive_group()
    mode.add_argument('--bpm', type=float)
    mode.add_argument('--manual-beats-file', type=Path)
    mode.add_argument('--librosa', action='store_true')
    cmd.add_argument('--output', type=Path, required=True)
    cmd = sub.add_parser('map-beats', help='Map one exact music source through its production cues')
    cmd.add_argument('production', type=Path)
    cmd.add_argument('beat_map', type=Path)
    cmd.add_argument('--asset-id', required=True)
    cmd.add_argument('--fps', required=True)
    cmd.add_argument('--protected-ranges-file', type=Path)
    cmd.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.action == 'resolve':
            from .patterns import resolve_pattern, resolve_asset_policy
            cfg = read(args.project)
            result = {'pattern': resolve_pattern(cfg), 'policy': resolve_asset_policy(cfg)}
        elif args.action == 'register':
            from .assets import register_asset
            result = register_asset(args.source, read(args.metadata))
        elif args.action == 'validate':
            from .assets import validate_asset
            result = validate_asset(read(args.asset), read(args.policy), args.operation)
        elif args.action == 'select':
            from .assets import rank_assets
            result = rank_assets(read(args.catalog), read(args.request), read(args.policy))
        elif args.action == 'cues':
            from .production import resolve_production
            result = resolve_production(read(args.project), read(args.mapping))
        elif args.action == 'search':
            from .asset_providers import search_pexels, official_transport
            result = {'provider': 'pexels', 'provider_url': 'https://www.pexels.com',
                      'query': args.query, 'kind': args.kind,
                      'candidates': search_pexels(args.query, args.kind, read(args.policy), official_transport),
                      'rights_status': 'unknown_until_asset_specific_review'}
        elif args.action == 'fetch':
            from .asset_providers import download_pexels, official_transport
            from .common import fingerprint
            candidate = read(args.candidate)
            path = download_pexels(candidate, args.folder, read(args.policy), official_transport)
            result = {'provider': 'pexels', 'provider_url': 'https://www.pexels.com',
                      'candidate': candidate, 'file': fingerprint(path),
                      'rights_status': 'unknown_until_asset_specific_review',
                      'next': 'Review asset-specific conditions and register with rights evidence'}
        elif args.action == 'trend':
            from .trends import load_trend_profile
            result = load_trend_profile(args.id, root=args.root)
        elif args.action == 'import-trend':
            from .trends import import_trend_profile
            result = import_trend_profile(args.root, read(args.profile))
        elif args.action == 'beats':
            from .beats import analyze_beats
            result = analyze_beats(args.source, manual_bpm=args.bpm,
                                   manual_beats=read(args.manual_beats_file) if args.manual_beats_file else None,
                                   use_librosa=args.librosa)
        else:
            from .beats import map_beats
            from .production import verify_production
            from .common import fingerprint
            production = verify_production(read(args.production))
            beat_map = read(args.beat_map)
            asset = next((a for a in production['assets'] if a['asset_id'] == args.asset_id), None)
            if not asset or beat_map.get('source_sha256') != asset['sha256'] or fingerprint(beat_map['source'])['sha256'] != asset['sha256']:
                raise ValueError('Beat map must name the exact registered music SHA')
            cues = [c for c in production['cues'] if c.get('asset_id') == args.asset_id and c['role'] in ('music', 'sfx')]
            result = map_beats(beat_map, cues, args.fps,
                               protected_intervals=read(args.protected_ranges_file) if args.protected_ranges_file else ())
        if getattr(args, 'output', None):
            write(args.output, result)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return result
    except (ValueError, OSError, KeyError, TypeError) as exc:
        parser.error(str(exc))
