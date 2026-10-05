from pathlib import Path
import hashlib,numpy as np
from .common import DATA_ROOT,read,write

def _read_cube(path):
 size=None;rows=[];domain_min=None;domain_max=None
 for line in path.read_text().splitlines():
  line=line.split('#',1)[0].strip()
  if not line:continue
  parts=line.split();key=parts[0]
  if key=='TITLE':continue
  if key=='LUT_3D_SIZE':
   if size is not None or len(parts)!=2:raise ValueError('Invalid LUT_3D_SIZE')
   try:size=int(parts[1])
   except ValueError as e:raise ValueError('Invalid LUT_3D_SIZE') from e
   if size<2:raise ValueError('Invalid LUT_3D_SIZE')
   continue
  if key in ('DOMAIN_MIN','DOMAIN_MAX'):
   if len(parts)!=4:raise ValueError(f'Invalid {key}')
   try:values=np.array([float(v) for v in parts[1:]])
   except ValueError as e:raise ValueError(f'Invalid {key}') from e
   if not np.isfinite(values).all():raise ValueError(f'Invalid {key}: values must be finite')
   if key=='DOMAIN_MIN':
    if domain_min is not None:raise ValueError('Duplicate DOMAIN_MIN')
    domain_min=values
   else:
    if domain_max is not None:raise ValueError('Duplicate DOMAIN_MAX')
    domain_max=values
   continue
  if key=='LUT_1D_SIZE' or 'INPUT_RANGE' in key:
   raise ValueError(f'Unsupported cube directive: {key}')
  try:values=[float(v) for v in parts]
  except ValueError as e:raise ValueError(f'Unsupported cube directive or invalid row: {key}') from e
  if len(values)!=3 or not np.isfinite(values).all():raise ValueError('Invalid cube rows: expected three finite values per row')
  rows.append(values)
 if domain_min is not None and not np.array_equal(domain_min,np.zeros(3)):
  raise ValueError('Custom cube input domain must be 0 0 0 to 1 1 1')
 if domain_max is not None and not np.array_equal(domain_max,np.ones(3)):
  raise ValueError('Custom cube input domain must be 0 0 0 to 1 1 1')
 if size is None or len(rows)!=size**3:raise ValueError('Invalid cube rows or missing LUT_3D_SIZE')
 return size,np.array(rows)

def build_lut(cfg,tone_name,out):
 resolved=cfg.get('_resolved')
 tone=read(DATA_ROOT/'tones'/f'{tone_name}.json') if not resolved else {'name':resolved['use_case']+' / '+resolved['style'],**resolved['base_grade']}
 n=65
 if cfg['input_color']=='apple_log':
  custom=cfg.get('apple_log_cube')
  if custom:
   base=Path(custom);n,a=_read_cube(base)
  else:
   matches=list(Path('/Applications').glob('Final Cut Pro*.app/Contents/Frameworks/Helium.framework/Versions/A/Resources/AppleLogToRec709_v1.0.3dlut'))
   if not matches:raise ValueError('Apple Log base LUT missing. Set apple_log_cube to your licensed LUT.')
   base=matches[0];raw=base.read_bytes()
   if len(raw)!=65**3*6:raise ValueError('Unknown Apple LUT binary layout')
   a=np.frombuffer(raw,dtype='>u2').reshape(-1,3).astype(float)/65535
 else:
  grid=np.linspace(0,1,n);b,g,r=np.meshgrid(grid,grid,grid,indexing='ij');a=np.stack((r,g,b),-1).reshape(-1,3);base=None
 gains=np.array(cfg.get('white_balance_gains',[1,1,1]),float)*np.array(tone['rgb_gains'])
 if gains.shape!=(3,) or not np.isfinite(gains).all() or (gains<=0).any():raise ValueError('White balance gains must be three positive finite values')
 x=a*gains;y=x@np.array([.2126,.7152,.0722]);target=np.interp(y,[0,.05,.18,.4,.65,.85,1],tone['curve'])
 x+=(target-y)[:,None];x=target[:,None]+(x-target[:,None])*tone['saturation']
 warm_mask=np.clip((a[:,0]-a[:,2])/.18,0,1)*np.clip((a[:,0]-a[:,1]+.025)/.1,0,1)
 shadows=np.clip(1-target/.65,0,1)**2;highlights=np.clip((target-.4)/.6,0,1)**1.5
 x+=shadows[:,None]*np.array(tone['shadow_tint'])*(1-.8*warm_mask[:,None])+highlights[:,None]*np.array(tone['highlight_tint'])
 if resolved:
  x=apply_style(x,resolved)
 x=np.clip(x,0,1)
 p=Path(out);p.parent.mkdir(parents=True,exist_ok=True)
 with p.open('x') as f:
  f.write(f'TITLE "{tone["name"]} ({cfg["input_color"]} to Rec709)"\nLUT_3D_SIZE {n}\nDOMAIN_MIN 0 0 0\nDOMAIN_MAX 1 1 1\n');np.savetxt(f,x,fmt='%.7f')
 write(p.with_suffix('.json'),{'tone':tone,'resolved':resolved,'input_color':cfg['input_color'],'white_balance_gains':cfg.get('white_balance_gains',[1,1,1]),'base_lut':str(base) if base else None,'base_sha256':hashlib.sha256(base.read_bytes()).hexdigest() if base else None,'combined_log_conversion':cfg['input_color']=='apple_log','warning':'Warm-color protection is heuristic, not a face/background mask.'})
 return p


