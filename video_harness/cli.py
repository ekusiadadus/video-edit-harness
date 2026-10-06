import argparse,json,shutil,subprocess
from pathlib import Path
from copy import deepcopy
from .common import ROOT,project,probe,read,write,fingerprint
from .color import build_lut
from .pacing import analyze,keep_intervals
from .media import render,verify
from .profiles import resolve,catalog,ADJUSTMENTS,get
from .runs import evidence_run,unique_id,review
from .evaluate import evaluate,validate_regions
from . import __version__
LEGACY_TONES=['clean_natural','soft_warm','subtle_cinema']

def parser():
 p=argparse.ArgumentParser(description='Use-case × style video editing harness');p.add_argument('--version',action='version',version=__version__);s=p.add_subparsers(dest='cmd',required=True)
 s.add_parser('session',help='Durable transcript-backed editing session; use session --help')
 s.add_parser('production',help='Editing patterns and local asset rights; use production --help')
 s.add_parser('tiktok-api',help='Official TikTok OAuth and read-only Display API; use tiktok-api --help')
 s.add_parser('effects-catalog',help='Versioned controls for parameterized local video effects')
 s.add_parser('tracking',help='Local subject tracking proposals; use tracking --help')
 s.add_parser('retime',help='Source-bound speed ramps and holds; use retime --help')
 for name in ['doctor','presets']:s.add_parser(name)
 for name in ['inspect','preview','compare','render','plan','resolve']:
  a=s.add_parser(name);a.add_argument('project',type=Path);a.add_argument('--output',type=Path)
  if name in ['preview','compare','render','resolve']:
   a.add_argument('--use-case');a.add_argument('--style');a.add_argument('--style-intensity',type=float)
   for key in ADJUSTMENTS:a.add_argument('--'+key.replace('_','-'),dest=key,type=float)
  if name=='render':a.add_argument('--baseline',type=Path,help='Reuse an adopted frozen profile with this project source')
  if name in ['preview','render']:a.add_argument('--tone',choices=LEGACY_TONES,help='Legacy v1 tone (compatibility)')
  if name in ['preview','compare']:a.add_argument('--styles',help='Comma-separated style IDs')
  if name=='compare':a.add_argument('--use-cases',required=True,help='Comma-separated use-case IDs')
 a=s.add_parser('tiktok-export',help='Local 1080x1920 derivative of an already graded Rec.709 edit');a.add_argument('source',type=Path);a.add_argument('--output',type=Path,required=True);a.add_argument('--framing',choices=['fit','center_crop'],default='fit');a.add_argument('--subtitles',type=Path);a.add_argument('--font',type=Path)
 a=s.add_parser('inspect-xml');a.add_argument('xml',type=Path);a.add_argument('--output',type=Path)
 a=s.add_parser('export-xml');a.add_argument('plan',type=Path);a.add_argument('output',type=Path);a.add_argument('--name',default='Talk Pacing Review')
 a=s.add_parser('verify');a.add_argument('video',type=Path);a.add_argument('--output',type=Path,required=True)
 a.add_argument('--require-audio',action='store_true');a.add_argument('--expected-audio-range',nargs=2,type=float,metavar=('START','END'))
 a=s.add_parser('transcribe');a.add_argument('project',type=Path);a.add_argument('--output',type=Path);a.add_argument('--provider',choices=['auto','openai','azure']);a.add_argument('--model');a.add_argument('--language')
 a=s.add_parser('edit-plan');a.add_argument('project',type=Path);a.add_argument('transcript',type=Path);a.add_argument('--output',type=Path)
 a=s.add_parser('revise-plan');a.add_argument('plan',type=Path);a.add_argument('output',type=Path);a.add_argument('--enable',default='');a.add_argument('--disable',default='');a.add_argument('--note',required=True)
 for cmd in ['edit-preview','edit-render','edit-export','audition']:
  a=s.add_parser(cmd);a.add_argument('project',type=Path);a.add_argument('plan',type=Path);a.add_argument('--output',type=Path)
  if cmd=='audition':a.add_argument('--cut-ids');a.add_argument('--context',type=float,default=1.5)
 a=s.add_parser('check-fcp');a.add_argument('reference',type=Path);a.add_argument('returned',type=Path);a.add_argument('--project-name');a.add_argument('--output',type=Path,required=True)
 for cmd in ['review','adopt']:
  a=s.add_parser(cmd);a.add_argument('run',type=Path);a.add_argument('--candidate',required=True);a.add_argument('--note',required=True)
  if cmd=='review':a.add_argument('--decision',choices=['accept','reject'],required=True)
 return p

