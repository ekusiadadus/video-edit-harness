"""Source-bound proposals for optically compatible hard cuts, never transitions."""
from copy import deepcopy
from fractions import Fraction
import math
from pathlib import Path
import subprocess
import numpy as np
from .common import fingerprint
from .visual import validate_visual_edl, revise_visual_edl
from .video_effects import _probe, _stream, _verified_rate
from .tracking import _box


def _integer(value, name, minimum=0):
    if type(value) is not int or value < minimum:
        raise ValueError(f'{name} must be an integer >= {minimum}')
    return value


def _window(path, first, end, info, box):
    from .motion_analysis import analyze_frames
    width=min(640,info['width']);height=max(8,round(info['height']*width/info['width']))
    raw=subprocess.check_output(['ffmpeg','-hide_banner','-nostdin','-v','error','-i',str(path),
        '-vf',f'trim=start_frame={first}:end_frame={end},scale={width}:{height}',
        '-frames:v',str(end-first),'-fps_mode','passthrough','-an','-pix_fmt','rgb24','-f','rawvideo','-'])
    if len(raw)!=(end-first)*width*height*3:
        raise ValueError('Motion window did not decode the exact source frames')
    frames=np.frombuffer(raw,np.uint8).reshape(end-first,height,width,3)
    return {'source_first_frame':first,'source_end_frame_exclusive':end,
            'source_frame_ids':list(range(first,end)),
            'analysis':analyze_frames(frames,box,info['fps'])}


def prepare_motion_cut(plan, cfg, request, actor, reason):
    """Rank explicitly supplied endpoints; return a proposed plan or no change."""
    from .motion_analysis import compare_motion
    if actor not in {'human','codex','claude_code','automation'} or not isinstance(reason,str) or not reason.strip():
        raise ValueError('Motion cut needs a real actor and reason')
    if cfg.get('edit_basis')!='visual' or cfg.get('retime') or cfg.get('audio_cuts'):
        raise ValueError('Motion cuts require a visual plan without retime or J/L cuts')
    fields={'version','left_segment_id','choices','left_box','right_box','nonspoken_intervals','window_frames'}
    if not isinstance(request,dict) or set(request)!=fields or type(request['version']) is not int or request['version']!=1:
        raise ValueError('Invalid motion-cut request')
    count=_integer(request['window_frames'],'window_frames',3)
    if count>12:
        raise ValueError('Motion windows are limited to 12 source frames')
    boxes=[_box(request['left_box']),_box(request['right_box'])]
    if not isinstance(request['choices'],list) or not 1<=len(request['choices'])<=12:
        raise ValueError('Supply 1..12 observed endpoint choices')
    plan=validate_visual_edl(plan,cfg.get('assets',[]))
    sequence=plan['sequence'];index=next((i for i,s in enumerate(sequence) if s['id']==request['left_segment_id']),None)
    if index is None or index+1>=len(sequence):
        raise ValueError('Choose an existing adjacent visual junction')
    left,right=sequence[index:index+2];registry={a['asset_id']:a for a in cfg['assets']}
    source_info={}
    for segment in (left,right):
        aid=segment['asset_id']
        if aid in source_info:continue
        asset=registry[aid];identity=fingerprint(asset['path'])
        if identity['sha256']!=asset['sha256'] or identity['bytes']!=asset['bytes']:
            raise ValueError('Motion source differs from registered asset')
        video=_stream(_probe(asset['path'],count=True),'video');frames=int(video['nb_read_frames'])
        rate=_verified_rate(asset['path'],video,frames)
        source_info[aid]={'identity':identity,'fps':str(rate),'frame_count':frames,
                          'width':int(video['width']),'height':int(video['height'])}
    intervals=request['nonspoken_intervals']
    if not isinstance(intervals,list):raise ValueError('Declare observed nonspoken source intervals')
    allowed={}
    for row in intervals:
        if not isinstance(row,dict) or set(row)!={'asset_id','first_frame','end_frame_exclusive','reason'} or row['asset_id'] not in source_info or not isinstance(row['reason'],str) or not row['reason'].strip():
            raise ValueError('Invalid observed nonspoken interval')
        first=_integer(row['first_frame'],'interval first');end=_integer(row['end_frame_exclusive'],'interval end')
        if not first<end<=source_info[row['asset_id']]['frame_count']:raise ValueError('Nonspoken interval outside actual source')
        allowed.setdefault(row['asset_id'],[]).append((first,end))
    def covered(aid,first,end):
        cursor=first
        for a,b in sorted(allowed.get(aid,[])):
            if a<=cursor<b:cursor=max(cursor,b)
            if cursor>=end:return True
        return first==end
    candidates=[];cache={};seen=set()
    for choice in request['choices']:
        if not isinstance(choice,dict) or set(choice)!={'left_end_frame','right_start_frame','reason'} or not isinstance(choice['reason'],str) or not choice['reason'].strip():
            raise ValueError('Every observed endpoint choice needs a reason')
        le=_integer(choice['left_end_frame'],'left_end_frame');rs=_integer(choice['right_start_frame'],'right_start_frame')
        if (le,rs) in seen:raise ValueError('Duplicate motion endpoint choice')
        seen.add((le,rs))
        if not left['source_first_frame']+count<=le<=source_info[left['asset_id']]['frame_count'] or not 0<=rs<=right['source_end_frame_exclusive']-count:
            raise ValueError('Motion choice has insufficient source frames or handles')
        for segment,before,after in ((left,left['source_end_frame_exclusive'],le),(right,right['source_first_frame'],rs)):
            if not covered(segment['asset_id'],min(before,after),max(before,after)):
                raise ValueError('Changed source frames require observed nonspoken permission')
        windows=[]
        for segment,first,end,box in ((left,le-count,le,boxes[0]),(right,rs,rs+count,boxes[1])):
            key=(segment['asset_id'],first,end,tuple(box))
            if key not in cache:
                info=source_info[segment['asset_id']]
                cache[key]=_window(info['identity']['path'],first,end,info,box)
            windows.append(deepcopy(cache[key]))
        match=compare_motion(windows[0]['analysis'],windows[1]['analysis'])
        candidates.append({'choice':deepcopy(choice),'left':windows[0],'right':windows[1],'match':match})
    for info in source_info.values():
        if fingerprint(info['identity']['path'])!=info['identity']:
            raise ValueError('Motion source changed during analysis')
    compatible=[c for c in candidates if c['match']['classification']=='compatible']
    selected=max(compatible,key=lambda c:c['match']['cosine']-.05*abs(math.log(c['match']['speed_ratio']))) if compatible else None
    report={'version':1,'kind':'optical_motion_cut_proposal','actor':actor,'reason':reason,
            'sources':source_info,'request':deepcopy(request),'candidates':candidates,'selected':deepcopy(selected),
            'adopted':False,'human_review':False,'transition_rendered':False,
            'limitations':['Optical movement is not action semantics or camera-motion compensation.',
                           'Declared nonspoken intervals are not speech recognition or listening proof.']}
    if selected is None:return None,report
    if selected['choice']['left_end_frame']==left['source_end_frame_exclusive'] and selected['choice']['right_start_frame']==right['source_first_frame']:
        return None,report
    choice=selected['choice'];new=deepcopy(sequence)
    for segment,key,frame in ((new[index],'source_end',choice['left_end_frame']),(new[index+1],'source_start',choice['right_start_frame'])):
        segment[key]=str(Fraction(frame,1)/Fraction(segment['source_fps']))
        for derived in ('source_fps','source_first_frame','source_end_frame_exclusive'):segment.pop(derived,None)
        segment['reason']=reason+'; '+choice['reason']
    proposed=validate_visual_edl(revise_visual_edl(plan,new,actor=actor,reason=reason),cfg['assets'])
    return proposed,report


