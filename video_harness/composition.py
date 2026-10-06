"""Frame-bound fixed or observed tracked regions; no identity is inferred."""
from fractions import Fraction
import math
from pathlib import Path


def rectangle(value):
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        raise ValueError('Region rectangle requires four normalized coordinates')
    if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in value):
        raise ValueError('Region coordinates must be finite numbers')
    x0,y0,x1,y1 = map(float,value)
    if not 0 <= x0 < x1 <= 1 or not 0 <= y0 < y1 <= 1:
        raise ValueError('Region rectangle must be inside the frame')
    return [x0,y0,x1,y1]


def overlap(first, second):
    a,b=rectangle(first),rectangle(second)
    return max(0,min(a[2],b[2])-max(a[0],b[0])) * max(0,min(a[3],b[3])-max(a[1],b[1]))


def resolve_guides(guides, mapping):
    from .video_effects import _mapping_shape,_time,_frame,_digest
    rate,count=_mapping_shape(mapping)
    if not isinstance(guides,list):
        raise ValueError('composition_guides must be an array')
    result=[];seen=set()
    required={'id','kind','output_start','output_end','reason'}
    for row in guides:
        if not isinstance(row,dict) or not required <= set(row) or set(row)-required-{'rect','track_path','track_sha256'}:
            raise ValueError('Guide needs id, kind, rectangle, output interval and reason')
        if ('rect' in row)==('track_path' in row) or ('track_sha256' in row and 'track_path' not in row):
            raise ValueError('Guide requires either rect or track_path')
        if not isinstance(row['id'],str) or not row['id'].strip() or row['id'] in seen:
            raise ValueError('Guide IDs must be nonempty and unique')
        if row['kind'] not in {'subject','caption','ui'}:
            raise ValueError('Guide kind must be subject, caption or ui')
        if not isinstance(row['reason'],str) or not row['reason'].strip():
            raise ValueError('Guide requires an observation reason')
        first=_frame(_time(row['output_start'],'guide start'),rate,'guide start')
        last=_frame(_time(row['output_end'],'guide end'),rate,'guide end')
        if not 0 <= first < last <= count:
            raise ValueError('Guide interval must be within the output')
        seen.add(row['id'])
        resolved={**row,'output_start':str(Fraction(first,1)/rate),'output_end':str(Fraction(last,1)/rate)}
        if 'rect' in row:
            resolved['rect']=rectangle(row['rect'])
        else:
            if row['kind']=='ui':
                raise ValueError('UI guides use fixed screen coordinates, not tracking')
            if not isinstance(row['track_path'],str) or not row['track_path'].strip():
                raise ValueError('Guide track_path must be a local file')
            from .video_effects import _sha
            path=Path(row['track_path']).resolve(strict=True)
            sha=_sha(path)
            if 'track_sha256' in row and row['track_sha256']!=sha:
                raise ValueError('Tracking artifact changed')
            resolved.update(track_path=str(path),track_sha256=sha)
            guide_track(resolved,rate)
        result.append(resolved)
    return {'version':1,'mapping_sha256':_digest(mapping),'guides':result,
            'basis':'Declared fixed regions or observed tracked boxes; unmarked subjects and identity are not inferred.'}


def guide_track(guide, rate=None):
    """Revalidate a sealed guide dependency, including every selected frame."""
    from .video_effects import _tracking_data
    if rate is None:
        import json
        rate=Fraction(json.loads(Path(guide['track_path']).read_text())['fps'])
    return _tracking_data({'output_start':guide['output_start'],'output_end':guide['output_end'],
                           'parameters':guide},Fraction(rate))


def _envelope(frame, first, last, easing):
    if last<=first:return 0.
    phase=max(0.,min(1.,(frame-first)/(last-first)))
    triangle=1-abs(2*phase-1)
    return (1-math.cos(math.pi*triangle))/2 if easing=='cosine' else triangle*triangle*(3-2*triangle)


def _pulse_amount(event, frame, rate):
    from .video_effects import _time
    first=float(_time(event['output_start'],'start')*rate)
    end=float(_time(event['output_end'],'end')*rate)
    midpoint=(first+end-1)/2
    half=max(1,(end-first)/2)
    return event['strength']*max(0,1-abs(frame-midpoint)/half)


