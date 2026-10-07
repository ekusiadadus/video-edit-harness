"""Conservative semantic readback of a layered Final Cut Pro XML handoff.

Resource IDs, file locations and display names can change on FCP export. This
reader identifies local media by SHA-256 and rejects structural changes it
cannot map back to a timeline-bound cue plan. It never claims GUI playback.
"""

from __future__ import annotations

from copy import deepcopy
from decimal import Decimal, InvalidOperation
from fractions import Fraction
from pathlib import Path
import hashlib
import math
import shutil
import subprocess
import tempfile
import xml.etree.ElementTree as ET

from .cues import _asset_map, _check_asset, validate_cues
from .overlay_placement import parse_static_placement
from .production_fcp import (DTD_PATHS, FCP_FRAME_SAMPLING, FCP_SOURCE_RATES, _fcp_time,
                             _read_time, resolve_media_path, validate_still_resource)


ACTORS = {'human', 'codex', 'claude_code', 'automation'}
STRUCTURE = {'fcpxml', 'import-options', 'option', 'resources', 'format', 'asset',
             'media-rep', 'library', 'event', 'project', 'sequence', 'spine',
             'asset-clip', 'conform-rate', 'marker', 'adjust-volume', 'param',
             'fadeIn', 'fadeOut', 'note', 'metadata', 'md', 'array',
             'bookmark', 'smart-collection', 'match-media', 'match-clip',
             'match-ratings', 'match-analysis-type', 'adjust-colorConform',
             'adjust-conform', 'adjust-transform', 'adjust-blend'}
STRUCTURE.update({'keyframeAnimation', 'keyframe', 'video'})


def _xml_path(path):
    path = Path(path)
    if path.is_dir():
        if path.suffix != '.fcpxmld':
            raise ValueError('Expected an FCPXML file or .fcpxmld bundle')
        path = path / 'Info.fcpxml'
    if not path.is_file():
        raise ValueError('FCPXML file is missing')
    return path


def _identity_color(node):
    if node.tag != 'adjust-colorConform' or list(node):
        return False
    if set(node.attrib) - {'enabled', 'autoOrManual', 'conformType',
                           'peakNitsOfPQSource', 'peakNitsOfSDRToPQSource'}:
        return False
    return (node.get('enabled') == '1' and node.get('autoOrManual') == 'manual'
            and node.get('conformType') == 'conformNone')


def _sha(path):
    value = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(4 * 1024 * 1024), b''):
            value.update(chunk)
    return value.hexdigest()