def gallery(out,candidates):
 import html
 cards=[]
 for key in candidates:
  resolved=read(out/key/'resolved.json');metrics=read(out/key/'evaluation.json');sample=metrics['samples'][1]
  title=f"{resolved.get('use_case','legacy')} / {resolved.get('style',key)}"
  display={'exposure_stops':resolved.get('adjustments',{}).get('exposure_stops',0),'contrast':resolved.get('adjustments',{}).get('contrast',1),'intensity':resolved.get('intensity',1),'midpoint_luma_pct':round(sample['mean_luma_pct'],1),'background_minus_subject_pct':sample['background_minus_subject_pct']}
  audio_link = f'<a href="{key}/audio-only.mp3">音声のみ</a> · ' if (out/key/'audio-only.mp3').exists() else '音声なし · '
  cards.append(f'<article><h2>{html.escape(title)}</h2><video controls preload="none" poster="{key}/poster.jpg" src="{key}/video.mp4"></video><p>{audio_link} <a href="{key}/resolved.json">設定</a> · <a href="{key}/evaluation.json">測定</a></p><pre>{html.escape(json.dumps(display,ensure_ascii=False,indent=2))}</pre></article>')
 (out/'index.html').write_text('<!doctype html><html lang="ja"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>Video Harness Comparison</title><style>body{background:#151515;color:#eee;font:15px system-ui;padding:24px}main{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:20px}video{width:100%;max-height:60vh}h2{font-size:18px}a{color:#cfdfff}pre{font-size:12px;overflow:auto}</style><h1>用途 × スタイルの比較</h1><p>同じ素材・区間・音声で比較。技術検証と見た目の採用判断は別に記録します。</p><main>'+''.join(cards)+'</main></html>')

def candidate_profiles(cfg,args,overrides):
 baseline=getattr(args,'baseline',None)
 if baseline:
  if overrides or args.style or args.use_case or args.style_intensity is not None or getattr(args,'tone',None):raise ValueError('Frozen baseline cannot be combined with profile overrides')
  adopted=read(baseline)
  if adopted.get('decision')!='accept' or not adopted.get('review') or adopted['review'].get('decision')!='accept':raise ValueError('Expected an adopted baseline with acceptance evidence')
  r=adopted['resolved']
  if r.get('version')!=2:raise ValueError('Baseline needs v2 resolved profile')
  key=r['use_case']+'--'+r['style']
  return [(key,r)],[key],None,baseline
 cases=args.use_cases.split(',') if args.cmd=='compare' else [args.use_case or cfg.get('use_case','indoor_talk')]
 variants=[]
 for case in cases:
  styles=args.styles.split(',') if getattr(args,'styles',None) else [args.style] if args.style else list(dict.fromkeys([cfg.get('style') or get('use_cases',case)['default_style']]+get('use_cases',case)['compare_styles'])) if args.cmd=='preview' else get('use_cases',case)['compare_styles'] if args.cmd=='compare' else [cfg.get('style') or get('use_cases',case)['default_style']]
  for style in styles:
   r=resolve(cfg,case,style,args.style_intensity,overrides);variants.append((case+'--'+style,r))
 legacy=getattr(args,'tone',None)
 if legacy:
  if overrides or args.style or args.use_case or args.style_intensity is not None or getattr(args,'styles',None):raise ValueError('Legacy --tone cannot be combined with use-case/style adjustments')
  variants=[('legacy--'+legacy,{'legacy_tone':legacy})]
 if len(variants)>12:raise ValueError('At most 12 candidates per comparison. Narrow use-cases/styles.')
 keys=[key for key,_ in variants]
 if len(keys)!=len(set(keys)):raise ValueError('Duplicate use-case/style combination')
 return variants,keys,legacy,baseline

