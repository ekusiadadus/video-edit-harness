"""Explicit local relative-depth preparation and unadopted image compositing."""
import argparse
import json
from pathlib import Path
import subprocess

from .common import read, write
from .depth_artifact import prepare_manual_depth, validate_depth
from .runs import evidence_run


def main(argv=None):
    parser = argparse.ArgumentParser(prog='video-harness depth')
    commands = parser.add_subparsers(dest='command', required=True)
    prepare = commands.add_parser('prepare', help='Copy explicitly normalized per-frame float32 NPY fields')
    prepare.add_argument('source', type=Path)
    prepare.add_argument('request', type=Path)
    validate = commands.add_parser('validate', help='Recheck retained source and depth bindings')
    validate.add_argument('manifest', type=Path)
    render = commands.add_parser('render', help='Place a registered same-size RGBA image behind near picture content')
    render.add_argument('source', type=Path)
    render.add_argument('manifest', type=Path)
    render.add_argument('--asset', type=Path, required=True)
    render.add_argument('--policy', type=Path, required=True)
    render.add_argument('--input-color', choices=['rec709'], required=True)
    for name, default in [('threshold', .5), ('softness', .1), ('strength', 1.)]:
        render.add_argument('--'+name, type=float, default=default)
    for command in (prepare, render):
        command.add_argument('--output', type=Path, required=True, help='New evidence directory')
        command.add_argument('--actor', choices=['human','codex','claude_code','automation'], required=True)
        command.add_argument('--note', required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == 'validate':
            doc = validate_depth(args.manifest)
            print(json.dumps({'source': doc['source'], 'frames': len(doc['rows']),
                              'review_required': True, 'adopted': False}, indent=2))
            return
        cfg = {'source': str(args.source.resolve())}
        if args.command == 'render':
            cfg['input_color'] = args.input_color
        with evidence_run(cfg, 'depth-'+args.command, args.output, {'actor':args.actor,'reason':args.note}):
            if args.command == 'prepare':
                request = read(args.request)
                if (not isinstance(request, dict) or set(request) != {'version','fields'}
                        or type(request['version']) is not int or request['version'] != 1
                        or not isinstance(request['fields'], list) or not request['fields']):
                    raise ValueError('Expected version 1 with explicit frame/path fields')
                fields = {}
                for row in request['fields']:
                    if (not isinstance(row, dict) or set(row) != {'frame','path'}
                            or type(row['frame']) is not int or row['frame'] in fields
                            or not isinstance(row['path'], str) or not row['path']):
                        raise ValueError('Invalid or duplicate depth field request')
                    path = Path(row['path']).expanduser()
                    fields[row['frame']] = path if path.is_absolute() else args.request.resolve().parent/path
                manifest = prepare_manual_depth(args.source, fields, args.output/'fields', args.actor, args.note)
                result = {'manifest':str(manifest), 'review_required':True, 'adopted':False}
            else:
                from .depth_render import render_depth_layer
                result = render_depth_layer(args.source, args.manifest, read(args.asset), read(args.policy),
                                            args.output/'video.mp4', input_color=args.input_color,
                                            threshold=args.threshold, softness=args.softness,
                                            strength=args.strength, actor=args.actor, reason=args.note)
                write(args.output/'depth-render.json', result)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except (ValueError, OSError, RuntimeError, subprocess.SubprocessError) as error:
        parser.exit(2, f'Error: {error}\n')