def _safe_xml(path):
    path = _xml_path(path)
    root = ET.parse(path).getroot()
    version = root.get('version')
    if root.tag != 'fcpxml' or version not in {'1.10', '1.12', '1.13', '1.14'}:
        raise ValueError('unsupported FCPXML version')
    suffix = version.replace('.', '_')
    dtd = next((candidate.with_name(f'FCPXMLv{suffix}.dtd') for candidate in DTD_PATHS
                if candidate.with_name(f'FCPXMLv{suffix}.dtd').is_file()), None)
    if version != '1.10' and (dtd is None or not shutil.which('xmllint')):
        raise ValueError(f'FCPXML {version} requires its installed Apple DTD and xmllint')
    if dtd is not None and shutil.which('xmllint'):
        with tempfile.TemporaryDirectory(prefix='production-import-dtd-') as tmp:
            alias = Path(tmp) / 'fcp.dtd'
            alias.symlink_to(dtd)
            checked = subprocess.run(['xmllint', '--noout', '--dtdvalid', str(alias), str(path)],
                                     capture_output=True, text=True)
            if checked.returncode:
                raise ValueError(f'FCPXML {version} DTD invalid: {checked.stderr[-600:]}')
    parent = {child: node for node in root.iter() for child in node}
    project_spine = root.find('./library/event/project/sequence/spine')
    for node in root.iter('video'):
        owner = parent.get(node)
        if owner is None or owner.tag != 'asset-clip' or parent.get(owner) is not project_spine:
            raise ValueError('still video is outside a connected clip')
    for animation in root.iter('keyframeAnimation'):
        param = parent.get(animation)
        volume = parent.get(param)
        connected = parent.get(volume)
        primary = parent.get(connected)
        if (param is None or param.tag != 'param' or volume is None or volume.tag != 'adjust-volume'
                or connected is None or connected.tag != 'asset-clip'
                or primary is None or primary.tag != 'asset-clip'
                or parent.get(primary) is not project_spine):
            raise ValueError('audio animation outside connected clip volume')
    for frame in root.iter('keyframe'):
        if parent.get(frame) is None or parent[frame].tag != 'keyframeAnimation':
            raise ValueError('orphan audio keyframe')
    for node in root.iter():
        if node.tag in {'adjust-conform', 'adjust-transform', 'adjust-blend'}:
            owner = parent.get(node)
            anchor = parent.get(owner)
            spine_owner = parent.get(anchor)
            if (owner is None or owner.tag not in {'asset-clip', 'video'}
                    or owner.tag == 'asset-clip' and owner.get('srcEnable') != 'video'
                    or anchor is None or anchor.tag != 'asset-clip'
                    or spine_owner is None or spine_owner is not project_spine):
                raise ValueError('unsupported visual placement location')
            order = [child.tag for child in owner if child.tag in
                     {'adjust-conform', 'adjust-transform', 'adjust-blend'}]
            if order != ['adjust-conform', 'adjust-transform', 'adjust-blend']:
                raise ValueError('unsupported visual placement order')
            parse_static_placement(owner)
        if node.tag == 'bookmark' and parent[node].tag != 'media-rep':
            raise ValueError('unsupported bookmark location')
        if node.tag == 'smart-collection' and parent[node].tag not in {'library', 'event'}:
            raise ValueError('unsupported smart collection location')
        if node.tag.startswith('match-') and parent[node].tag != 'smart-collection':
            raise ValueError('unsupported smart collection rule location')
        if node.tag == 'adjust-colorConform' and (parent[node].tag not in {'asset-clip', 'video'} or not _identity_color(node)):
            raise ValueError('non-identity color conform is unsupported')
        if node.tag in STRUCTURE:
            continue
        cursor = parent.get(node)
        while cursor is not None and cursor.tag != 'metadata':
            cursor = parent.get(cursor)
        if cursor is None:
            raise ValueError(f'unsupported FCPXML structure: {node.tag}')
    projects = root.findall('./library/event/project')
    if len(projects) != 1:
        raise ValueError('expected exactly one flat project')
    sequence = projects[0].find('sequence')
    if sequence is None or sequence.find('spine') is None:
        raise ValueError('project sequence/spine is missing')
    if len(root.findall('.//project')) != 1:
        raise ValueError('nested or additional projects are unsupported')
    return root, sequence, sequence.find('spine')


def _conform(clip, source_rate, output_rate):
    nodes = clip.findall('conform-rate')
    if len(nodes) > 1 or bool(nodes) != (source_rate != output_rate):
        raise ValueError('source frame-rate conform structure changed')
    if not nodes:
        return None
    node = nodes[0]
    if set(node.attrib) - {'scaleEnabled', 'srcFrameRate', 'frameSampling'}:
        raise ValueError('unknown frame conform attribute')
    scale = node.get('scaleEnabled', '1')
    sampling = node.get('frameSampling', 'floor')
    if scale not in {'0', '1'} or sampling not in FCP_FRAME_SAMPLING:
        raise ValueError('invalid frame conform value')
    label = FCP_SOURCE_RATES.get(source_rate)
    if node.get('srcFrameRate') is not None and node.get('srcFrameRate') != label:
        raise ValueError('frame conform disagrees with source format')
    return {'scaleEnabled': scale, 'frameSampling': sampling,
            'srcFrameRate': label}


