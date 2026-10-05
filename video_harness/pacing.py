import math,re
from .common import fingerprint,probe,run,write

def silence_intervals(log,duration):
 events=re.findall(r'silence_(start|end):\s*(-?\d+(?:\.\d+)?)',log);result=[];start=None
 for kind,value in events:
  t=max(0,min(duration,float(value)))
  if kind=='start':start=t
  elif start is not None:
   if t>start:result.append((start,t))
   start=None
 if start is not None and duration>start:result.append((start,duration))
 return result

def candidates(intervals,cfg):
 p=cfg['pacing'];cuts=[]
 for s,e in intervals:
  a=s+float(p['keep_after']);b=e-float(p['keep_before'])
  if b-a>=float(p['minimum_cut']):cuts.append({'id':len(cuts)+1,'start':round(a,6),'end':round(b,6),'enabled':False,'reason':'低音量区間。発話・呼吸・意味の確認が必要。'})
 return cuts

def keep_intervals(plan):
 duration=float(plan['duration']);last=0.;keep=[]
 if not math.isfinite(duration) or duration<=0:raise ValueError('Invalid duration')
 for c in sorted((x for x in plan['cuts'] if x.get('enabled') is True),key=lambda x:float(x['start'])):
  s,e=float(c['start']),float(c['end'])
  if not all(math.isfinite(v) for v in (s,e)) or not (last<=s<e<=duration):raise ValueError('Cuts overlap or exceed source duration')
  if s>last:keep.append((last,s))
  last=e
 if last<duration:keep.append((last,duration))
 if not keep:raise ValueError('Cannot remove entire source')
 return keep

def analyze(cfg,out):
 src=cfg['source'];j=probe(src)
 if not any(s['codec_type']=='audio' for s in j['streams']):raise ValueError('No audio stream')
 duration=float(j['format']['duration']);p=cfg['pacing']
 log=run(['ffmpeg','-hide_banner','-nostdin','-i',src,'-map','0:a:0','-af',f"silencedetect=noise={float(p['silence_db'])}dB:d={float(p['minimum_silence'])}",'-f','null','-'],out/'silence.log')
 cuts=candidates(silence_intervals(log,duration),cfg)
 plan={'version':1,'source':fingerprint(src),'duration':duration,'cuts':cuts,'pacing':p,'status':'review_required','note':'enabledをtrueにしたカットだけXMLに反映。無音は言葉の意味や呼吸を判定しない。既存の編集済みXMLには自動適用しない。'}
 write(out/'cut-plan.json',plan);return plan