def _framewise_checks(events, guide, titles, rate):
    """Apply the renderer's zoom geometry at every protected output frame."""
    from .video_effects import _time,_frame,_tracking_data
    doc=guide_track(guide,rate)
    boxes={r['frame']:r['box'] for r in doc['rows']}
    first=_frame(_time(guide['output_start'],'start'),rate,'start')
    last=_frame(_time(guide['output_end'],'end'),rate,'end')
    active=[e for e in events if _time(e['output_start'],'start')<_time(guide['output_end'],'end') and
            _time(guide['output_start'],'start')<_time(e['output_end'],'end')]
    if any(e['type'] in {'split_screen','comparison_wipe'} for e in active):
        raise ValueError('Tracked composition does not support split/comparison geometry; revise interval')
    tracks={e['id']:{r['frame']:r['box'] for r in _tracking_data(e,rate)['rows']}
            for e in active if e['type']=='tracked_zoom'}
    counts={e['id']:0 for e in active if e['type'] in {'keyword_title','smooth_zoom','tracked_zoom','zoom_pulse'}}
    for frame in range(first,last):
        present=[e for e in active if _time(e['output_start'],'start')*rate<=frame<_time(e['output_end'],'end')*rate]
        box=list(boxes[frame])
        zooms=[e for e in present if e['type'] in {'smooth_zoom','tracked_zoom','zoom_pulse'}]
        # zoom_pulse is the first renderer stage and uses the maximum envelope.
        pulse=max((_pulse_amount(e,frame,rate)
                   for e in zooms if e['type']=='zoom_pulse'),default=0.)
        transforms=[(1+.04*pulse,.5,.5)]
        for e in zooms:
            if e['type']=='zoom_pulse':continue
            p=e['parameters'];a=float(_time(e['output_start'],'start')*rate);b=float(_time(e['output_end'],'end')*rate)-1
            scale=1+(p['max_scale']-1)*e['strength']*_envelope(frame,a,b,p['easing'])
            if e['type']=='tracked_zoom':
                anchor=tracks[e['id']][frame];x=(anchor[0]+anchor[2])/2;y=(anchor[1]+anchor[3])/2
            else:x,y=p['anchor_x'],p['anchor_y']
            transforms.append((scale,x,y))
        for scale,x,y in transforms:
            box=[scale*box[0]-x*(scale-1),scale*box[1]-y*(scale-1),scale*box[2]-x*(scale-1),scale*box[3]-y*(scale-1)]
        if guide['kind']=='subject' and zooms and (min(box[:2]) < -1e-9 or max(box[2:]) > 1+1e-9):
            raise ValueError(f'Zoom crops tracked subject: guide {guide["id"]}, frame {frame}')
        for e in present:
            if e['id'] in counts:counts[e['id']]+=1
            if e['type']!='keyword_title':continue
            if e['id'] not in titles:raise ValueError('Missing measured title bounds')
            bounds=list(titles[e['id']]['bounds'])
            if e['parameters']['motion']=='rise':bounds[3]=min(1,bounds[3]+.02*e['strength'])
            # Partially offscreen caption regions have only a visible portion.
            clipped=[max(0,box[0]),max(0,box[1]),min(1,box[2]),min(1,box[3])]
            if clipped[0]<clipped[2] and clipped[1]<clipped[3] and overlap(bounds,clipped)>0:
                raise ValueError(f'Text intersects tracked region: event {e["id"]}, guide {guide["id"]}, frame {frame}')
    checks=[{'event_id':id_,'guide_id':guide['id'],'status':'no_detected_conflict','frames_checked':count}
            for id_,count in counts.items()]
    checks.extend({'event_id':e['id'],'guide_id':guide['id'],'status':'not_checked_for_this_effect'}
                  for e in active if e['id'] not in counts)
    return checks


def check_composition(events, composition, title_assets=(), *, fps=None):
    """Reject measured card collision or zoom crop of declared subject bounds."""
    from .video_effects import _time
    titles={row['event_id']:row for row in title_assets}
    checked=[]
    for guide in composition['guides']:
        if 'track_path' in guide:
            rate=Fraction(fps) if fps is not None else Fraction(guide_track(guide)['fps'])
            checked.extend(_framewise_checks(events,guide,titles,rate))
    for event in events:
        for guide in composition['guides']:
            if 'track_path' in guide:continue
            if (_time(event['output_start'],'start') >= _time(guide['output_end'],'end') or
                _time(guide['output_start'],'start') >= _time(event['output_end'],'end')):
                continue
            if event['type'] not in {'keyword_title', 'smooth_zoom'}:
                checked.append({'event_id':event['id'],'guide_id':guide['id'],'status':'not_checked_for_this_effect'})
                continue
            problem=None
            if event['type']=='keyword_title':
                if event['id'] not in titles:raise ValueError('Missing measured title bounds')
                bounds=list(titles[event['id']]['bounds'])
                if event['parameters']['motion']=='rise':
                    bounds[3]=min(1,bounds[3]+.02*event['strength'])
                protected=list(guide['rect'])
                if guide['kind'] != 'ui':
                    for zoom in (e for e in events if e['type']=='smooth_zoom'):
                        if (_time(zoom['output_start'],'start') >= _time(event['output_end'],'end') or
                            _time(event['output_start'],'start') >= _time(zoom['output_end'],'end')):
                            continue
                        p=zoom['parameters'];s=1+(p['max_scale']-1)*zoom['strength']
                        shifted=[s*protected[0]-p['anchor_x']*(s-1),s*protected[1]-p['anchor_y']*(s-1),
                                 s*protected[2]-p['anchor_x']*(s-1),s*protected[3]-p['anchor_y']*(s-1)]
                        protected=[max(0,min(protected[0],shifted[0])),max(0,min(protected[1],shifted[1])),
                                   min(1,max(protected[2],shifted[2])),min(1,max(protected[3],shifted[3]))]
                if overlap(bounds,protected) > 0:
                    problem='Text intersects protected region'
            elif event['type']=='smooth_zoom' and guide['kind']=='subject':
                p=event['parameters'];scale=1+(p['max_scale']-1)*event['strength']
                x0=p['anchor_x']*(1-1/scale);y0=p['anchor_y']*(1-1/scale)
                visible=[x0,y0,x0+1/scale,y0+1/scale]
                box=guide['rect']
                if box[0]<visible[0] or box[1]<visible[1] or box[2]>visible[2] or box[3]>visible[3]:
                    problem='Zoom crops protected subject at maximum scale'
            if problem:
                raise ValueError(f'{problem}: event {event["id"]}, guide {guide["id"]}; revise position, strength or interval')
            checked.append({'event_id':event['id'],'guide_id':guide['id'],'status':'no_detected_conflict'})
    return {'version':1,'mapping_sha256':composition['mapping_sha256'],'checks':checked,
            'scope':'Declared regions only; full visual review remains required.'}