def _volume(clip, src_enable=None):
    nodes = clip.findall('adjust-volume')
    if len(nodes) > 1:
        raise ValueError('multiple volume adjustments are unsupported')
    if not nodes:
        return {'gain_db': 0.0, 'fade_in': Fraction(0), 'fade_out': Fraction(0),
                'automation': None, 'volume_present': False}
    node = nodes[0]
    if set(node.attrib) - {'amount'}:
        raise ValueError('unknown volume adjustment attribute')
    amount = node.get('amount', '0dB')
    if not amount.endswith('dB'):
        raise ValueError('unknown volume amount unit')
    try:
        gain = float(amount[:-2])
    except ValueError as exc:
        raise ValueError('invalid volume amount') from exc
    if not math.isfinite(gain) or not -120 <= gain <= 24:
        raise ValueError('volume gain outside supported range')
    children = list(node)
    if len(children) > 1 or any(item.tag != 'param' or item.get('name') != 'amount' for item in children):
        raise ValueError('audio automation beyond edge fades is unsupported')
    fades = {'fadeIn': Fraction(0), 'fadeOut': Fraction(0)}
    automation = None
    if children:
        animations = children[0].findall('keyframeAnimation')
        if animations:
            if (src_enable != 'audio' or node.attrib != {'amount': '0dB'}
                    or children[0].attrib != {'name': 'amount'}
                    or len(children[0]) != 1 or len(animations) != 1
                    or children[0][0] is not animations[0] or animations[0].attrib):
                raise ValueError('unsupported audio keyframe placement')
            start = _read_time(clip.get('start', '0s'))
            end = start + _read_time(clip.get('duration'))
            points = []
            for frame in animations[0]:
                if (frame.tag != 'keyframe' or len(frame) or
                        set(frame.attrib) not in ({'time', 'value', 'curve'}, {'time', 'value', 'interp', 'curve'}) or
                        frame.get('interp', 'linear') != 'linear' or frame.get('curve') != 'linear'):
                    raise ValueError('unsupported audio keyframe attributes')
                instant = _read_time(frame.get('time'))
                value = frame.get('value', '')
                if not value.endswith('dB'):
                    raise ValueError('unsupported audio keyframe unit')
                try:
                    decibels = Decimal(value[:-2])
                except InvalidOperation as exc:
                    raise ValueError('invalid audio keyframe gain') from exc
                if (not decibels.is_finite() or not Decimal(-96) <= decibels <= Decimal(24)
                        or not start <= instant < end
                        or points and instant <= points[-1][0]):
                    raise ValueError('invalid audio keyframe time or gain')
                points.append((instant, decibels))
            if not points or len(points) > 20000 or points[0][0] != start:
                raise ValueError('invalid audio keyframe coverage')
            automation = tuple(points)
            return {'gain_db': gain, 'fade_in': Fraction(0), 'fade_out': Fraction(0),
                    'automation': automation, 'volume_present': True}
        if any(item.tag not in fades or set(item.attrib) - {'duration', 'type'} for item in children[0]):
            raise ValueError('unknown volume automation')
        for item in children[0]:
            if fades[item.tag] != 0 or item.get('type', 'linear') not in {'linear', 'easeIn', 'easeOut', 'easeInOut'}:
                raise ValueError('duplicate or unknown volume fade')
            fades[item.tag] = _read_time(item.get('duration'))
    return {'gain_db': gain, 'fade_in': fades['fadeIn'], 'fade_out': fades['fadeOut'],
            'automation': automation, 'volume_present': True}