def _linear(rgb):
 x=np.maximum(rgb,0)
 return np.where(x<.081,x/4.5,((x+.099)/1.099)**(1/.45))
def _encoded(rgb):
 x=np.maximum(rgb,0)
 return np.where(x<.018,x*4.5,1.099*x**.45-.099)
def _luma_change(rgb,contrast=1,midtones=0,black_lift=0,rolloff=0):
 y=rgb@np.array([.2126,.7152,.0722]);t=.4+(y-.4)*contrast
 t+=midtones*np.maximum(0,4*np.clip(y,0,1)*(1-np.clip(y,0,1)))
 t+=black_lift*np.clip(1-y,0,1)**2
 if rolloff:
  shoulder=.75+.25*(1-np.exp(-np.maximum(t-.75,0)/.25))
  t=np.where(t>.75,(1-rolloff)*t+rolloff*shoulder,t)
 return rgb+(t-y)[:,None]
def apply_style(rgb,resolved):
 g=resolved['style_grade'];a=resolved['intensity'];original=rgb.copy()
 styled=(_encoded(_linear(rgb)*2**g['exposure_stops']) if g['exposure_stops'] else rgb.copy())*np.array(g['rgb_gains'])
 styled=_luma_change(styled,g['contrast'],black_lift=g['black_lift'],rolloff=g['highlight_rolloff'])
 y=styled@np.array([.2126,.7152,.0722]);sat=0 if g['monochrome'] else g['saturation'];styled=y[:,None]+(styled-y[:,None])*sat
 warm=np.clip((original[:,0]-original[:,2])/.18,0,1)*np.clip((original[:,0]-original[:,1]+.025)/.1,0,1)
 styled+=(np.clip(1-y/.65,0,1)**2)[:,None]*np.array(g['shadow_tint'])*(1-.8*warm[:,None])
 styled+=(np.clip((y-.4)/.6,0,1)**1.5)[:,None]*np.array(g['highlight_tint'])
 x=original*(1-a)+styled*a
 adj=resolved['adjustments'];x=_encoded(_linear(x)*2**adj['exposure_stops']) if adj['exposure_stops'] else x
 x=_luma_change(x,adj['contrast'],adj['midtones'],adj['black_lift'],adj['highlight_rolloff'])
 y=x@np.array([.2126,.7152,.0722]);return y[:,None]+(x-y[:,None])*adj['saturation']
