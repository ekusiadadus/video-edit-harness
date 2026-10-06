"""Bindings and validation for first-retime temporal stage replay."""

from __future__ import annotations

import hashlib
import json
import re
from copy import deepcopy


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                     separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def new_plan_binding(events, mapping_sha256):
    """Bind canonical candidate events without their self-referential content maps."""
    return _digest({'version': 1, 'mapping_sha256': mapping_sha256,
                    'events': [{k: deepcopy(v) for k, v in event.items() if k != 'content_map'}
                               for event in events]})


def picture_binding(cfg):
    """Bind the picture-producing settings shared by migration and rendering."""
    if not isinstance(cfg, dict):
        raise ValueError('Picture binding requires project settings')
    keys = ('input_color', 'white_balance_gains', 'use_case', 'style',
            'style_intensity', 'adjustments', 'review_regions',
            'region_corrections', 'depth_layer', 'retime')
    picture = {key: deepcopy(cfg.get(key)) for key in keys}
    picture['visual_pipeline_version'] = cfg.get('visual_pipeline_version', 1)
    cues = cfg.get('cue_plan')
    if isinstance(cues, dict):
        picture['cue_plan'] = {key: deepcopy(value) for key, value in cues.items()
                               if key not in {'cues', 'events'}}
        for key in ('cues', 'events'):
            if isinstance(cues.get(key), list):
                picture['cue_plan'][key] = [deepcopy(row) for row in cues[key]
                                            if isinstance(row, dict) and row.get('role') in {'image', 'video', 'title'}]
    else:
        picture['cue_plan'] = None
    assets = cfg.get('assets') or []
    if not isinstance(assets, list):
        raise ValueError('Picture assets must be a list')
    picture['assets'] = [{key: deepcopy(row.get(key)) for key in ('asset_id', 'sha256', 'path', 'kind')}
                         for row in assets if isinstance(row, dict)]
    return _digest(picture)