def _snapshot(path):
    path = _xml_path(path)
    root, sequence, spine = _safe_xml(path)
    resources = root.find('resources')
    if resources is None:
        raise ValueError('resources missing')
    formats = {item.get('id'): item for item in resources.findall('format')}
    assets = {}
    for item in resources.findall('asset'):
        identifier = item.get('id')
        if not identifier or identifier in assets:
            raise ValueError('duplicate/empty asset ID')
        reps = item.findall('media-rep')
        if len(reps) != 1 or reps[0].get('kind') != 'original-media':
            raise ValueError('asset needs one original media reference')
        media = resolve_media_path(reps[0].get('src', ''), path)
        if not media.is_file():
            raise ValueError('referenced local asset is missing')
        asset_format = formats.get(item.get('format'))
        still = asset_format is not None and asset_format.get('frameDuration') is None
        if still:
            validate_still_resource(item, formats, media)
        assets[identifier] = {'sha256': _sha(media), 'path': str(media),
                              'still': still,
                              'has_video': item.get('hasVideo') == '1',
                              'has_audio': item.get('hasAudio') == '1',
                              'source_fps': 1 / _read_time(asset_format.get('frameDuration')) if asset_format is not None and not still else None,
                              'width': asset_format.get('width') if asset_format is not None else None,
                              'height': asset_format.get('height') if asset_format is not None else None}
    output_format = formats.get(sequence.get('format'))
    if output_format is None:
        raise ValueError('sequence format missing')
    output = {'fps': 1 / _read_time(output_format.get('frameDuration')),
              'width': output_format.get('width'), 'height': output_format.get('height'),
              'duration': _read_time(sequence.get('duration')),
              'audio_rate': sequence.get('audioRate'), 'audio_layout': sequence.get('audioLayout')}
    primary, connected, markers = [], [], []
    for clip in spine:
        if clip.tag != 'asset-clip' or clip.get('ref') not in assets or clip.get('lane') is not None:
            raise ValueError('unsupported primary timeline layer')
        resource = assets[clip.get('ref')]
        if not resource['has_video'] or resource['source_fps'] is None:
            raise ValueError('primary clip must be video')
        start = _read_time(clip.get('start', '0s'))
        offset = _read_time(clip.get('offset', '0s'))
        length = _read_time(clip.get('duration'))
        if length <= 0:
            raise ValueError('empty primary clip')
        primary.append({'sha256': resource['sha256'], 'source_start': start,
                        'output_start': offset, 'duration': length,
                        'src_enable': clip.get('srcEnable', 'all'),
                        'source_fps': resource['source_fps'],
                        'source_size': (resource['width'], resource['height']),
                        'conform': _conform(clip, resource['source_fps'], output['fps'])})
        for child in clip:
            if child.tag in {'conform-rate', 'note', 'metadata', 'adjust-colorConform'}:
                continue
            if child.tag == 'marker':
                if set(child.attrib) - {'start', 'duration', 'value', 'completed', 'note'}:
                    raise ValueError('unknown marker attribute')
                global_time = offset + _read_time(child.get('start')) - start
                if not 0 <= global_time < output['duration']:
                    raise ValueError('marker outside output timeline')
                markers.append({'output_time': global_time, 'value': child.get('value')})
                continue
            if child.tag not in {'asset-clip', 'video'}:
                raise ValueError(f'unsupported connected layer: {child.tag}')
            reference = assets.get(child.get('ref'))
            if reference is None:
                raise ValueError('connected layer asset missing')
            if child.get('lane') is None:
                raise ValueError('connected layer lacks lane')
            if any(node.tag not in {'adjust-volume', 'conform-rate', 'note', 'metadata',
                                    'adjust-colorConform', 'adjust-conform', 'adjust-transform',
                                    'adjust-blend'} for node in child):
                raise ValueError('connected effect unsupported')
            start_output = offset + _read_time(child.get('offset')) - start
            clip_length = _read_time(child.get('duration'))
            if start_output < 0 or clip_length <= 0 or start_output + clip_length > output['duration']:
                raise ValueError('connected layer outside output timeline')
            source_fps = reference['source_fps']
            src_enable = child.get('srcEnable')
            if child.tag == 'video':
                if (not reference['still'] or set(child.attrib) -
                        {'ref', 'name', 'lane', 'offset', 'start', 'duration'}):
                    raise ValueError('unsupported still connection')
                src_enable = 'video'
            # FCP 1.14 can omit srcEnable on an audio-only resource. In that
            # case the media has no video stream to re-enable. Never make this
            # inference for a primary or a source with both audio and video.
            if src_enable is None and reference['has_audio'] and not reference['has_video']:
                src_enable = 'audio'
            if src_enable == 'video':
                if not reference['has_video'] or source_fps is None and not reference['still']:
                    raise ValueError('visual layer does not reference video/image')
                if reference['still']:
                    if child.find('conform-rate') is not None:
                        raise ValueError('still connection cannot have conform-rate')
                    conform = None
                else:
                    conform = _conform(child, source_fps, output['fps'])
            elif src_enable == 'audio':
                if not reference['has_audio'] or child.find('conform-rate') is not None:
                    raise ValueError('audio layer has unsupported source/conform')
                conform = None
            else:
                raise ValueError('connected layer source enable is ambiguous')
            if src_enable == 'video' and child.find('adjust-volume') is not None:
                raise ValueError('visual layer cannot carry audio volume')
            placement = parse_static_placement(child)
            if src_enable == 'audio' and placement is not None:
                raise ValueError('audio layer cannot carry visual placement')
            volume = _volume(child, src_enable)
            connected.append({'sha256': reference['sha256'], 'name': child.get('name'),
                              'role': child.get('audioRole') if src_enable == 'audio' else ('video' if child.tag == 'video' else child.get('videoRole')),
                              'src_enable': src_enable, 'lane': child.get('lane'),
                              'output_start': start_output, 'source_start': _read_time(child.get('start', '0s')),
                              'duration': clip_length, 'conform': conform,
                              'source_size': (reference['width'], reference['height']) if src_enable == 'video' else None,
                              'placement': placement, **volume})
    if not primary:
        raise ValueError('empty primary timeline')
    if output['duration'] != sum((row['duration'] for row in primary), Fraction(0)):
        raise ValueError('primary timeline duration changed or has gaps')
    cursor = Fraction(0)
    for row in primary:
        if row['output_start'] != cursor:
            raise ValueError('primary timeline has gap, overlap or reorder')
        cursor += row['duration']
    return {'output': output, 'primary': primary, 'connected': connected, 'markers': markers}


