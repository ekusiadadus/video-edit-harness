"""Optional fixed soft spatial luma corrections. No person segmentation/tracking."""
from .evaluate import validate_regions
from .profiles import finite

def region_filter(cfg):
 regions=cfg.get('region_corrections',[])
 if not isinstance(regions,list) or len(regions)>8:raise ValueError('region_corrections must be a list of at most 8 regions')
 terms=[]
 for r in regions:
  rect=r['rect'];validate_regions({r['name']:rect});gain=finite(r.get('luma_delta_pct',0),-20,20,'region luma_delta_pct');feather=finite(r.get('feather',.2),.05,.8,'region feather')
  x,y,w,h=rect;cx=x+w/2;cy=y+h/2
  # Width scale controls a smooth super-Gaussian correction; the rect is a reference area, not a hard crop.
  rx=w/2*(1+feather);ry=h/2*(1+feather)
  if gain:terms.append(f'{gain*219/100:.9f}*exp(-pow((X/W-{cx:.9f})/{rx:.9f},4)-pow((Y/H-{cy:.9f})/{ry:.9f},4))')
 if not terms:return ''
 expression='lum(X,Y)+'+'+'.join('('+t+')' for t in terms)
 return f",format=yuv444p,geq=lum='clip({expression},16,235)':cb='cb(X,Y)':cr='cr(X,Y)'"
