"""OpenCV CSRT backend for manually selected local objects.

Tracker status and template correlation are diagnostics, not identity certainty.
Any detected loss persists until an explicit observed manual correction.
"""
import math
import numpy as np

from .tracking import _box, _cv2, _gray


def track_frames_csrt(frames, initial_box, corrections=None):
    cv2 = _cv2()
    if not hasattr(cv2, 'TrackerCSRT_create'):
        raise RuntimeError('CSRT requires opencv-contrib-python; uv sync --extra tracking')
    initial = _box(initial_box)
    corrections = {} if corrections is None else corrections
    if not isinstance(corrections, dict) or any(type(k) is not int or k < 0 for k in corrections):
        raise ValueError('corrections must map nonnegative integer frames to boxes')
    corrections = {k: _box(v) for k,v in corrections.items()}
    rows=[];tracker=None;dimensions=None;template=None
    for index,frame in enumerate(frames):
        gray=_gray(frame,cv2)
        if dimensions is None:
            dimensions=gray.shape
        elif gray.shape != dimensions:
            raise ValueError('all frames must have the same dimensions')
        array=np.asarray(frame)
        if array.ndim==2:
            picture=cv2.cvtColor(gray,cv2.COLOR_GRAY2BGR)
        else:
            picture=cv2.cvtColor(array,cv2.COLOR_RGBA2BGR if array.shape[2]==4 else cv2.COLOR_RGB2BGR)
        h,w=gray.shape
        reason=None;correlation=None
        manual=index==0 or index in corrections
        if manual:
            selected=corrections.get(index,initial)
            x0,y0,x1,y1=selected
            left,top,right,bottom=round(x0*w),round(y0*h),round(x1*w),round(y1*h)
            if right-left<8 or bottom-top<8:
                reason='manual_box_too_small'
            else:
                template=gray[top:bottom,left:right].copy()
                if float(template.std())<5:
                    reason='featureless_manual_box'
                else:
                    tracker=cv2.TrackerCSRT_create()
                    tracker.init(picture,(left,top,right-left,bottom-top))
                    box=[left/w,top/h,right/w,bottom/h]
        elif tracker is None:
            reason='awaiting_manual_correction'
        else:
            ok,position=tracker.update(picture)
            if not ok or len(position)!=4 or not all(math.isfinite(v) for v in position):
                reason='tracker_update_failed'
            else:
                x,y,bw,bh=map(int,position)
                if x<0 or y<0 or bw<8 or bh<8 or x+bw>w or y+bh>h:
                    reason='out_of_frame_or_too_small'
                else:
                    sample=gray[y:y+bh,x:x+bw]
                    # CSRT can quantize or slightly resize a correct box. Check
                    # appearance within a small neighbourhood rather than
                    # destroying texture by resizing the whole candidate ROI.
                    margin_x=max(2,round(bw*.15));margin_y=max(2,round(bh*.15))
                    search=gray[max(0,y-margin_y):min(h,y+bh+margin_y),max(0,x-margin_x):min(w,x+bw+margin_x)]
                    matches=[]
                    for scale in (.9,1,1.1):
                        tw=max(8,round(template.shape[1]*scale));th=max(8,round(template.shape[0]*scale))
                        if tw<=search.shape[1] and th<=search.shape[0]:
                            reference=cv2.resize(template,(tw,th))
                            matches.append(float(cv2.matchTemplate(search,reference,cv2.TM_CCOEFF_NORMED).max()))
                    correlation=max(matches,default=-1)
                    correlation=max(-1,min(1,correlation))
                    if float(sample.std())<5 or not math.isfinite(correlation) or correlation<.15:
                        reason='appearance_mismatch'
                    else:
                        box=[x/w,y/h,(x+bw)/w,(y+bh)/h]
        if reason:
            tracker=None
            rows.append({'frame':index,'box':None,'state':'lost','quality':{'reason':reason}})
        else:
            quality={'tracker_update':True}
            if not manual:
                quality['template_correlation']=correlation
            rows.append({'frame':index,'box':box,'state':'manual' if manual else 'tracked','quality':quality})
    if not rows or any(k>=len(rows) for k in corrections):
        raise ValueError('empty frames or correction outside supplied frames')
    return rows
