"""Frame-bound, reviewable visual effects on an already rendered edit.

Effects change picture only. The audio stream is copied from the input, and no
beat alignment is claimed merely because an event is anchored to a cut.
"""
from __future__ import annotations

from fractions import Fraction
import hashlib
import json
from pathlib import Path
import subprocess
import uuid

TYPES = {'zoom_pulse', 'split_screen', 'monochrome', 'color_frame',
         'smooth_zoom', 'tracked_zoom', 'saturation_pulse', 'comparison_wipe', 'keyword_title', 'tracked_title', 'motion_trail', 'tracked_background'}
INTENSITY = {'low': .35, 'medium': .65, 'high': 1.0}


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                     separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def _sha(path):
    hash_ = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(4 * 1024 * 1024), b''):
            hash_.update(chunk)
    return hash_.hexdigest()


def _time(value, name):
    if isinstance(value, bool):
        raise ValueError(f'{name} must be finite time')
    try:
        result = Fraction(str(value).removesuffix('s'))
    except (ValueError, TypeError, ZeroDivisionError) as exc:
        raise ValueError(f'{name} must be finite time') from exc
    return result


def _mapping_shape(mapping):
    if not isinstance(mapping, dict) or not isinstance(mapping.get('sequence'), list):
        raise ValueError('Effects require an actual frame mapping sequence')
    rate = _time(mapping.get('fps'), 'mapping.fps')
    duration = _time(mapping.get('duration'), 'mapping.duration')
    if rate <= 0 or duration <= 0:
        raise ValueError('Mapping FPS and duration must be positive')
    frames = duration * rate
    if abs(float(frames - round(frames))) > .01:
        raise ValueError('Mapping duration is not frame aligned')
    return rate, round(frames)


def _frame(time, rate, field):
    frame = time * rate
    if abs(float(frame - round(frame))) > .01:
        raise ValueError(f'{field} must align to an output frame')
    return round(frame)


def _canonical_event(row, rate, count):
    required = {'id', 'type', 'output_start', 'output_end', 'strength', 'reason'}
    if not isinstance(row, dict) or not required <= set(row) or set(row) - required - {'parameters', 'effect_version', 'font_sha256', 'layout_binding'}:
        raise ValueError('Effect event needs exact id, type, times, strength, reason')
    if not isinstance(row['id'], str) or not row['id'].strip():
        raise ValueError('Effect id must be nonempty')
    if row['type'] not in TYPES:
        raise ValueError('Unsupported effect type')
    if isinstance(row['strength'], bool) or not isinstance(row['strength'], (float, int)) or not 0 < row['strength'] <= 1:
        raise ValueError('Effect strength must be in (0, 1]')
    if not isinstance(row['reason'], str) or not row['reason'].strip():
        raise ValueError('Effect reason must be nonempty')
    first = _frame(_time(row['output_start'], 'output_start'), rate, 'output_start')
    last = _frame(_time(row['output_end'], 'output_end'), rate, 'output_end')
    if first < 0 or last > count or last <= first:
        raise ValueError('Effect must occupy at least one existing output frame')
    result = {'id': row['id'], 'type': row['type'], 'output_start': str(Fraction(first, 1) / rate),
            'output_end': str(Fraction(last, 1) / rate), 'strength': float(row['strength']),
            'reason': row['reason'].strip()}
    if row['type'] in {'keyword_title', 'tracked_title'}:
        from .effect_catalog import validate_parameters
        if type(row.get('effect_version', 1)) is not int or row.get('effect_version', 1) not in (1, 2):
            raise ValueError('Unsupported effect version')
        version = row.get('effect_version', 1)
        result['parameters'] = validate_parameters(row['type'], row.get('parameters', {}), version=version)
        if version == 2:
            from .text_effects import layout_binding
            binding = layout_binding()
            if row.get('layout_binding', binding) != binding:
                raise ValueError('Text layout engine/model binding changed')
            result['layout_binding'] = binding
        elif 'layout_binding' in row:
            raise ValueError('Only version-2 text effects accept a layout binding')
        font_sha = _sha(result['parameters']['font_path'])
        if row.get('font_sha256', font_sha) != font_sha:
            raise ValueError('Text font binding changed')
        result['font_sha256'] = font_sha
        result['effect_version'] = version
        if row['type'] == 'tracked_title':
            params = result['parameters']; sha = _sha(params['track_path'])
            if params['track_sha256'] not in (None, sha):
                raise ValueError('Tracking artifact changed')
            params['track_sha256'] = sha
            _tracking_data(result, rate)
    elif row['type'] in {'smooth_zoom', 'tracked_zoom', 'saturation_pulse', 'comparison_wipe', 'motion_trail', 'tracked_background'}:
        if 'font_sha256' in row or 'layout_binding' in row:
            raise ValueError('Only text effects accept a font binding')
        if type(row.get('effect_version', 1)) is not int or row.get('effect_version', 1) != 1:
            raise ValueError('Unsupported effect version')
        if row['type'] not in {'comparison_wipe','motion_trail','tracked_background'} and last - first < 3:
            raise ValueError('Smooth pulse effects require at least three frames')
        from .effect_catalog import validate_parameters
        result['parameters'] = validate_parameters(row['type'], row.get('parameters', {}))
        result['effect_version'] = 1
        if row['type']=='tracked_background':
            params=result['parameters'];sha=_sha(params['mask_path'])
            if params['mask_sha256'] not in (None,sha):
                raise ValueError('Subject mask artifact changed')
            params['mask_sha256']=sha
            _mask_data(result,rate)
        if row['type']=='motion_trail' and last-first < result['parameters']['history_frames']:
            raise ValueError('Motion trail window is shorter than its history')
        if row['type']=='tracked_zoom':
            params=result['parameters'];sha=_sha(params['track_path'])
            if params['track_sha256'] is not None and params['track_sha256']!=sha:
                raise ValueError('Tracking artifact changed')
            params['track_sha256']=sha
            _tracking_data(result,rate)
    elif 'parameters' in row or 'effect_version' in row or 'font_sha256' in row or 'layout_binding' in row:
        raise ValueError('Legacy effects do not accept parameters; use a versioned new effect')
    return result