def _primary_semantic(row):
    return {key: value for key, value in row.items() if key != 'src_enable'}


def _signature(row):
    return (row['sha256'], row['src_enable'], row['role'], row['lane'])


def _retained_dialogue(reference, returned):
    """Keep measured dialogue separate from production cues and compare exactly."""
    original = [row for row in reference['connected'] if row['role'] == 'dialogue']
    imported = [row for row in returned['connected'] if row['role'] == 'dialogue']
    if len(original) != len(imported) or len(original) > 1:
        raise ValueError('retained dialogue layer missing, duplicated or added')
    if original:
        before = {key: value for key, value in original[0].items() if key != 'name'}
        after = {key: value for key, value in imported[0].items() if key != 'name'}
        if before != after or original[0]['src_enable'] != 'audio':
            raise ValueError('retained dialogue source, range, role or guard changed')
    return ([row for row in reference['connected'] if row['role'] != 'dialogue'],
            [row for row in returned['connected'] if row['role'] != 'dialogue'], bool(original))


def _match_editable(reference, returned, production):
    if not production.get('mapping_sha256'):
        raise ValueError('production mapping hash missing; cannot bind imported cues')
    assets = _asset_map(production.get('assets', []))
    for record in assets.values():
        _check_asset(record['asset_id'], assets)
    cues = production.get('cues', [])
    reference_cues, returned_cues, has_dialogue = _retained_dialogue(reference, returned)
    measured = any(row['automation'] is not None for row in reference_cues)
    if measured and not has_dialogue:
        raise ValueError('measured cue automation lacks retained dialogue')
    if has_dialogue and (not measured or any(
            row['automation'] is None for row in reference_cues if row['role'] in {'music', 'effects'})):
        raise ValueError('retained dialogue lacks complete cue automation')
    expected_by_id = {}
    for row in reference_cues:
        name = row.get('name')
        if name not in {cue['id'] for cue in cues}:
            raise ValueError('reference XML cue names do not bind to production')
        expected_by_id.setdefault(name, []).append(row)
    if set(expected_by_id) != {cue['id'] for cue in cues}:
        raise ValueError('reference XML cue set differs from production')
    signatures = {}
    for cue in cues:
        group = expected_by_id[cue['id']]
        kinds = {_signature(row) for row in group}
        if len(kinds) != 1:
            raise ValueError('reference cue has mixed media/roles')
        signature = kinds.pop()
        if signature in signatures:
            raise ValueError('same asset/role/lane used by multiple cues; import ambiguous')
        signatures[signature] = cue['id']
        if cue.get('asset_id') and signature[0] != assets[cue['asset_id']]['sha256']:
            raise ValueError('reference cue media differs from registered asset')
    returned_by_id = {cue['id']: [] for cue in cues}
    for row in returned_cues:
        cue_id = signatures.get(_signature(row))
        if cue_id is None:
            raise ValueError('new, missing or role-changed layer cannot be mapped')
        returned_by_id[cue_id].append(row)
    reference_order = [cue_id for cue_id in sorted(expected_by_id,
        key=lambda identifier: (min(row['output_start'] for row in expected_by_id[identifier]),
                                identifier))]
    returned_order = [cue_id for cue_id in sorted(returned_by_id,
        key=lambda identifier: (min((row['output_start'] for row in returned_by_id[identifier]),
                                    default=Fraction(10**12)), identifier))]
    if reference_order != returned_order:
        raise ValueError('connected cue order changed; import unsupported')
    revised = []
    changes = []
    for cue in cues:
        cue_id = cue['id']
        before = sorted(expected_by_id[cue_id], key=lambda item: item['output_start'])
        after = sorted(returned_by_id[cue_id], key=lambda item: item['output_start'])
        if len(after) != len(before):
            raise ValueError(f'cue {cue_id} lost or gained a connected part')
        if any(row['conform'] != baseline['conform'] for row, baseline in zip(after, before)):
            raise ValueError(f'cue {cue_id} frame conform changed')
        if any(row['placement'] != baseline['placement'] or row['source_size'] != baseline['source_size']
               for row, baseline in zip(after, before)):
            raise ValueError(f'cue {cue_id} visual placement or source size changed; import unsupported')
        if any(row['source_start'] != baseline['source_start'] for row, baseline in zip(after, before)):
            raise ValueError(f'cue {cue_id} source in-point changed')
        if cue['role'] in {'music', 'sfx'} and measured:
            if any(baseline['automation'] is None for baseline in before):
                raise ValueError(f'cue {cue_id} has incomplete reference gain automation')
            audio_fields = ('output_start', 'source_start', 'duration', 'gain_db',
                            'fade_in', 'fade_out', 'automation', 'volume_present')
            if any(any(row[field] != baseline[field] for field in audio_fields)
                   for row, baseline in zip(after, before)):
                raise ValueError(f'cue {cue_id} measured audio automation or range changed')
        elif any(row['automation'] is not None or baseline['automation'] is not None
                 for row, baseline in zip(after, before)):
            raise ValueError(f'cue {cue_id} has unsupported audio automation')
        if len(after) > 1 and not cue.get('loop'):
            raise ValueError(f'cue {cue_id} was split without a loop contract')
        if len(after) > 1:
            span = before[0]['duration']
            if any(row['duration'] != span for row in after[:-1]):
                raise ValueError(f'cue {cue_id} loop period changed')
            if any(after[i+1]['output_start'] != after[i]['output_start'] + after[i]['duration'] for i in range(len(after)-1)):
                raise ValueError(f'cue {cue_id} loop has gaps or overlaps')
            if after[-1]['duration'] > span:
                raise ValueError(f'cue {cue_id} final loop part exceeds source period')
        if len({row['gain_db'] for row in after}) != 1:
            raise ValueError(f'cue {cue_id} has unsupported per-part gain automation')
        if any(row['fade_in'] or row['fade_out'] for row in after[1:-1]):
            raise ValueError(f'cue {cue_id} has unsupported mid-loop fade')
        updated = deepcopy(cue)
        # Generated measured audio uses sample-rounded XML ranges. Equal XML
        # readback proves the audio stayed put; keep the original cue intent.
        if not (measured and cue['role'] in {'music', 'sfx'}):
            updated['output_start'] = float(after[0]['output_start'])
            updated['output_end'] = float(after[-1]['output_start'] + after[-1]['duration'])
        if cue['role'] in {'music', 'sfx'}:
            if not measured:
                updated['gain_db'] = after[0]['gain_db']
                updated['fade_in'] = float(after[0]['fade_in'])
                updated['fade_out'] = float(after[-1]['fade_out'])
                if len(after) == 1 and not cue.get('loop'):
                    updated['source_end'] = float(after[0]['source_start'] + after[0]['duration'])
        elif cue['role'] == 'video':
            if after[0]['duration'] != before[0]['duration']:
                updated['source_end'] = float(after[0]['source_start'] + after[0]['duration'])
        if updated != cue:
            changes.append({'cue_id': cue_id, 'before': cue, 'after': updated})
        revised.append(updated)
    before_markers = {row['value']: row['output_time'] for row in reference['markers']}
    after_markers = {row['value']: row['output_time'] for row in returned['markers']}
    if len(before_markers) != len(reference['markers']) or set(before_markers) != set(after_markers):
        raise ValueError('beat marker set changed or duplicated')
    for cue in revised:
        label = f"Beat: {cue['id']}"
        if label in before_markers:
            anchor = after_markers[label]
            if not Fraction(str(cue['output_start'])) <= anchor < Fraction(str(cue['output_end'])):
                raise ValueError('moved beat marker is outside its cue')
            if before_markers[label] != anchor:
                cue['beat_anchor'] = float(anchor)
                changes.append({'cue_id': cue['id'], 'beat_anchor_before': float(before_markers[label]),
                                'beat_anchor_after': float(anchor)})
    revised = validate_cues(revised, assets, returned['output']['duration'], returned['output']['fps'])
    return {'version': 1, 'mapping_sha256': production['mapping_sha256'], 'cues': revised}, changes


