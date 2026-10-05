"""Measured frame evidence, kept separate from human style/skin judgments."""
from pathlib import Path
from io import BytesIO
import json,subprocess,numpy as np
from PIL import Image
from .common import probe,write

def validate_regions(regions):
 if not isinstance(regions,dict):raise ValueError('review_regions must map names to normalized rectangles')
 for name,rect in regions.items():
  if not isinstance(name,str) or not isinstance(rect,list) or len(rect)!=4:raise ValueError('Region needs name and [x,y,w,h]')
  if any(isinstance(v,bool) or not isinstance(v,(int,float)) or not np.isfinite(v) for v in rect):raise ValueError('Nonfinite region')
  x,y,w,h=rect
  if x<0 or y<0 or w<=0 or h<=0 or x+w>1 or y+h>1:raise ValueError('Region outside normalized frame')
 return regions

def frame_metrics(rgb,regions):
 a=np.array(rgb,dtype=float)/255;y=a@np.array([.2126,.7152,.0722]);h,w=y.shape
 values={}
 for name,(x0,y0,rw,rh) in validate_regions(regions).items():
  patch=y[int(y0*h):max(int(y0*h)+1,int((y0+rh)*h)),int(x0*w):max(int(x0*w)+1,int((x0+rw)*w))]
  values[name]={'mean_luma_pct':float(patch.mean()*100),'p10_luma_pct':float(np.percentile(patch,10)*100),'p90_luma_pct':float(np.percentile(patch,90)*100)}
 delta=values['background']['mean_luma_pct']-values['subject']['mean_luma_pct'] if 'background' in values and 'subject' in values else None
 return {'mean_luma_pct':float(y.mean()*100),'p05_luma_pct':float(np.percentile(y,5)*100),'p50_luma_pct':float(np.percentile(y,50)*100),'p95_luma_pct':float(np.percentile(y,95)*100),'near_white_pct':float(np.mean(y>.98)*100),'near_black_pct':float(np.mean(y<.02)*100),'regions':values,'background_minus_subject_pct':delta}

def evaluate(path,cfg,out):
 duration=float(probe(path)['format']['duration']);regions=cfg.get('review_regions',{})
 rows=[]
 for fraction in [.1,.5,.9]:
  t=duration*fraction
  cmd=['ffmpeg','-v','error','-ss',str(t),'-i',str(path),'-frames:v','1','-vf','scale=320:-2','-f','image2pipe','-vcodec','png','-']
  r=subprocess.run(cmd,stdout=subprocess.PIPE,stderr=subprocess.PIPE,check=True)
  (out/f'measure-{fraction}.log').write_bytes(r.stderr)
  image=Image.open(BytesIO(r.stdout)).convert('RGB');rows.append({'time':t,**frame_metrics(image,regions)})
 write(out/'evaluation.json',{'technical_status':'pass','samples':rows,'units':'Rec709 decoded RGB luma 0..100 percent; not a calibrated physical IRE measurement','quality_status':'not_reviewed','limits':['No automatic face mask or tracking.','Whole-frame averages are not subject exposure.','Near-white/black pixels may be intentional; no automatic aesthetic rejection.']})
 return rows