def resolve_effects(setting, mapping, assets=None):
    """Return an exact-mapping-bound effect plan; never infer musical beats."""
    mapping_sha = _digest(mapping)
    if setting is None or setting == 'natural' or setting == {'preset': 'natural'}:
        return {'version': 1, 'mapping_sha256': mapping_sha, 'preset': None, 'events': []}
    rate, count = _mapping_shape(mapping)
    if not isinstance(setting, dict):
        raise ValueError('Effects setting must be a preset or explicit plan')
    if 'preset' in setting:
        if set(setting) != {'preset', 'intensity'} or setting['preset'] not in {'pop_dance', 'subtle'} or setting['intensity'] not in INTENSITY:
            raise ValueError('Preset needs supported preset and intensity')
        preset, strength = setting['preset'], INTENSITY[setting['intensity']]
        cuts = sorted({_frame(_time(row.get('output_start'), 'sequence.output_start'), rate,
                              'sequence.output_start') for row in mapping['sequence'] if row.get('output_start') is not None})
        cuts = [frame for frame in cuts if 0 < frame < count]
        if not cuts:
            raise ValueError('Preset needs actual output cut boundaries')
        events = []
        for i, cut in enumerate(cuts[:4]):
            end = min(count, cut + max(1, round(float(rate) * .35)))
            events.append({'id': f'cut-{i+1}-zoom', 'type': 'zoom_pulse',
                           'output_start': str(Fraction(cut, 1) / rate),
                           'output_end': str(Fraction(end, 1) / rate),
                           'strength': strength, 'reason': 'actual output cut boundary'})
        if preset == 'pop_dance':
            cut = cuts[min(len(cuts) - 1, len(cuts) // 2)]
            end = min(count, cut + max(1, round(float(rate) * .7)))
            events.append({'id': 'mid-cut-split', 'type': 'split_screen',
                           'output_start': str(Fraction(cut, 1) / rate),
                           'output_end': str(Fraction(end, 1) / rate),
                           'strength': strength, 'reason': 'actual output cut boundary'})
    else:
        if set(setting) != {'version', 'mapping_sha256', 'events'} or setting['version'] != 1:
            raise ValueError('Explicit effects need exact version, mapping hash and events')
        if setting['mapping_sha256'] != mapping_sha:
            raise ValueError('Stale effects: mapping hash changed')
        if not isinstance(setting['events'], list):
            raise ValueError('Effects events must be a list')
        preset = None
        events = setting['events']
    normalized = [_canonical_event(event, rate, count) for event in events]
    for event in normalized:
        if event['type'] == 'motion_trail':
            start,end = _time(event['output_start'],'start'),_time(event['output_end'],'end')
            if any(start < _time(row['output_start'],'cut') < end for row in mapping['sequence'] if row.get('output_start') is not None):
                raise ValueError('Motion trail cannot cross a mapped cut; split the event')
    from .cues import _asset_map, _check_asset
    registry = _asset_map(assets or [])
    for event in normalized:
        if event['type'] == 'comparison_wipe':
            params = event['parameters']
            asset = _check_asset(params['asset_id'], registry)
            if asset.get('kind') != 'video':
                raise ValueError('Comparison requires a registered video asset')
            if params['asset_sha256'] not in (None, asset['sha256']):
                raise ValueError('Comparison asset binding changed')
            params['asset_sha256'] = asset['sha256']
    if len({event['id'] for event in normalized}) != len(normalized):
        raise ValueError('Duplicate effect ids')
    _check_trail_overlaps(normalized)
    normalized.sort(key=lambda item: (_time(item['output_start'], 'start'), item['type'], item['id']))
    return {'version': 1, 'mapping_sha256': mapping_sha, 'preset': preset, 'events': normalized}


def _check_trail_overlaps(events):
    trails = [event for event in events if event['type'] == 'motion_trail']
    for index,event in enumerate(trails):
        if any(_time(event['output_start'],'start') < _time(other['output_end'],'end') and _time(other['output_start'],'start') < _time(event['output_end'],'end') for other in trails[index+1:]):
            raise ValueError('Motion trail windows cannot overlap')


def revise_effects(setting, mapping, operations, assets=None):
    """Create a new explicit plan; removal is off, originals remain untouched."""
    from copy import deepcopy
    plan = resolve_effects(setting, mapping, assets)
    events = {event['id']: deepcopy(event) for event in plan['events']}
    if not isinstance(operations, list) or not operations:
        raise ValueError('Provide at least one effect operation')
    for operation in operations:
        if not isinstance(operation, dict):
            raise ValueError('Effect operation must be an object')
        action = operation.get('action')
        if action == 'add' and set(operation) == {'action', 'event'}:
            event = deepcopy(operation['event'])
            if not isinstance(event, dict) or not isinstance(event.get('id'), str):
                raise ValueError('Added effect needs an id')
            if event['id'] in events:
                raise ValueError('Duplicate effect id')
            events[event['id']] = event
        elif action in {'update', 'remove'}:
            expected = {'action', 'id', 'changes'} if action == 'update' else {'action', 'id'}
            if set(operation) != expected or not isinstance(operation['id'], str) or operation['id'] not in events:
                raise ValueError('Effect operation must target an existing id')
            if action == 'remove':
                del events[operation['id']]
            else:
                changes = operation['changes']
                allowed = {'strength', 'parameters', 'output_start', 'output_end', 'reason'}
                if not isinstance(changes, dict) or not changes or set(changes) - allowed:
                    raise ValueError('Update strength, parameters, timing or reason only')
                if 'parameters' in changes:
                    if not isinstance(changes['parameters'], dict):
                        raise ValueError('Effect parameters must be an object')
                    changes = deepcopy(changes)
                    changes['parameters'] = {**events[operation['id']].get('parameters', {}), **changes['parameters']}
                events[operation['id']].update(deepcopy(changes))
        else:
            raise ValueError('Unsupported effect operation')
    result = resolve_effects({'version': 1, 'mapping_sha256': plan['mapping_sha256'],
                              'events': list(events.values())}, mapping, assets)
    return {key: result[key] for key in ('version', 'mapping_sha256', 'events')}


def _probe(path, count=False):
    command = ['ffprobe', '-v', 'error']
    if count:
        command.append('-count_frames')
    command += ['-show_streams', '-show_format', '-of', 'json', str(path)]
    return json.loads(subprocess.check_output(command))


def _stream(info, kind):
    return next((row for row in info['streams'] if row.get('codec_type') == kind), None)


def _verified_rate(path, video, count):
    """Use frame timestamps: MP4 timebase rounding can skew avg_frame_rate."""
    try:
        rate = Fraction(video['r_frame_rate'])
        timebase = Fraction(video['time_base'])
    except (KeyError, ValueError, ZeroDivisionError) as exc:
        raise ValueError('Effects require a known frame rate and timebase') from exc
    if rate <= 0 or timebase <= 0:
        raise ValueError('Effects require a known positive frame rate')
    frames = json.loads(subprocess.check_output([
        'ffprobe', '-v', 'error', '-select_streams', 'v:0',
        '-show_entries', 'frame=best_effort_timestamp', '-of', 'json', str(path)]))['frames']
    try:
        ticks = [int(row['best_effort_timestamp']) for row in frames]
    except (KeyError, ValueError, TypeError) as exc:
        raise ValueError('Effects require every video frame timestamp') from exc
    if len(ticks) != count or not ticks:
        raise ValueError('Effects frame timestamps disagree with decoded frame count')
    ideal_ticks = Fraction(1, 1) / (rate * timebase)
    tolerance = max(Fraction(1, 1), ideal_ticks / 8)
    for index, tick in enumerate(ticks):
        if index and tick <= ticks[index - 1]:
            raise ValueError('Effects require strictly increasing frame timestamps')
        if abs(tick - ticks[0] - index * ideal_ticks) > tolerance:
            raise ValueError('Effects require constant frame rate timestamps')
    return rate


def _seconds(event, key):
    return float(_time(event[key], key))


def _mask_data(event, rate, source=None):
    from .subject_mask import validate_masks
    params=event['parameters']
    if _sha(params['mask_path']) != params['mask_sha256']:
        raise ValueError('Subject mask artifact changed')
    doc=validate_masks(params['mask_path'], source=source,
        first_frame=_frame(_time(event['output_start'],'start'),rate,'start'),
        end_frame=_frame(_time(event['output_end'],'end'),rate,'end'))
    if Fraction(doc['fps']) != rate:
        raise ValueError('Subject mask FPS differs from effects input')
    return doc


def _tracking_data(event, rate):
    from .tracking import validate_track
    params=event['parameters']
    if _sha(params['track_path'])!=params['track_sha256']:
        raise ValueError('Tracking artifact changed')
    doc=json.loads(Path(params['track_path']).read_text())
    first=_frame(_time(event['output_start'],'start'),rate,'start')
    end=_frame(_time(event['output_end'],'end'),rate,'end')
    validate_track(doc,first_frame=first,end_frame=end)
    if Fraction(doc['fps'])!=rate:
        raise ValueError('Tracking FPS differs from effects input')
    return doc


def _anchor_expression(rows, axis):
    # Balanced expression keeps parser depth logarithmic even for long clips.
    # Every selected output frame uses its exact observed box, never a gap fill.
    def tree(items):
        if len(items)==1:
            box=items[0]['box']
            return f'{(box[axis]+box[axis+2])/2:.9f}'
        half=len(items)//2;frame=items[half]['frame']
        return f'if(lt(on,{frame}),{tree(items[:half])},{tree(items[half:])})'
    return tree(rows)


def _pulse(variable, first, last, easing):
    """A symmetric pulse, exactly zero at both boundary frames."""
    if last <= first:
        return '0'
    phase = f'max(0,min(1,({variable}-{first:.9f})/{last-first:.9f}))'
    triangle = f'(1-abs(2*({phase})-1))'
    if easing == 'cosine':
        return f'(1-cos(PI*{triangle}))/2'
    return f'({triangle})*({triangle})*(3-2*({triangle}))'


def _filter_graph(events, width, height, rate):
    zooms = [event for event in events if event['type'] == 'zoom_pulse']
    terms = []
    for event in zooms:
        first = round(_time(event['output_start'], 'start') * rate)
        last = round(_time(event['output_end'], 'end') * rate)
        midpoint = (first + last - 1) / 2
        half = max(1, (last - first) / 2)
        terms.append(f'{event["strength"]:.6f}*max(0,1-abs(on-{midpoint:.3f})/{half:.3f})')
    envelope = '0'
    for term in terms:
        envelope = f'max({envelope},{term})'
    graph = (f'[0:v]zoompan=z=\'1+0.04*({envelope})\':d=1:'
             f'x=iw/2-iw/zoom/2:y=ih/2-ih/zoom/2:s={width}x{height}:'
             f'fps={rate.numerator}/{rate.denominator},setsar=1[v0]')
    current = 'v0'
    for i, event in enumerate(row for row in events if row['type'] in {'smooth_zoom','tracked_zoom'}):
        params = event['parameters']
        first = round(_time(event['output_start'], 'start') * rate)
        last = round(_time(event['output_end'], 'end') * rate) - 1
        envelope = _pulse('on', first, last, params['easing'])
        scale = (params['max_scale'] - 1) * event['strength']
        if event['type']=='tracked_zoom':
            doc=_tracking_data(event,rate)
            rows=[r for r in doc['rows'] if first<=r['frame']<=last]
            anchor_x=_anchor_expression(rows,0);anchor_y=_anchor_expression(rows,1)
        else:
            anchor_x=f'{params["anchor_x"]:.9f}';anchor_y=f'{params["anchor_y"]:.9f}'
        target = f'vsmooth{i}'
        graph += (f';[{current}]zoompan=z=\'1+{scale:.9f}*({envelope})\':d=1:'
                  f"x='iw*({anchor_x})*(1-1/zoom)':"
                  f"y='ih*({anchor_y})*(1-1/zoom)':"
                  f's={width}x{height}:fps={rate.numerator}/{rate.denominator},setsar=1[{target}]')
        current = target
    for i, event in enumerate(row for row in events if row['type'] == 'saturation_pulse'):
        params = event['parameters']
        first = _seconds(event, 'output_start')
        last = _seconds(event, 'output_end') - float(1 / rate)
        envelope = _pulse('t', first, last, params['easing'])
        reduction = (1 - params['minimum_saturation']) * event['strength']
        target = f'vsaturation{i}'
        graph += f';[{current}]hue=s=\'1-{reduction:.9f}*({envelope})\'[{target}]'
        current = target
    splits = [event for event in events if event['type'] == 'split_screen']
    for i, event in enumerate(splits):
        base, branch, target = f'base{i}', f'branch{i}', f'vsplit{i}'
        start, end = _seconds(event, 'output_start'), _seconds(event, 'output_end')
        graph += f';[{current}]split[{base}][{branch}]'
        graph += f';[{branch}]hflip,crop=iw/2:ih:iw/2:0[right{i}]'
        graph += (f';[{base}][right{i}]overlay=x=main_w/2:y=0:'
                  f"enable='gte(t,{start:.9f})*lt(t,{end:.9f})':shortest=1[{target}]")
        current = target
    for i, event in enumerate(row for row in events if row['type'] == 'monochrome'):
        start, end = _seconds(event, 'output_start'), _seconds(event, 'output_end')
        target = f'vmono{i}'
        graph += (f';[{current}]hue=s=0:'
                  f"enable='gte(t,{start:.9f})*lt(t,{end:.9f})'[{target}]")
        current = target
    for i, event in enumerate(row for row in events if row['type'] == 'color_frame'):
        start, end = _seconds(event, 'output_start'), _seconds(event, 'output_end')
        thickness = max(2, round(min(width, height) * .015 * event['strength']))
        target = f'vframe{i}'
        graph += (f';[{current}]drawbox=x=0:y=0:w=iw:h=ih:color=cyan@0.85:'
                  f"t={thickness}:enable='gte(t,{start:.9f})*lt(t,{end:.9f})'[{target}]")
        current = target
    return graph, current


def render_effects(input, plan, output, assets=None, composition=None, *, preserve_audio_end=False):
    """Render a sealed effect plan; preserve original audio and frame count."""
    if type(preserve_audio_end) is not bool:
        raise ValueError('preserve_audio_end must be boolean')
    source, target = Path(input).resolve(strict=True), Path(output).resolve()
    if source == target or target.exists():
        raise ValueError('Effects output must be a new file distinct from input')
    if not isinstance(plan, dict) or set(plan) != {'version', 'mapping_sha256', 'preset', 'events'} or plan['version'] != 1:
        raise ValueError('Pass a resolved effect plan')
    if not isinstance(plan['mapping_sha256'], str) or len(plan['mapping_sha256']) != 64:
        raise ValueError('Effect plan needs a mapping hash')
    if not plan['events']:
        raise ValueError('No effects to render')
    source_sha = _sha(source)
    info = _probe(source, count=True)
    video, audio = _stream(info, 'video'), _stream(info, 'audio')
    if not video or not audio:
        raise ValueError('Effects source requires video and embedded audio')
    count = int(video['nb_read_frames'])
    rate = _verified_rate(source, video, count)
    duration = Fraction(count, 1) / rate
    # The public plan is bound to the real frame mapping by resolve_effects.
    # Here event frame validity is checked again against the observed input.
    events = [_canonical_event(event, rate, count) for event in plan['events']]
    _check_trail_overlaps(events)
    if composition is not None:
        from .composition import resolve_guides
        if not isinstance(composition, dict) or composition.get('version') != 1 or composition.get('mapping_sha256') != plan['mapping_sha256']:
            raise ValueError('Composition guides are stale or invalid')
        validated = resolve_guides(composition.get('guides'), {'fps':str(rate),'duration':str(duration),'sequence':[]})
        validated['mapping_sha256'] = composition['mapping_sha256']
        composition = validated
    if len({event['id'] for event in events}) != len(events):
        raise ValueError('Duplicate effect ids')
    tracking_inputs=[]
    if composition is not None:
        from .composition import guide_track
        for guide in composition['guides']:
            if 'track_path' not in guide:continue
            doc=guide_track(guide,rate)
            if doc['source']['sha256']!=source_sha or doc['source']['bytes']!=source.stat().st_size:
                raise ValueError('Tracked guide belongs to a different effects input')
            tracking_inputs.append({'guide_id':guide['id'],'path':guide['track_path'],
                                    'sha256':guide['track_sha256'],'algorithm':doc['algorithm'],
                                    'source_sha256':doc['source']['sha256']})
    for event in events:
        if event['type'] in {'tracked_zoom', 'tracked_title'}:
            for other in events:
                if other is event or other['type'] not in ({'zoom_pulse','smooth_zoom','tracked_zoom','split_screen','comparison_wipe'} if event['type']=='tracked_title' else {'zoom_pulse','smooth_zoom','tracked_zoom'}):
                    continue
                if _time(event['output_start'],'start')<_time(other['output_end'],'end') and _time(other['output_start'],'start')<_time(event['output_end'],'end'):
                    raise ValueError('Tracked geometry cannot be stacked with overlapping zoom/split/comparison effects')
            doc=_tracking_data(event,rate)
            if doc['source']['sha256']!=source_sha or doc['source']['bytes']!=source.stat().st_size:
                raise ValueError('Tracking belongs to a different effects input; track the retained pre-effects picture')
            tracking_inputs.append({'event_id':event['id'],'path':event['parameters']['track_path'],
                                    'sha256':event['parameters']['track_sha256'],
                                    'algorithm':doc['algorithm'],'source_sha256':doc['source']['sha256']})
    mask_inputs=[]
    for event in events:
        if event['type'] != 'tracked_background':continue
        for other in events:
            if other is event or other['type'] not in {'zoom_pulse','smooth_zoom','tracked_zoom','split_screen','comparison_wipe','tracked_background','motion_trail'}:continue
            if _time(event['output_start'],'start') < _time(other['output_end'],'end') and _time(other['output_start'],'start') < _time(event['output_end'],'end'):
                raise ValueError('Subject masks cannot overlap geometry-changing effects, trails or another mask')
        mask_inputs.append({'event':event,'doc':_mask_data(event,rate,source)})
    width, height = int(video['width']), int(video['height'])
    if width % 2 or height % 2:
        raise ValueError('Effects source dimensions must be even')
    graph, label = _filter_graph(events, width, height, rate)
    temporal_inputs = []
    from .motion_trail import build_trail_graph
    for index,event in enumerate(events):
        if event['type'] != 'motion_trail':
            continue
        next_label = f'vtrail{index}'
        fragment,evidence = build_trail_graph(label,next_label,event,rate,count)
        graph += ';' + fragment
        label = next_label
        temporal_inputs.append({'event_id':event['id'],**evidence})
    secondary = []
    from .cues import _asset_map, _check_asset
    registry = _asset_map(assets or [])
    for event in events:
        if event['type'] != 'comparison_wipe':
            continue
        params = event['parameters']
        asset = _check_asset(params['asset_id'], registry)
        if asset.get('kind') != 'video' or params['asset_sha256'] != asset['sha256']:
            raise ValueError('Comparison asset binding changed')
        from .visual import _video_info
        observed_source = _video_info(asset['path'])
        observed_info = _probe(asset['path'], count=True)
        observed_video = _stream(observed_info, 'video')
        _verified_rate(asset['path'], observed_video, int(observed_video['nb_read_frames']))
        event_duration = _time(event['output_end'], 'end') - _time(event['output_start'], 'start')
        begin = _time(params['source_start'], 'source_start')
        _frame(begin, observed_source['fps'], 'Comparison source_start')
        if begin + event_duration > observed_source['duration']:
            raise ValueError('Comparison range exceeds second video duration')
        secondary.append({'event': event, 'asset': asset, 'source_fps': str(observed_source['fps'])})
    target.parent.mkdir(parents=True, exist_ok=True)
    log = target.with_suffix('.effects.log')
    command = ['ffmpeg', '-hide_banner', '-nostdin', '-n', '-i', str(source)]
    for index, item in enumerate(secondary, 1):
        event, asset = item['event'], item['asset']
        command += ['-i', asset['path']]
        begin = event['parameters']['source_start']
        start, end = _seconds(event, 'output_start'), _seconds(event, 'output_end')
        divider = max(2, min(width - 2, round(width * event['parameters']['divider'] / 2) * 2))
        branch, target_label = f'compare_input{index}', f'compared{index}'
        right_transform = (f'scale={width}:{height}:force_original_aspect_ratio=decrease,'
                           f'pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,setsar=1,'
                           f'crop={width-divider}:{height}:{divider}:0')
        if event['parameters']['layout'] == 'side_by_side':
            right_width = width - divider
            right_transform = (f'scale={right_width}:{height}:force_original_aspect_ratio=decrease,'
                               f'pad={right_width}:{height}:(ow-iw)/2:(oh-ih)/2,setsar=1')
        graph += (f';[{index}:v]trim=start={begin:.9f}:duration={end-start:.9f},setpts=PTS-STARTPTS,'
                  f'fps={rate.numerator}/{rate.denominator},'
                  f'{right_transform},format=rgba,'
                  f'colorchannelmixer=aa={event["strength"]:.9f},setpts=PTS+{start:.9f}/TB[{branch}]')
        overlay_x = divider
        if event['parameters']['layout'] == 'side_by_side':
            base_label, left_label, composite = f'compare_base{index}', f'compare_left{index}', f'compare_pair{index}'
            graph += f';[{label}]split[{base_label}][{left_label}]'
            graph += (f';[{left_label}]trim=start={start:.9f}:duration={end-start:.9f},'
                      f'setpts=PTS-STARTPTS+{start:.9f}/TB,'
                      f'scale={divider}:{height}:force_original_aspect_ratio=decrease,'
                      f'pad={divider}:{height}:(ow-iw)/2:(oh-ih)/2,setsar=1[{left_label}_fit]')
            graph += f';[{left_label}_fit][{branch}]hstack=inputs=2:shortest=1[{composite}]'
            label, branch, overlay_x = base_label, composite, 0
        graph += (f';[{label}][{branch}]overlay=x={overlay_x}:y=0:eof_action=pass:repeatlast=0:'
                  f"enable='gte(t,{start:.9f})*lt(t,{end:.9f})'[{target_label}]")
        label = target_label
    for index,item in enumerate(mask_inputs,len(secondary)+1):
        event,doc=item['event'],item['doc']
        from .subject_background import background_graph
        command += ['-framerate',str(rate),'-start_number',str(_frame(_time(event['output_start'],'start'),rate,'start')),
                    '-i',str(Path(event['parameters']['mask_path']).parent/'%08d.png')]
        fragment,next_label=background_graph(label,index,event,rate)
        graph += ';' + fragment
        label=next_label
    titles = []
    resource_dir = target.parent / (target.stem + '.resources-' + uuid.uuid4().hex[:8])
    for event in events:
        if event['type'] not in {'keyword_title', 'tracked_title'}:
            continue
        from .text_effects import render_text_asset
        resource_dir.mkdir(parents=True, exist_ok=True)
        png = resource_dir / f'title-{len(titles)}.png'
        text_parameters = {k:v for k,v in event['parameters'].items() if k not in {'track_path','track_sha256','placement','gap_fraction','offset_x','offset_y'}}
        title = render_text_asset(text_parameters, width, height, png, version=event['effect_version'])
        if event['effect_version'] == 2 and title['layout_binding'] != event['layout_binding']:
            raise ValueError('Text layout engine/model changed while rendering')
        if title['font_sha256'] != event['font_sha256']:
            raise ValueError('Text font changed while rendering')
        input_index = len(secondary) + len(mask_inputs) + len(titles) + 1
        command += ['-loop', '1', '-framerate', str(rate), '-i', str(png)]
        first, last = _seconds(event, 'output_start'), _seconds(event, 'output_end')
        fade = min(.18, (last-first)/3)
        branch, target_label = f'title_input{input_index}', f'titled{input_index}'
        graph += (f';[{input_index}:v]format=rgba,colorchannelmixer=aa={event["strength"]:.9f},'
                  f'fade=t=in:st={first:.9f}:d={fade:.9f}:alpha=1,'
                  f'fade=t=out:st={last-fade:.9f}:d={fade:.9f}:alpha=1[{branch}]')
        x = '0'
        if event['type'] == 'tracked_title':
            from .tracked_title import compile_title_positions
            doc = _tracking_data(event, rate)
            first_frame=_frame(_time(event['output_start'],'start'),rate,'start')
            last_frame=_frame(_time(event['output_end'],'end'),rate,'end')
            rows=[r for r in doc['rows'] if first_frame<=r['frame']<last_frame]
            positions = compile_title_positions(rows, first_frame, last_frame,
                                                width, height, title['bounds'],
                                                {k:event['parameters'][k] for k in ('placement','gap_fraction','offset_x','offset_y')})
            title['frame_positions'] = positions
            def expression(rows, key):
                if len(rows) == 1: return str(rows[0][key])
                half = len(rows)//2
                clock = f'floor(t*{rate.numerator}/{rate.denominator}+0.5)'
                return f'if(lt({clock},{rows[half]["frame"]}),{expression(rows[:half],key)},{expression(rows[half:],key)})'
            x = expression(positions, 'x_pixels')
            y = expression(positions, 'y_pixels')
        travel = min(height*.02*event['strength'], height*(1-title['bounds'][3]))
        static_y = f'{travel:.9f}*max(0,1-(t-{first:.9f})/{fade:.9f})' if event['parameters']['motion'] == 'rise' else '0'
        if event['type'] != 'tracked_title': y = static_y
        if event['type'] == 'keyword_title' and event['parameters']['motion'] == 'rise':
            import math
            # Default overlay output is yuv420: its translation is rounded down
            # to the two-pixel chroma grid. Keep the legacy rendering unchanged.
            first_frame = _frame(_time(event['output_start'],'start'),rate,'start')
            last_frame = _frame(_time(event['output_end'],'end'),rate,'end')
            title['frame_positions'] = []
            for frame in range(first_frame, last_frame):
                offset = float(f'{travel:.9f}') * max(0, 1-(float(Fraction(frame,1)/rate)-float(f'{first:.9f}'))/float(f'{fade:.9f}'))
                pixels = math.floor(offset) // 2 * 2
                bounds = list(title['bounds'])
                bounds[1] += pixels / height; bounds[3] += pixels / height
                title['frame_positions'].append({'frame':frame,'bounds':bounds,
                                                'x_pixels':0,'y_pixels':pixels})
        pixel_format = 'format=rgb:' if event['type']=='tracked_title' else ''
        graph += (f';[{label}][{branch}]overlay=x=\'{x}\':y=\'{y}\':{pixel_format}eval=frame:shortest=1:'
                  f"enable='gte(t,{first:.9f})*lt(t,{last:.9f})'[{target_label}]")
        label = target_label
        titles.append({**title, 'path': str(png), 'event_id': event['id'],
                       'subject_clearance': 'unverified; measured text bounds only'})
    composition_evidence = None
    from .title_collisions import check_title_collisions
    title_collision_checks = check_title_collisions(events, titles, fps=rate)
    if composition is not None:
        from .composition import check_composition
        composition_evidence = check_composition(events, composition, titles, fps=rate)
    if (video.get('color_primaries'),video.get('color_transfer'),video.get('color_space')) == ('bt709','bt709','bt709'):
        graph += f';[{label}]setparams=color_primaries=bt709:color_trc=bt709:colorspace=bt709[retained_rec709]'
        label = 'retained_rec709'
    command += ['-filter_complex', graph, '-map', f'[{label}]', '-map', '0:a:0',
               '-c:v', 'libx264', '-preset', 'fast', '-crf', '18', '-pix_fmt', 'yuv420p',
               '-c:a', 'copy', *(['-movie_timescale','48000'] if preserve_audio_end else []),
               '-movflags', '+faststart', str(target)]
    try:
        with log.open('w', encoding='utf-8') as stream:
            stream.write(json.dumps(command) + '\n')
            stream.flush()
            run = subprocess.run(command, stdout=stream, stderr=stream)
        if run.returncode:
            raise RuntimeError(f'Effects FFmpeg failed ({run.returncode}); see {log}')
        observed = _probe(target, count=True)
        picture, sound = _stream(observed, 'video'), _stream(observed, 'audio')
        if not picture or not sound or int(picture['nb_read_frames']) != count:
            raise ValueError('Effects changed video frame count or removed audio')
        if _verified_rate(target, picture, count) != rate:
            raise ValueError('Effects changed frame rate')
        if abs(Fraction(str(picture['duration'])) - duration) > Fraction(1, 1) / rate:
            raise ValueError('Effects changed duration')
        if sound['codec_name'] != audio['codec_name']:
            raise ValueError('Effects changed audio codec')
        with log.open('a', encoding='utf-8') as stream:
            subprocess.run(['ffmpeg', '-v', 'error', '-xerror', '-i', str(target), '-f', 'null', '-'],
                           stdout=stream, stderr=stream, check=True)
        if _sha(source) != source_sha:
            raise ValueError('Effects input changed during render')
        for item in secondary:
            _check_asset(item['asset']['asset_id'], registry)
        for title in titles:
            if _sha(title['font_path']) != title['font_sha256'] or _sha(title['path']) != title['png_sha256']:
                raise ValueError('Text resource changed during render')
        for item in mask_inputs:
            _mask_data(item['event'],rate,source)
        for item in tracking_inputs:
            if _sha(item['path'])!=item['sha256']:
                raise ValueError('Tracking resource changed during render')
    except Exception:
        target.unlink(missing_ok=True)
        raise
    return {'version': 1, 'input_sha256': source_sha, 'output_sha256': _sha(target),
            'mapping_sha256': plan['mapping_sha256'], 'events': events,
            'text_assets': titles,
            'temporal_inputs': temporal_inputs,
            'subject_masks':[{'event_id':item['event']['id'],'manifest_sha256':item['event']['parameters']['mask_sha256'],
                             'manifest_path':item['event']['parameters']['mask_path'],'source_sha256':item['doc']['source']['sha256'],
                             'frames':len(item['doc']['rows']),'review_required':True} for item in mask_inputs],
            'tracking_inputs': tracking_inputs,
            'composition': composition_evidence,
            'title_collision_checks': title_collision_checks,
            'secondary_inputs': [{'asset_id': item['asset']['asset_id'],
                                  'sha256': item['asset']['sha256'],
                                  'source_fps': item['source_fps'],
                                  'source_start': item['event']['parameters']['source_start'],
                                  'event_id': item['event']['id'], 'audio_used': False}
                                 for item in secondary],
            'frame_count': count, 'fps': str(rate), 'duration': float(duration),
            'output': str(target), 'ffmpeg_log': str(log),
            'review': 'technical full decode only; human visual/listening review pending'}
