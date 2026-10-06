"""Local-only tracking proposals; no detection, adoption or publication."""
import argparse
import json
from pathlib import Path
import re
import subprocess

from .tracking import track_video, validate_track


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('Duplicate JSON key')
        result[key] = value
    return result


def parser():
    p = argparse.ArgumentParser(description='Local manually seeded tracking')
    commands = p.add_subparsers(dest='command', required=True)
    a = commands.add_parser('track', help='Write a new review-required tracking artifact')
    a.add_argument('source', type=Path)
    a.add_argument('--output', type=Path, required=True)
    a.add_argument('--box', type=float, nargs=4, required=True, metavar=('X0', 'Y0', 'X1', 'Y1'))
    a.add_argument('--start-frame', type=int, default=0)
    a.add_argument('--end-frame', type=int)
    a.add_argument('--max-width', type=int, default=640)
    a.add_argument('--algorithm', choices=['lk','csrt','pose'], default='lk')
    a.add_argument('--model', type=Path, help='Explicit local MediaPipe task model for pose')
    a.add_argument('--actor',choices=['human','codex','claude_code','automation'],default='codex')
    a.add_argument('--note',default='Analyze the explicitly selected local region for an editing proposal')
    a.add_argument('--corrections-file', type=Path)
    a = commands.add_parser('validate', help='Check provenance and optionally require an interval without loss')
    a.add_argument('track', type=Path)
    a.add_argument('--source', type=Path)
    a.add_argument('--first-frame', type=int)
    a.add_argument('--end-frame', type=int)
    return p


def read_corrections(path):
    raw=json.loads(Path(path).read_text(),object_pairs_hook=_unique_object)
    if not isinstance(raw,dict) or any(not re.fullmatch('0|[1-9][0-9]*',key) for key in raw):
        raise ValueError('Corrections must map source frame numbers to normalized boxes')
    return {int(key):value for key,value in raw.items()}


def main(argv=None):
    p = parser()
    args = p.parse_args(argv)
    try:
        if args.command == 'track':
            corrections = None
            if args.corrections_file:
                corrections = read_corrections(args.corrections_file)
            result = track_video(args.source, args.box, args.output,
                                 start_frame=args.start_frame, end_frame=args.end_frame,
                                 corrections=corrections, max_width=args.max_width, algorithm=args.algorithm, model_path=args.model,
                                 actor=args.actor,reason=args.note)
            summary = validate_track(result)
        else:
            summary = validate_track(args.track, source=args.source,
                                     first_frame=args.first_frame, end_frame=args.end_frame)
        print(json.dumps(summary, ensure_ascii=False, indent=2, allow_nan=False))
    except (ValueError, OSError, RuntimeError, subprocess.SubprocessError) as exc:
        p.exit(2, f'Error: {exc}\n')


if __name__ == '__main__':
    main()
