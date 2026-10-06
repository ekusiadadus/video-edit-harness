"""Explicit local relative-depth preparation and unadopted image compositing."""
import argparse
import json
from pathlib import Path
import subprocess

from .common import read, write, fingerprint
from .depth_artifact import prepare_manual_depth, validate_depth
from .runs import evidence_run


def _fields(request_path):
    request = read(request_path)
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
        fields[row['frame']] = path if path.is_absolute() else request_path.resolve().parent/path
    return fields


def main(argv=None):
    parser = argparse.ArgumentParser(prog='video-harness depth')
    commands = parser.add_subparsers(dest='command', required=True)
    prepare = commands.add_parser('prepare', help='Copy explicitly normalized per-frame float32 NPY fields')
    prepare.add_argument('source', type=Path)
    prepare.add_argument('request', type=Path)
    correct = commands.add_parser('correct', help='Retain original depth and revise explicitly selected frame fields')
    correct.add_argument('manifest', type=Path)
    correct.add_argument('request', type=Path)
    stabilize = commands.add_parser('stabilize', help='Prepare opt-in motion-compensated depth with cut and confidence resets')
    stabilize.add_argument('manifest', type=Path)
    stabilize.add_argument('--strength', type=float, default=.5)
    stabilize.add_argument('--fb-tolerance', type=float, default=1.)
    stabilize.add_argument('--photometric-tolerance', type=float, default=.08)
    stabilize.add_argument('--min-coverage', type=float, default=.5)
    stabilize.add_argument('--cut-frame', type=int, action='append', default=[],
                           help='Source frame starting a new shot; repeat for every known cut')
    validate = commands.add_parser('validate', help='Recheck retained source and depth bindings')
    validate.add_argument('manifest', type=Path)
    inspect = commands.add_parser('inspect-model', help='Verify a local pinned Small model without loading weights')
    inspect.add_argument('model', type=Path)
    fetch = commands.add_parser('fetch-model', help='Explicitly download a trusted pinned official Small snapshot')
    fetch.add_argument('--output', type=Path, required=True)
    infer = commands.add_parser('infer', help='Infer relative depth locally; retain raw fields and shared interval normalization')
    infer.add_argument('source', type=Path)
    infer.add_argument('--model', type=Path, required=True)
    infer.add_argument('--first-frame', type=int, required=True)
    infer.add_argument('--end-frame-exclusive', type=int, required=True)
    render = commands.add_parser('render', help='Place a registered same-size RGBA image behind near picture content')
    render.add_argument('source', type=Path)
    render.add_argument('manifest', type=Path)
    render.add_argument('--asset', type=Path, required=True)
    render.add_argument('--policy', type=Path, required=True)
    render.add_argument('--input-color', choices=['rec709'], required=True)
    for name, default in [('threshold', .5), ('softness', .1), ('strength', 1.)]:
        render.add_argument('--'+name, type=float, default=default)
    for command in (prepare, render, infer, correct, stabilize):
        command.add_argument('--output', type=Path, required=True, help='New evidence directory')
        command.add_argument('--actor', choices=['human','codex','claude_code','automation'], required=True)
        command.add_argument('--note', required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == 'fetch-model':
            from .depth_model import fetch_model
            print(json.dumps(fetch_model(args.output), ensure_ascii=False, indent=2))
            return
        if args.command == 'inspect-model':
            from .depth_model import inspect_model
            print(json.dumps(inspect_model(args.model), ensure_ascii=False, indent=2))
            return
        if args.command == 'validate':
            doc = validate_depth(args.manifest)
            print(json.dumps({'source': doc['source'], 'frames': len(doc['rows']),
                              'review_required': True, 'adopted': False}, indent=2))
            return
        parent_binding = None
        if args.command in ('correct', 'stabilize'):
            parent_binding = fingerprint(args.manifest)
            original = validate_depth(args.manifest)
            cfg = {'source':original['source']['path']}
        else:
            cfg = {'source': str(args.source.resolve())}
        if args.command == 'render':
            cfg['input_color'] = args.input_color
        with evidence_run(cfg, 'depth-'+args.command, args.output, {'actor':args.actor,'reason':args.note}):
            if args.command == 'prepare':
                fields = _fields(args.request)
                manifest = prepare_manual_depth(args.source, fields, args.output/'fields', args.actor, args.note)
                result = {'manifest':str(manifest), 'review_required':True, 'adopted':False}
            elif args.command == 'correct':
                from .depth_artifact import correct_depth
                manifest = correct_depth(args.manifest, _fields(args.request), args.output/'fields', args.actor, args.note)
                if fingerprint(args.manifest) != parent_binding:
                    raise ValueError('Original depth changed during CLI correction')
                result = {'manifest':str(manifest), 'parent':parent_binding, 'review_required':True, 'adopted':False}
            elif args.command == 'stabilize':
                from .depth_temporal import stabilize_depth
                manifest = stabilize_depth(args.manifest, args.output/'fields', args.actor, args.note,
                    strength=args.strength, fb_tolerance=args.fb_tolerance,
                    photometric_tolerance=args.photometric_tolerance, min_coverage=args.min_coverage,
                    cut_frames=args.cut_frame)
                if fingerprint(args.manifest) != parent_binding:
                    raise ValueError('Original depth changed during CLI stabilization')
                result = {'manifest':str(manifest), 'parent':parent_binding,
                          'review_required':True, 'adopted':False,
                          'temporal_consistency_verified':False, 'metric_distance':False}
            elif args.command == 'infer':
                from .depth_inference import infer_depth
                manifest = infer_depth(args.source, args.model, args.first_frame, args.end_frame_exclusive,
                                       args.output/'depth', args.actor, args.note)
                result = {'manifest':str(manifest), 'review_required':True, 'adopted':False,
                          'temporal_consistency':False, 'metric_distance':False}
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
