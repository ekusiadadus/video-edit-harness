"""Use-case corrections, composable looks, and explicit per-source adjustments."""
from copy import deepcopy
import math,re
from .common import DATA_ROOT,read
ADJUSTMENTS={'exposure_stops':(-3,3,0),'contrast':(.5,1.6,1),'midtones':(-.15,.15,0),'saturation':(0,2,1),'black_lift':(-.05,.1,0),'highlight_rolloff':(0,1,0)}

def finite(value,low,high,label):
 if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value) or not low<=value<=high:raise ValueError(f'{label} must be a finite number between {low} and {high}')
 return float(value)
def catalog(kind):
 return {p.stem:read(p) for p in sorted((DATA_ROOT/kind).glob('*.json'))}
def get(kind,name):
 if not isinstance(name,str) or not re.fullmatch('[a-z][a-z0-9_]*',name):raise ValueError(f'Invalid {kind} id')
 p=DATA_ROOT/kind/f'{name}.json'
 if not p.is_file():raise ValueError(f'Unknown {kind}: {name}')
 return read(p)
def resolve(cfg,use_case=None,style=None,intensity=None,overrides=None):
 case_id=use_case or cfg.get('use_case','indoor_talk');case=get('use_cases',case_id)
 style_id=style or cfg.get('style') or case['default_style'];look=get('styles',style_id)
 amount=intensity if intensity is not None else cfg.get('style_intensity',look['defaults']['intensity']);amount=finite(amount,0,1,'style_intensity')
 adjustments=deepcopy(cfg.get('adjustments',{}));adjustments.update(overrides or {})
 unknown=set(adjustments)-set(ADJUSTMENTS)
 if unknown:raise ValueError(f'Unknown adjustments: {sorted(unknown)}')
 adj={k:finite(adjustments.get(k,d),lo,hi,k) for k,(lo,hi,d) in ADJUSTMENTS.items()}
 base=case['grade'];curve=base['curve']
 if len(curve)!=7 or any(not isinstance(v,(int,float)) or not math.isfinite(v) or not 0<=v<=1 for v in curve) or any(a>b for a,b in zip(curve,curve[1:])):raise ValueError('Use-case curve must have 7 finite monotonic knots')
 finite(base['saturation'],0,2,'case saturation')
 for key in ['rgb_gains','shadow_tint','highlight_tint']:
  if len(base[key])!=3:raise ValueError(f'{key} requires RGB triplet')
  for v in base[key]:finite(v,.1 if key=='rgb_gains' else -.2,3 if key=='rgb_gains' else .2,key)
 grade=look['grade']
 for key,lo,hi in [('contrast',.5,1.6),('saturation',0,2),('exposure_stops',-3,3),('black_lift',-.05,.1),('highlight_rolloff',0,1)]:finite(grade[key],lo,hi,'style '+key)
 for key in ['rgb_gains','shadow_tint','highlight_tint']:
  if len(grade[key])!=3:raise ValueError('Style RGB values need 3 components')
  for v in grade[key]:finite(v,.1 if key=='rgb_gains' else -.2,3 if key=='rgb_gains' else .2,key)
 if not isinstance(grade['monochrome'],bool):raise ValueError('monochrome must be boolean')
 return {'version':2,'use_case':case_id,'style':style_id,'intensity':amount,'base_grade':deepcopy(base),'style_grade':deepcopy(grade),'adjustments':adj,'brightness_guidance':deepcopy(case['brightness_guidance']),'description':case['description'],'style_description':look['description'],'processing_order':['Apple Log conversion if needed','white balance RGB gains','use-case luma curve','style at selected intensity','per-source exposure/contrast/midtones','Rec709 output'],'limitations':['Subject/background targets are human guidance, not automatic masks.','Exposure operates after Log-to-Rec709 transform; clipped highlight detail cannot be recovered.']}