def validate_content_map(content, event, rate, first, last):
    """Validate shape and old capture proof; plan-wide binding is checked later."""
    from .overlay_layers import validate_overlay_layer_reference
    from .video_effects import MAX_PHASE_FRAMES, _time, _canonical_event

    keys = {'version', 'original_sample', 'original_events', 'original_event',
            'frames', 'new_plan_sha256', 'project_picture_sha256'}
    if not isinstance(content, dict) or set(content) != keys or type(content['version']) is not int or content['version'] != 1:
        raise ValueError('Content map requires exact version and capture bindings')
    if event['type'] not in {'motion_trail', 'comparison_wipe'}:
        raise ValueError('Content map is unsupported for this effect type')
    for key in ('new_plan_sha256', 'project_picture_sha256'):
        if not isinstance(content[key], str) or not re.fullmatch(r'[0-9a-f]{64}', content[key]):
            raise ValueError(f'Content map {key} is invalid')
    sample = content['original_sample']
    required = {'event_id', 'type', 'original_start_frame', 'original_frame_count',
                'stage_ordinal', 'original_event_sha256', 'mapping_sha256',
                'input_sha256', 'capture_stage_version', 'stage_plan_sha256',
                'selected_asset_bindings', 'original_layer'}
    if not isinstance(sample, dict) or set(sample) != required:
        raise ValueError('Content map needs a complete successful original sample')
    old_events = content['original_events']
    old_event = content['original_event']
    if not isinstance(old_events, list) or not old_events or not isinstance(old_event, dict):
        raise ValueError('Content map needs canonical original events')
    if any(not isinstance(row, dict) or 'content_map' in row for row in old_events):
        raise ValueError('Original events cannot contain content maps')
    if sample['event_id'] != event['id'] or sample['type'] != event['type'] or old_event.get('id') != event['id']:
        raise ValueError('Content map event identity changed')
    if old_event not in old_events or _digest(old_event) != sample['original_event_sha256']:
        raise ValueError('Content map original event changed')
    if any(old_event.get(key) != event.get(key) for key in ('id', 'type', 'strength', 'reason', 'effect_version', 'parameters')):
        raise ValueError('Content map original effect parameters changed')
    if (type(sample['original_start_frame']) is not int or sample['original_start_frame'] < 0
            or type(sample['original_frame_count']) is not int
            or not 1 <= sample['original_frame_count'] <= MAX_PHASE_FRAMES
            or type(sample['capture_stage_version']) is not int
            or sample['capture_stage_version'] != 1):
        raise ValueError('Content map original frame window is invalid')
    old_start = _time(old_event['output_start'], 'old start') * rate
    old_end = _time(old_event['output_end'], 'old end') * rate
    if old_start.denominator != 1 or old_end.denominator != 1:
        raise ValueError('Content map original event is not frame aligned')
    old_first, old_last = int(old_start), int(old_end)
    if old_first != sample['original_start_frame'] or old_last - old_first != sample['original_frame_count']:
        raise ValueError('Content map original event window changed')
    from .video_effects import _canonical_event
    if _canonical_event(old_event, rate, old_last) != old_event:
        raise ValueError('Content map original event is not canonical')
    stage_order = [row for row in old_events if row['type'] == 'motion_trail'] + [row for row in old_events if row['type'] == 'comparison_wipe']
    if stage_order.index(old_event) != sample['stage_ordinal'] or type(sample['stage_ordinal']) is not int:
        raise ValueError('Content map stage order changed')
    for key in ('mapping_sha256', 'input_sha256', 'stage_plan_sha256', 'original_event_sha256'):
        if not isinstance(sample[key], str) or not re.fullmatch(r'[0-9a-f]{64}', sample[key]):
            raise ValueError('Content map capture digest is invalid')
    bindings = sample['selected_asset_bindings']
    if (not isinstance(bindings, list) or any(
            not isinstance(row, dict) or set(row) != {'asset_id', 'sha256', 'bytes', 'event_id'}
            or not isinstance(row['asset_id'], str) or not row['asset_id']
            or not isinstance(row['event_id'], str) or not row['event_id']
            or not isinstance(row['sha256'], str) or not re.fullmatch(r'[0-9a-f]{64}', row['sha256'])
            or type(row['bytes']) is not int or row['bytes'] <= 0 for row in bindings)):
        raise ValueError('Content map asset bindings are invalid')
    expected = _digest({'version': 1, 'events': old_events,
                        'mapping_sha256': sample['mapping_sha256'],
                        'input_sha256': sample['input_sha256'],
                        'selected_asset_bindings': bindings})
    if expected != sample['stage_plan_sha256']:
        raise ValueError('Content map original stage plan changed')
    if event['type'] == 'comparison_wipe':
        matching = [row for row in bindings if row.get('event_id') == event['id']]
        if len(matching) != 1 or matching[0].get('asset_id') != event['parameters']['asset_id'] or matching[0].get('sha256') != event['parameters']['asset_sha256']:
            raise ValueError('Content map comparison asset changed')
    validate_overlay_layer_reference(sample['original_layer'], rate, count=sample['original_frame_count'])
    frames = content['frames']
    if not isinstance(frames, list) or len(frames) != last - first or not 1 <= len(frames) <= MAX_PHASE_FRAMES:
        raise ValueError('Content map frame count differs from mapped window')
    if any(type(index) is not int or not 0 <= index < sample['original_frame_count'] for index in frames):
        raise ValueError('Content map frame index is outside original capture')
    if any(left > right for left, right in zip(frames, frames[1:])):
        raise ValueError('Content map frames must be nondecreasing')
    return deepcopy(content)


def validate_retime_selections(events, compiled_mapping, original_mapping_sha256):
    """Compare replay membership with the verified picture retime, not metadata alone."""
    from fractions import Fraction
    for event in events:
        content = event.get('content_map')
        if content is None:
            continue
        sample = content['original_sample']
        if sample['mapping_sha256'] != original_mapping_sha256:
            raise ValueError('Temporal replay original mapping changed')
        first = sample['original_start_frame']
        end = first + sample['original_frame_count']
        if not 0 <= first < end <= compiled_mapping['input_frame_count']:
            raise ValueError('Temporal replay original window exceeds verified input')
        frame_map = compiled_mapping['frame_map']
        selected = [(j, frame-first) for j, frame in enumerate(frame_map) if first <= frame < end]
        rate = Fraction(compiled_mapping['fps'])
        if (not selected or selected[-1][0]-selected[0][0]+1 != len(selected)
                or content['frames'] != [frame for _, frame in selected]
                or Fraction(event['output_start'])*rate != selected[0][0]
                or Fraction(event['output_end'])*rate != selected[-1][0]+1):
            raise ValueError('Temporal replay frame selection differs from verified picture retime')
