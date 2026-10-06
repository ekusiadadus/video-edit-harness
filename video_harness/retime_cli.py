"""Source-bound local retime proposal and render commands."""
import argparse
import json
from pathlib import Path
import subprocess

from .common import read,write
from .retime import prepare_retime,render_retime,captions_srt


def main(argv=None):
    parser=argparse.ArgumentParser(prog='video-harness retime')
    commands=parser.add_subparsers(dest='command',required=True)
    prepare=commands.add_parser('prepare',help='Bind observed ramp/freeze operations to actual source frames')
    prepare.add_argument('source',type=Path);prepare.add_argument('request',type=Path)
    prepare.add_argument('--output',type=Path,required=True)
    prepare.add_argument('--actor',choices=['human','codex','claude_code','automation'],default='codex')
    prepare.add_argument('--note',required=True)
    render=commands.add_parser('render',help='Render a prepared proposal without adopting it')
    render.add_argument('source',type=Path);render.add_argument('proposal',type=Path)
    render.add_argument('--output',type=Path,required=True)
    args=parser.parse_args(argv)
    try:
        paths=[args.output] if args.command=='prepare' else [args.output,args.output.with_suffix('.retime.json'),args.output.with_suffix('.srt')]
        if any(path.exists() for path in paths):raise ValueError('Outputs must be new files')
        if args.command=='prepare':
            result=prepare_retime(args.source,read(args.request),args.actor,args.note);write(args.output,result)
        else:
            result=render_retime(args.source,read(args.proposal),args.output)
            write(args.output.with_suffix('.retime.json'),result)
            args.output.with_suffix('.srt').write_text(captions_srt(result['captions']),encoding='utf-8')
        print(json.dumps({'output':str(args.output),'output_frame_count':result['mapping']['output_frame_count'],
                          'review_required':True,'adopted':False},ensure_ascii=False,indent=2))
    except (ValueError,OSError,RuntimeError,subprocess.SubprocessError) as error:
        parser.exit(2,f'Error: {error}\n')