def import_production_xml(reference_xml, returned_xml, production, actor, note):
    """Return a review-required cue revision or a read-only mix comparison."""
    if actor not in ACTORS or not isinstance(note, str) or not note.strip():
        raise ValueError('production import needs the real actor and decision reason')
    reference_xml = _xml_path(reference_xml)
    returned_xml = _xml_path(returned_xml)
    report = {'status': 'rejected', 'actor': actor, 'reason': note,
              'reference_xml_sha256': _sha(reference_xml),
              'returned_xml_sha256': _sha(returned_xml),
              'gui_import': 'unverified', 'gui_playback': 'unverified',
              'cue_plan': None, 'changes': [], 'reasons': []}
    try:
        reference = _snapshot(reference_xml)
        returned = _snapshot(returned_xml)
        if reference['output'] != returned['output']:
            raise ValueError('project output format or duration changed')
        if len(reference['primary']) != len(returned['primary']):
            raise ValueError('source cut count changed; transcript/visual mapping cannot be reused')
        for old, new in zip(reference['primary'], returned['primary']):
            if _primary_semantic(old) != _primary_semantic(new) or old['src_enable'] != new['src_enable']:
                raise ValueError('source cuts or frame mapping changed; import unsupported')
        is_mix = (len(reference['connected']) == 1 and
                  reference['connected'][0]['role'] == 'dialogue' and
                  all(row['src_enable'] == 'video' for row in reference['primary']))
        report['mode'] = 'mix' if is_mix else 'editable'
        if is_mix:
            if len(returned['connected']) != 1:
                raise ValueError('mixed PCM layer missing or duplicated')
            old, new = reference['connected'][0], returned['connected'][0]
            if _signature(old) != _signature(new) or old['source_start'] != new['source_start']:
                raise ValueError('mixed PCM resource or role changed')
            if old['automation'] is not None or new['automation'] is not None:
                raise ValueError('mixed PCM keyframe automation is unsupported')
            if reference['markers'] != returned['markers']:
                raise ValueError('mix marker structure changed')
            fields = ('output_start', 'duration', 'gain_db', 'fade_in', 'fade_out')
            delta = {field: {'before': str(old[field]), 'after': str(new[field])}
                     for field in fields if old[field] != new[field]}
            report.update(status='comparison_only', changes=[delta] if delta else [],
                          scope='finished mix comparison only; no original word or cue mapping')
            return report
        cue_plan, changes = _match_editable(reference, returned, production)
        measured = any(row['automation'] is not None for row in reference['connected'])
        report.update(status='review_required', cue_plan=cue_plan, changes=changes,
                      scope=('unchanged primary cuts and measured audio; supported visual cues and beat markers'
                             if measured else 'unchanged primary cuts; connected cue gain/fades/timing and beat markers'))
        return report
    except (ValueError, KeyError, TypeError, ET.ParseError) as exc:
        report['reasons'].append(str(exc))
        return report