def validate_motion_report(plan):
    """Bind attached motion evidence to this exact source-frame sequence."""
    from .common import read
    ref=plan['motion_proposal']
    if fingerprint(ref['path'])!=ref:
        raise ValueError('Motion proposal artifact changed')
    report=read(ref['path'])
    if report.get('kind')!='optical_motion_cut_proposal' or not report.get('selected'):
        raise ValueError('Attached motion report has no selected source-frame proposal')
    parent_ref=report.get('parent_plan')
    if not isinstance(parent_ref,dict) or fingerprint(parent_ref['path'])!=parent_ref:
        raise ValueError('Motion parent plan changed')
    parent=read(parent_ref['path']);expected=deepcopy(parent['sequence'])
    left_id=report['request']['left_segment_id']
    index=next((i for i,row in enumerate(expected) if row['id']==left_id),None)
    if index is None or index+1>=len(expected):
        raise ValueError('Motion evidence junction is missing')
    choice=report['selected']['choice']
    expected[index]['source_end_frame_exclusive']=choice['left_end_frame']
    expected[index+1]['source_first_frame']=choice['right_start_frame']
    keys=('id','asset_id','source_fps','source_first_frame','source_end_frame_exclusive')
    if len(expected)!=len(plan['sequence']) or any(tuple(a.get(k) for k in keys)!=tuple(b.get(k) for k in keys)
            for a,b in zip(expected,plan['sequence'])) or parent['sources']!=plan['sources']:
        raise ValueError('Motion evidence does not describe current source frames')