def main():
 import sys
 if len(sys.argv)>1 and sys.argv[1]=='tracking':
  from .tracking_cli import main as tracking_main
  return tracking_main(sys.argv[2:])
 if len(sys.argv)>1 and sys.argv[1]=='retime':
  from .retime_cli import main as retime_main
  return retime_main(sys.argv[2:])
 if len(sys.argv)>1 and sys.argv[1]=='tiktok-api':
  from .tiktok_cli import main as tiktok_main
  return tiktok_main(sys.argv[2:])
 if len(sys.argv)>1 and sys.argv[1]=='production':
  from .production_cli import main as production_main
  return production_main(sys.argv[2:])
 if len(sys.argv)>1 and sys.argv[1]=='session':
  from .workflow_cli import main as session_main
  return session_main(sys.argv[2:])
 p=parser();args=p.parse_args()
 try:
  if args.cmd=='effects-catalog':
   from .effect_catalog import catalog as effects_catalog
   print(json.dumps(effects_catalog(),ensure_ascii=False,indent=2));return
  if args.cmd=='tiktok-export':
   from .vertical import export_vertical
   print(json.dumps(export_vertical(args.source,args.output,args.framing,args.subtitles,args.font),ensure_ascii=False,indent=2));return
  if args.cmd in ['doctor','presets']:
   result={'use_cases':catalog('use_cases'),'styles':catalog('styles')}
   if args.cmd=='doctor':
    from .doctor import report
    result=report()|{'use_cases':list(result['use_cases']),'styles':list(result['styles'])}
   print(json.dumps(result,ensure_ascii=False,indent=2));return
  if args.cmd in ['review','adopt']:
   print(review(args.run,args.candidate,getattr(args,'decision','accept'),args.note,args.cmd=='adopt'));return
  if args.cmd=='inspect-xml':
   from .fcp import inspect_xml
   result=inspect_xml(args.xml)
   if args.output:write(args.output,result)
   print(json.dumps(result,ensure_ascii=False,indent=2));return
  if args.cmd=='export-xml':
   from .fcp import export_timeline
   plan=read(args.plan);src=Path(plan['source']['path']);current=fingerprint(src)
   if current!=plan['source']:raise ValueError('Source changed since cut plan. Re-analyze.')
   keeps=keep_intervals(plan);result=export_timeline(src,probe(src),keeps,args.output,args.name)
   write(args.output.with_suffix('.manifest.json'),{'source':current,'keep':keeps,'result':result,'cuts_enabled':sum(x.get('enabled') is True for x in plan['cuts']),'note':'Natural source audio; apply combined LUT in FCP; normalize final mix after editing.'});print(args.output);return
  if args.cmd=='verify':verify(args.video,args.output,require_audio=args.require_audio,expected_audio_range=args.expected_audio_range);print('decode + color tags + track coverage PASS');return
  if args.cmd=='check-fcp':
   from .fcp_check import compare_roundtrip
   result=compare_roundtrip(args.reference,args.returned,args.output,args.project_name)
   if result['status']!='pass':raise ValueError(f'FCP timeline differs; see {args.output / "roundtrip.json"}')
   print(args.output/'roundtrip.json');return
  if args.cmd=='revise-plan':
   from .editing import revise_plan
   ids=lambda text:[] if not text else [int(x.strip()) for x in text.split(',')]
   print(revise_plan(args.plan,args.output,ids(args.enable),ids(args.disable),args.note));return
  cfg=project(args.project);out=(args.output or ROOT/'output'/f"{cfg['name']}-{args.cmd}-{unique_id()}").resolve()
  if args.cmd=='transcribe':
   from .transcription_router import transcribe
   print(transcribe(cfg,out,args.provider,args.model,args.language));return
  if args.cmd=='edit-plan':
   from .transcript import load_transcript
   from .edl import build_plan
   from .pacing import silence_intervals
   transcript=load_transcript(args.transcript,cfg['source'])
   with evidence_run(cfg,'edit-plan',out,{'transcript_sha256':fingerprint(args.transcript)['sha256']}):
    analyze(cfg,out)
    intervals=silence_intervals((out/'silence.log').read_text(),transcript['duration'])
    plan=build_plan(cfg,transcript,intervals);write(out/'plan.json',plan)
    (out/'plan-review.txt').write_text('\n'.join(f"{c['id']}: {c['start']:.3f}–{c['end']:.3f}s | {''.join(c['previous_words'])} → {''.join(c['next_words'])} | {c['reason']}" for c in plan['cuts']))
   print(out/'plan.json');return
  if args.cmd in ['edit-preview','edit-render','edit-export','audition']:
   from .editing import render_edit,export_edit,audition
   from .edl import validate_plan
   plan=read(args.plan);validate_plan(plan,verify_source=True)
   if args.cmd in ['edit-preview','edit-render']:print(render_edit(cfg,plan,out,args.cmd=='edit-preview'));return
   with evidence_run(cfg,args.cmd,out,{'plan_sha256':fingerprint(args.plan)['sha256']}):
    if args.cmd=='edit-export':
     export_edit(cfg,plan,out)
     cfg['_resolved']=resolve(cfg);build_lut(cfg,None,out/'look.cube')
     from .fcp_check import validate_dtd
     write(out/'dtd-verification.json',validate_dtd(out/'timeline.fcpxml',out/'dtd.log'))
    else:audition(cfg,plan,out/'junctions',None if not args.cut_ids else [int(x.strip()) for x in args.cut_ids.split(',')],args.context)
   print(out);return
  if args.cmd=='inspect':
   j=probe(cfg['source']);write(out/'probe.json',j);print(out/'probe.json');return
  if args.cmd=='plan':
   out.mkdir(parents=True,exist_ok=False);plan=analyze(cfg,out);print(f"{len(plan['cuts'])} candidates, disabled until review: {out/'cut-plan.json'}");return
  overrides={k:getattr(args,k) for k in ADJUSTMENTS if getattr(args,k,None) is not None}
  variants,keys,legacy,baseline=candidate_profiles(cfg,args,overrides)
  if args.cmd=='resolve':
   for key,r in variants:write(out/f'{key}.json',r)
   print(out);return
  validate_regions(cfg.get('review_regions',{}))
  from .regions import region_filter
  region_filter(cfg) # validate before rendering anything
  duration=float(probe(cfg['source'])['format']['duration']);start=0;is_preview=args.cmd in ['preview','compare']
  if is_preview:start=float(cfg['preview']['start']);duration=min(float(cfg['preview']['duration']),duration-start)
  if start<0 or duration<=0:raise ValueError('Invalid preview range')
  # Conservative capacity guard; no source copies or full-run render on low free space.
  reserve=256*1024**2;estimated=duration*len(variants)*(1_500_000 if not is_preview else 500_000)
  volume=out.parent
  while not volume.exists():volume=volume.parent
  if shutil.disk_usage(volume).free<reserve+estimated:raise ValueError('Not enough free disk for estimated run + 256MiB reserve. Shorten preview or choose an external output volume.')
  conditions={'start':start,'duration':duration,'preview':is_preview,'candidate_ids':keys,'resolved_profiles':{key:r for key,r in variants},'baseline':str(baseline.resolve()) if baseline else None,'region_corrections':cfg.get('region_corrections',[]),'review_regions':cfg.get('review_regions',{})}
  with evidence_run(cfg,args.cmd,out,conditions):
   write(out/'project.json',cfg);write(out/'candidates.json',keys)
   for key,r in variants:
    c=deepcopy(cfg);c['_resolved']=r if not legacy else None
    tone=legacy or 'clean_natural';lut=build_lut(c,tone,out/'luts'/f'{key}.cube')
    path=render(c,lut,out/key,start,duration,is_preview);write(out/key/'resolved.json',r);evaluate(path,c,out/key)
   gallery(out,keys)
  print(out)
 except (ValueError,FileNotFoundError,FileExistsError,subprocess.CalledProcessError) as e:p.exit(2,f'Error: {e}\n')
if __name__=='__main__':main()
