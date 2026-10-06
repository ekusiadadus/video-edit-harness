"""Explicit FCPXML handoff modes for optional production layers.

This module does not decide rights. Callers must check embedded use and, for
separate PCM/asset handoff, the relevant audio/raw handoff permission first.
DTD validity and structural readback are not Final Cut Pro GUI import proof.
"""

from __future__ import annotations

from fractions import Fraction
from pathlib import Path
from urllib.parse import unquote, urlparse
import hashlib
import json
import math
import subprocess
import tempfile
import wave
import xml.etree.ElementTree as ET
from PIL import Image

from .cues import _asset_map, _check_asset, _seconds, validate_cues
from .overlay_placement import (check_overlay_video_clock, check_video_geometry,
                                measure_placement, parse_static_placement, xml_number)
from .visual import _title_image

MIX_RATE = 48000


DTD_PATHS = (
    Path('/Applications/Final Cut Pro Creator Studio.app/Contents/Frameworks/Interchange.framework/Versions/A/Resources/FCPXMLv1_10.dtd'),
    Path('/Applications/Final Cut Pro.app/Contents/Frameworks/Interchange.framework/Versions/A/Resources/FCPXMLv1_10.dtd'),
)
SUPPORTED_TAGS = {'fcpxml', 'resources', 'format', 'asset', 'media-rep', 'library',
                  'event', 'project', 'sequence', 'spine', 'asset-clip', 'marker',
                  'adjust-volume', 'param', 'fadeIn', 'fadeOut', 'conform-rate',
                  'adjust-conform', 'adjust-transform', 'adjust-blend',
                  'keyframeAnimation', 'keyframe'}
FCP_SOURCE_RATES = {Fraction(24000, 1001): '23.98', Fraction(24): '24',
                    Fraction(25): '25', Fraction(30000, 1001): '29.97',
                    Fraction(30): '30', Fraction(60): '60',
                    Fraction(48000, 1001): '47.95', Fraction(48): '48',
                    Fraction(50): '50', Fraction(60000, 1001): '59.94'}
FCP_FRAME_SAMPLING = {'floor', 'nearest-neighbor', 'frame-blending',
                      'optical-flow-classic', 'optical-flow'}


def _fcp_time(value):
    value = Fraction(value)
    return f'{value.numerator}/{value.denominator}s' if value.denominator != 1 else f'{value.numerator}s'


def _read_time(value):
    if not value or not value.endswith('s'):
        raise ValueError('invalid FCP time')
    return _seconds(value[:-1], 'FCP time')


def resolve_media_path(uri, xml_path):
    """Resolve a local absolute file URI or bundle-contained relative media URI.

    A relative URI may be percent encoded but cannot escape the XML directory,
    including through symlinks. Network authorities and query/fragment parts are
    never valid media references for this local handoff.
    """
    parsed = urlparse(uri)
    if parsed.scheme not in {'', 'file'} or parsed.netloc or parsed.query or parsed.fragment:
        raise ValueError('media reference must be a local URI without query or fragment')
    decoded = unquote(parsed.path)
    if not decoded or '\x00' in decoded or '\\' in decoded:
        raise ValueError('invalid media reference path')
    parts = Path(decoded).parts
    if '..' in parts:
        raise ValueError('media reference path traversal')
    if parsed.scheme == 'file':
        if not Path(decoded).is_absolute():
            raise ValueError('file URI must be absolute')
        return Path(decoded).resolve()
    if Path(decoded).is_absolute():
        raise ValueError('relative media URI cannot be absolute')
    parent = Path(xml_path).resolve().parent
    resolved = (parent / decoded).resolve()
    if not resolved.is_relative_to(parent):
        raise ValueError('relative media URI escapes XML directory')
    return resolved


def _stream_info(path):
    import json
    value = subprocess.check_output(['ffprobe', '-v', 'error', '-show_streams', '-show_format',
                                     '-of', 'json', str(path)])
    return json.loads(value)


def _sound_duration(path):
    with wave.open(str(path), 'rb') as source:
        if source.getframerate() != 48000 or source.getnchannels() not in {1, 2} or source.getsampwidth() != 2:
            raise ValueError('mixed PCM must be 48 kHz 16-bit mono/stereo WAV')
        return Fraction(source.getnframes(), source.getframerate()), source.getnchannels()


def _sequence(root, *, allow_connected=False):
    if root.tag != 'fcpxml' or root.get('version') != '1.10':
        raise ValueError('production handoff needs flat FCPXML 1.10')
    sequence = root.find('./library/event/project/sequence')
    if sequence is None or sequence.find('spine') is None:
        raise ValueError('base XML has no single project sequence')
    spine = sequence.find('spine')
    if not list(spine) or any(item.tag != 'asset-clip' for item in spine):
        raise ValueError('base XML is not a flat asset-clip timeline')
    if not allow_connected and any(item.find('./asset-clip') is not None for item in spine):
        raise ValueError('base XML already has connected clips')
    return sequence, spine


def _add_asset(resources, identifier, path, kind, duration, *, channels=None):
    path = Path(path).resolve(strict=True)
    attrs = {'id': identifier, 'name': path.stem, 'start': '0s',
             'duration': _fcp_time(duration)}
    if kind in {'music', 'sfx', 'mix'}:
        if channels is None:
            stream = next((s for s in _stream_info(path)['streams'] if s['codec_type'] == 'audio'), None)
            if stream is None:
                raise ValueError(f'audio asset has no sound: {path}')
            channels = int(stream['channels'])
            sample_rate = int(stream['sample_rate'])
        else:
            sample_rate = 48000
        attrs.update(hasVideo='0', hasAudio='1', audioSources='1',
                     audioChannels=str(channels), audioRate=str(sample_rate))
    else:
        video_format = identifier + '_format'
        if kind == 'video':
            picture = next((s for s in _stream_info(path)['streams'] if s['codec_type'] == 'video'), None)
            if picture is None:
                raise ValueError('visual cue asset has no video')
            source_width, source_height = check_video_geometry(picture)
            source_rate = check_overlay_video_clock(path, picture)
            frame_duration = _fcp_time(1 / source_rate)
        else:
            with Image.open(path) as image:
                if image.getexif().get(274, 1) != 1:
                    raise ValueError('rotated image geometry is unsupported')
                source_width, source_height = image.size
            canvas_format = resources.find("format[@id='fmt']")
            frame_duration = canvas_format.get('frameDuration')
        ET.SubElement(resources, 'format', id=video_format,
                      frameDuration=frame_duration,
                      width=str(source_width), height=str(source_height))
        attrs.update(hasVideo='1', hasAudio='0', format=video_format)
    asset = ET.SubElement(resources, 'asset', attrs)
    ET.SubElement(asset, 'media-rep', kind='original-media', src=path.as_uri())
    return asset


def _anchor(spine, position):
    clips = list(spine)
    for clip in clips:
        offset = _read_time(clip.get('offset', '0s'))
        if offset <= position < offset + _read_time(clip.get('duration')):
            return clip
    if position == sum((_read_time(c.get('duration')) for c in clips), Fraction(0)):
        return clips[-1]
    raise ValueError('cue cannot be anchored on base timeline')


def _anchor_local_time(anchor, output_position):
    """Connected item times are local to the parent clip's source clock."""
    return (_read_time(anchor.get('start', '0s')) + output_position -
            _read_time(anchor.get('offset', '0s')))


def _validate_base(root, production):
    sequence, spine = _sequence(root)
    unknown = {node.tag for node in root.iter()} - SUPPORTED_TAGS
    if unknown:
        raise ValueError(f'base XML contains unsupported structure: {sorted(unknown)}')
    total = _read_time(sequence.get('duration'))
    if len(root.findall('./library/event/project')) != 1:
        raise ValueError('ambiguous base projects')
    if any(node.tag in {'timeMap', 'filter-video', 'filter-audio', 'transition', 'gap', 'title'}
           for node in root.iter()):
        raise ValueError('base XML has unsupported edits')
    if any(node.tag in {'adjust-conform', 'adjust-transform', 'adjust-blend'}
           for node in root.iter()):
        raise ValueError('base XML has unsupported spatial adjustments')
    _base_conform(root, sequence, spine)
    cues = validate_cues(production.get('cues', []), production.get('assets', []), total)
    return sequence, spine, total, cues


def _base_conform(root, sequence, spine):
    """Accept only explicit CFR conform nodes consistent with source formats."""
    resources = root.find('resources')
    if resources is None:
        raise ValueError('base XML lacks resources')
    formats = {item.get('id'): item for item in resources.findall('format')}
    assets = {item.get('id'): item for item in resources.findall('asset')}
    output_format = formats.get(sequence.get('format'))
    if output_format is None:
        raise ValueError('base XML output format is missing')
    output_rate = 1 / _read_time(output_format.get('frameDuration'))
    observed = []
    for clip in spine:
        asset = assets.get(clip.get('ref'))
        source_format = formats.get(asset.get('format')) if asset is not None else None
        if source_format is None:
            raise ValueError('primary clip source format is missing')
        source_rate = 1 / _read_time(source_format.get('frameDuration'))
        attributes = _check_conform_node(clip, source_rate, output_rate)
        observed.append({'source_fps': str(source_rate), 'output_fps': str(output_rate),
                         'conform': attributes})
    return observed


def _check_conform_node(clip, source_rate, output_rate):
    nodes = clip.findall('conform-rate')
    if len(nodes) > 1:
        raise ValueError('multiple conform-rate nodes on one clip')
    node = nodes[0] if nodes else None
    if source_rate == output_rate and node is not None:
        raise ValueError('same-rate clip has unnecessary conform-rate')
    if source_rate != output_rate and node is None:
        raise ValueError('mixed-rate clip lacks conform-rate')
    if node is None:
        return None
    if set(node.attrib) - {'scaleEnabled', 'srcFrameRate', 'frameSampling'}:
        raise ValueError('unsupported conform-rate attribute')
    if node.get('scaleEnabled', '1') not in {'0', '1'}:
        raise ValueError('invalid conform-rate scaleEnabled')
    if node.get('frameSampling', 'floor') not in FCP_FRAME_SAMPLING:
        raise ValueError('invalid conform-rate frameSampling')
    label = FCP_SOURCE_RATES.get(source_rate)
    if label is None and node.get('srcFrameRate') is not None:
        raise ValueError('srcFrameRate cannot express source rational FPS')
    if label is not None and node.get('srcFrameRate') not in {None, label}:
        raise ValueError('srcFrameRate disagrees with source format')
    return dict(node.attrib)


def _safe_name(name):
    return ''.join(ch if ch.isalnum() or ch in '-_' else '_' for ch in name)[:64]


def export_production_xml(base_xml, production, mixed_pcm, output, mode='mix', *,
                          gain_inputs=None):
    """Write one FCP handoff mode and return exact support/fidelity evidence.

    ``mix`` disables original audio and connects a full-length PCM replacement.
    ``editable`` keeps original speech and connects individually editable cues.
    ``video_only`` emits no XML; the caller packages its approved finished MP4.
    """
    if mode not in {'mix', 'editable', 'video_only'}:
        raise ValueError('unsupported production FCP mode')
    if gain_inputs is not None and mode != 'editable':
        raise ValueError('measured audio automation requires editable mode')
    if mode == 'editable' and production.get('depth_layer'):
        raise ValueError('Depth layer requires baked mix/video_only FCP handoff')
    output = Path(output)
    if mode == 'video_only':
        if output.exists():
            raise FileExistsError(output)
        return {'mode': mode, 'xml': None, 'assets': [], 'manual_remaining':
                ['Finished-video-only delivery; no editable Final Cut Pro project was generated.']}
    if output.exists():
        raise FileExistsError(output)
    root = ET.parse(base_xml).getroot()
    sequence, spine, total, cues = _validate_base(root, production)
    resources = root.find('resources')
    if resources is None or resources.find("format[@id='fmt']") is None:
        raise ValueError('base FCPXML format resource is unsupported')
    assets = _asset_map(production.get('assets', []))
    gain_manifest, gain_curves = None, None
    automation_evidence = []
    if gain_inputs is not None:
        from .audio_envelopes import load_audio_envelopes
        if (not isinstance(gain_inputs, dict) or
                set(gain_inputs) != {'folder', 'speech', 'mixed'} or
                gain_inputs['speech'] is None or gain_inputs['mixed'] is None):
            raise ValueError('measured audio automation needs bound mixer inputs')
        gain_manifest, gain_curves = load_audio_envelopes(
            gain_inputs['folder'], expected_cues=[cue for cue in cues if cue['role'] in {'music', 'sfx'}],
            expected_assets=assets, expected_speech=gain_inputs['speech'],
            expected_mixed_wav=gain_inputs['mixed'])
        if abs(Fraction(gain_manifest['samples'], MIX_RATE) - total) > Fraction(1, MIX_RATE):
            raise ValueError('audio automation duration differs from sequence')
    for cue in cues:
        if cue.get('asset_id'):
            _check_asset(cue['asset_id'], assets)
    manual = []
    resource_evidence = []
    if mode == 'mix':
        if mixed_pcm is None:
            raise ValueError('mix mode requires final mixed PCM')
        pcm = Path(mixed_pcm)
        pcm_duration, channels = _sound_duration(pcm)
        if abs(pcm_duration - total) > Fraction(1, 48000):
            raise ValueError('mixed PCM does not match base sequence duration')
        for clip in spine:
            clip.set('srcEnable', 'video')
        _add_asset(resources, 'production_mix', pcm, 'mix', pcm_duration, channels=channels)
        anchor = spine[0]
        ET.SubElement(anchor, 'asset-clip', ref='production_mix', name='Final PCM Mix',
                      lane='-1', offset=_fcp_time(_anchor_local_time(anchor, Fraction(0))),
                      start='0s', duration=_fcp_time(pcm_duration),
                      srcEnable='audio', audioRole='dialogue')
        resource_evidence.append({'id': 'production_mix', 'path': str(pcm.resolve()),
                                  'sha256': hashlib.sha256(pcm.read_bytes()).hexdigest()})
        manual.append('Compare FCP import and re-export audio with the reviewed PCM; XML validation alone does not establish playback fidelity.')
    else:
        # Rendered preview ducking and any adaptive RMS gain cannot be faithfully
        # represented by a static connected track. Preserve editable content and
        # make the remaining finishing explicit.
        pending_markers = []
        if gain_manifest is not None:
            speech = Path(gain_inputs['speech'])
            speech_duration, channels = _sound_duration(speech)
            if abs(speech_duration - total) > Fraction(1, MIX_RATE):
                raise ValueError('dialogue PCM does not match sequence duration')
            for clip in spine:
                clip.set('srcEnable', 'video')
            _add_asset(resources, 'production_dialogue', speech, 'mix', speech_duration, channels=channels)
            dialogue = ET.SubElement(spine[0], 'asset-clip', ref='production_dialogue',
                name='Measured Dialogue PCM', lane='-3',
                offset=_fcp_time(_anchor_local_time(spine[0], Fraction(0))),
                start='0s', duration=_fcp_time(min(total, speech_duration)),
                srcEnable='audio', audioRole='dialogue')
            guard_db = 20 * math.log10(gain_manifest['global_peak_guard_gain'])
            ET.SubElement(dialogue, 'adjust-volume', amount=f'{guard_db:.9f}dB')
            resource_evidence.append({'id': 'production_dialogue', 'path': str(speech.resolve()),
                'sha256': hashlib.sha256(speech.read_bytes()).hexdigest()})
            manual.append('Measured audio automation is pre-normalization; final loudness processing and FCP source-clock/interpolation playback calibration remain unverified. Do not treat this XML as the reviewed final mix.')
        for cue in cues:
            role = cue['role']
            identifier = 'prod_' + _safe_name(cue['id'])
            begin = _seconds(cue['output_start'], 'output_start')
            finish = _seconds(cue['output_end'], 'output_end')
            length = finish - begin
            if role == 'title':
                image_path = output.parent / (output.stem + '-' + _safe_name(cue['id']) + '-title.png')
                if image_path.exists():
                    raise FileExistsError(image_path)
                fmt = resources.find("format[@id='fmt']")
                _title_image(cue['text'], image_path, int(fmt.get('width')), int(fmt.get('height')))
                asset_path = image_path
                kind = 'image'
                manual.append(f"Title {cue['id']} is a raster overlay; edit text in the source design and regenerate.")
            else:
                asset_path = Path(assets[cue['asset_id']]['path'])
                kind = role
            info = _stream_info(asset_path) if kind in {'music', 'sfx', 'video'} else None
            if kind in {'music', 'sfx', 'video'}:
                media_duration = Fraction(str(info['format']['duration']))
                if _seconds(cue['source_end'], 'source_end') > media_duration + Fraction(1, 100):
                    raise ValueError('cue exceeds source media duration')
            else:
                media_duration = length
            _add_asset(resources, identifier, asset_path, kind, media_duration)
            resource_evidence.append({'id': identifier, 'path': str(asset_path.resolve()),
                                      'sha256': hashlib.sha256(asset_path.read_bytes()).hexdigest()})
            if role in {'music', 'sfx'}:
                if gain_manifest is not None:
                    row = next(item for item in gain_manifest['cues'] if item['cue']['id'] == cue['id'])
                    begin, finish = Fraction(row['first_sample'], MIX_RATE), min(total, Fraction(row['end_sample'], MIX_RATE))
                    length = finish - begin
                raw_span = _seconds(cue['source_end'], 'source_end') - _seconds(cue['source_start'], 'source_start')
                span = Fraction(round(float(raw_span) * MIX_RATE), MIX_RATE)
                periods = math.ceil(length / span) if cue['loop'] else 1
                if gain_manifest is not None and periods + len(automation_evidence) > 1000:
                    raise ValueError('measured audio exceeds connected part budget')
                if cue['loop'] and gain_manifest is None:
                    manual.append(f"Cue {cue['id']} uses butt-joined repeats in XML; preview loop crossfade needs FCP review.")
                for repeat in range(periods):
                    part_start = begin + repeat * span
                    part_length = min(span, finish - part_start)
                    if part_length <= 0:
                        break
                    if gain_manifest is not None and _seconds(cue['source_start'], 'source_start') + part_length > media_duration:
                        raise ValueError('measured audio part exceeds source media duration')
                    anchor = _anchor(spine, part_start)
                    node = ET.SubElement(anchor, 'asset-clip',
                                         ref=identifier, name=cue['id'], lane='-1' if role == 'music' else '-2',
                                         offset=_fcp_time(_anchor_local_time(anchor, part_start)),
                                         start=_fcp_time(_seconds(cue['source_start'], 'source_start')),
                                         duration=_fcp_time(part_length), srcEnable='audio',
                                         audioRole='music' if role == 'music' else 'effects')
                    amount = ET.SubElement(node, 'adjust-volume', amount=f"{float(_seconds(cue['gain_db'], 'gain_db')):.3f}dB")
                    if gain_manifest is not None:
                        from .audio_keyframes import compile_gain_keyframes
                        first = round((part_start - begin) * MIX_RATE)
                        last = first + round(part_length * MIX_RATE)
                        compiled = compile_gain_keyframes(gain_curves[cue['id']][first:last],
                            source_start=_seconds(cue['source_start'], 'source_start'),
                            scalar_gain=gain_manifest['global_peak_guard_gain'])
                        if sum(part['keyframes'] for part in automation_evidence) + len(compiled['keyframes']) > 200000:
                            raise ValueError('measured audio exceeds total keyframe budget')
                        amount.set('amount', '0dB')
                        animation = ET.SubElement(ET.SubElement(amount, 'param', name='amount'), 'keyframeAnimation')
                        for frame in compiled['keyframes']:
                            ET.SubElement(animation, 'keyframe', {key: frame[key] for key in ('time', 'value', 'interp', 'curve')})
                        automation_evidence.append({'cue_id': cue['id'], 'repeat': repeat,
                            'samples': compiled['samples'], 'keyframes': len(compiled['keyframes']),
                            'output_start': _fcp_time(part_start), 'source_start': node.get('start'),
                            'duration': node.get('duration'),
                            'keyframes_sha256': _animation_digest([{key: frame[key] for key in ('time', 'value', 'interp', 'curve')} for frame in compiled['keyframes']]),
                            'max_absolute_gain_error': compiled['max_absolute_gain_error'],
                            'zero_floor_db': compiled['zero_floor_db']})
                    elif repeat == 0 and float(_seconds(cue['fade_in'], 'fade_in')) or repeat == periods - 1 and float(_seconds(cue['fade_out'], 'fade_out')):
                        param = ET.SubElement(amount, 'param', name='amount')
                        if repeat == 0 and float(_seconds(cue['fade_in'], 'fade_in')):
                            ET.SubElement(param, 'fadeIn', duration=_fcp_time(_seconds(cue['fade_in'], 'fade_in')))
                        if repeat == periods - 1 and float(_seconds(cue['fade_out'], 'fade_out')):
                            ET.SubElement(param, 'fadeOut', duration=_fcp_time(_seconds(cue['fade_out'], 'fade_out')))
            else:
                if cue['loop']:
                    raise ValueError('visual cue loop cannot be represented in editable XML')
                anchor = _anchor(spine, begin)
                node = ET.SubElement(anchor, 'asset-clip', ref=identifier, name=cue['id'],
                              lane='1', offset=_fcp_time(_anchor_local_time(anchor, begin)),
                              start=_fcp_time(_seconds(cue['source_start'], 'source_start')) if role == 'video' else '0s',
                              duration=_fcp_time(length), srcEnable='video', videoRole='video')
                if role == 'video':
                    source_rate = Fraction(next(s for s in info['streams'] if s['codec_type'] == 'video')['r_frame_rate'])
                    fmt = resources.find("format[@id='fmt']")
                    output_rate = 1 / _read_time(fmt.get('frameDuration'))
                    if source_rate != output_rate:
                        attrs = {'scaleEnabled': '1'}
                        if source_rate in FCP_SOURCE_RATES:
                            attrs['srcFrameRate'] = FCP_SOURCE_RATES[source_rate]
                        ET.SubElement(node, 'conform-rate', attrs)
                source_format = resources.find(f"format[@id='{identifier}_format']")
                canvas_format = resources.find("format[@id='fmt']")
                placement = measure_placement(cue, int(canvas_format.get('width')),
                                              int(canvas_format.get('height')),
                                              int(source_format.get('width')),
                                              int(source_format.get('height')))
                ET.SubElement(node, 'adjust-conform', type='none')
                ET.SubElement(node, 'adjust-transform',
                              position=' '.join(xml_number(value) for value in placement['transform_position']),
                              scale=' '.join(xml_number(value) for value in placement['transform_scale']))
                ET.SubElement(node, 'adjust-blend', amount=xml_number(placement['opacity']))
                manual.append(f"Visual cue {cue['id']} has static placement; inspect FCP geometry, color and subject/subtitle clearance against preview.")
            if cue.get('beat_anchor') is not None:
                anchor_time = _seconds(cue['beat_anchor'], 'beat_anchor')
                if not begin <= anchor_time < finish:
                    raise ValueError('beat anchor outside cue')
                pending_markers.append((anchor_time, cue['id']))
            if cue.get('duck') and gain_manifest is None:
                manual.append(f"Cue {cue['id']} needs speech-linked ducking reapplied and listened to in FCP.")
        for anchor_time, cue_id in pending_markers:
            anchor = _anchor(spine, anchor_time)
            ET.SubElement(anchor, 'marker', start=_fcp_time(_anchor_local_time(anchor, anchor_time)),
                          value=f"Beat: {cue_id}")
        if gain_manifest is None and any(c['role'] in {'music', 'sfx'} for c in cues):
            manual.append('Static XML gains do not reproduce the preview mixer\'s measured relative gain or peak guard; compare and adjust final audio.')
        manual.append('Import in FCP, check role lanes, media relinking, overlays, fades, and re-export against the reviewed render.')
    if gain_manifest is not None:
        checked_manifest, _ = load_audio_envelopes(
            gain_inputs['folder'], expected_cues=[cue for cue in cues if cue['role'] in {'music', 'sfx'}],
            expected_assets=assets, expected_speech=gain_inputs['speech'],
            expected_mixed_wav=gain_inputs['mixed'])
        if checked_manifest['manifest_sha256'] != gain_manifest['manifest_sha256']:
            raise ValueError('audio automation inputs changed during export')
    output.parent.mkdir(parents=True, exist_ok=True)
    xml = ET.tostring(root, encoding='utf-8', xml_declaration=True)
    xml = xml.replace(b'?>\n', b'?>\n<!DOCTYPE fcpxml>\n', 1)
    with output.open('xb') as stream:
        stream.write(xml)
    dtd = next((path for path in DTD_PATHS if path.exists()), None)
    dtd_result = 'unavailable'
    if dtd:
        # xmllint treats a pathname containing spaces as a malformed DTD URI.
        # A temporary no-space symlink points at the installed Apple's DTD.
        with tempfile.TemporaryDirectory(prefix='fcp-dtd-') as tmp:
            alias = Path(tmp) / 'fcp.dtd'
            alias.symlink_to(dtd)
            process = subprocess.run(['xmllint', '--noout', '--dtdvalid', str(alias), str(output)],
                                     capture_output=True, text=True)
        if process.returncode:
            output.unlink()
            raise ValueError(f'generated XML fails FCPXML 1.10 DTD: {process.stderr[-1000:]}')
        dtd_result = 'passed'
    result = {'mode': mode, 'xml': str(output), 'duration': _fcp_time(total),
              'resources': resource_evidence, 'manual_remaining': manual,
              'dtd': dtd_result, 'gui_import': 'unverified'}
    if gain_manifest is not None:
        result['audio_automation'] = {'scope': 'pre_normalization',
            'status': 'pending_fcp_gui_calibration',
            'manifest_sha256': gain_manifest['manifest_sha256'],
            'global_peak_guard_gain': gain_manifest['global_peak_guard_gain'],
            'parts': automation_evidence, 'return_import': 'unsupported'}
    if mode == 'editable' and any(cue['role'] in {'image', 'video', 'title'} for cue in cues):
        result['placement_status'] = 'pending_fcp_gui_calibration'
        result['geometry_source'] = 'shared_preview_pixel_model'
    inspect_production_xml(output, expected=result)
    return result


def inspect_production_xml(path, expected=None):
    """Reject unknown structures and report exact connected media/fades/roles."""
    root = ET.parse(path).getroot()
    sequence, spine = _sequence(root, allow_connected=True)
    unknown = {node.tag for node in root.iter()} - SUPPORTED_TAGS
    if unknown:
        raise ValueError(f'unknown or unsupported FCPXML structure: {sorted(unknown)}')
    _validate_spatial_context(root, spine)
    _validate_audio_animation_context(root, spine)
    conform = _base_conform(root, sequence, spine)
    forbidden = {'timeMap', 'filter-video', 'filter-audio', 'transition', 'gap',
                 'sync-clip', 'multicam', 'mc-clip', 'ref-clip', 'title'}
    if any(node.tag in forbidden for node in root.iter()):
        raise ValueError('unknown or unsupported FCPXML structure cannot be silently dropped')
    resources = root.find('resources')
    if resources is None:
        raise ValueError('missing resources')
    asset_refs = {item.get('id'): item for item in resources.findall('asset')}
    format_refs = {item.get('id'): item for item in resources.findall('format')}
    output_rate = 1 / _read_time(format_refs[sequence.get('format')].get('frameDuration'))
    if None in asset_refs or len(asset_refs) != len(resources.findall('asset')):
        raise ValueError('duplicate/missing asset resource ID')
    resource_uris = {}
    for identifier, asset in asset_refs.items():
        reps = asset.findall('media-rep')
        if len(reps) != 1 or not reps[0].get('src'):
            raise ValueError('asset needs one local media reference')
        uri = reps[0].get('src')
        local = resolve_media_path(uri, path)
        if not local.is_file():
            raise ValueError('asset media reference is missing')
        resource_uris[identifier] = uri
    primary = []
    connected = []
    markers = []
    sequence_duration = _read_time(sequence.get('duration'))
    for clip_index, clip in enumerate(spine):
        if clip.get('ref') not in asset_refs:
            raise ValueError('missing primary media resource')
        parent_output = _read_time(clip.get('offset', '0s'))
        parent_start = _read_time(clip.get('start', '0s'))
        primary.append({'ref': clip.get('ref'), 'offset': clip.get('offset'),
                        'start': clip.get('start'), 'duration': clip.get('duration'),
                        'srcEnable': clip.get('srcEnable', 'all'),
                        'conform_rate': conform[clip_index]})
        for node in clip:
            if node.tag == 'conform-rate':
                continue
            if node.tag == 'marker':
                marker_local = _read_time(node.get('start'))
                marker_output = parent_output + marker_local - parent_start
                if not 0 <= marker_output < sequence_duration:
                    raise ValueError('marker resolves outside output timeline')
                markers.append({'start': node.get('start'),
                                'output_time': _fcp_time(marker_output),
                                'value': node.get('value')})
                continue
            if node.tag != 'asset-clip':
                raise ValueError(f'unknown primary clip child: {node.tag}')
            if node.get('ref') not in asset_refs or not node.get('lane'):
                raise ValueError('connected clip lacks resource/lane')
            if any(child.tag not in {'adjust-volume', 'conform-rate', 'adjust-conform',
                                    'adjust-transform', 'adjust-blend'} for child in node):
                raise ValueError('connected effect/structure is unsupported')
            spatial_order = [child.tag for child in node if child.tag in
                             {'adjust-conform', 'adjust-transform', 'adjust-blend'}]
            if spatial_order and spatial_order != ['adjust-conform', 'adjust-transform', 'adjust-blend']:
                raise ValueError('visual placement node order is unsupported')
            source_asset = asset_refs[node.get('ref')]
            connected_conform = None
            if node.get('srcEnable') not in {'video', 'audio'}:
                raise ValueError('connected clip source enable must be video or audio')
            video_format = None
            if node.get('srcEnable') == 'video':
                if not source_asset.get('format'):
                    raise ValueError('connected visual source format missing')
                video_format = format_refs.get(source_asset.get('format'))
                if video_format is None:
                    raise ValueError('connected visual source format missing')
                source_rate = 1 / _read_time(video_format.get('frameDuration'))
                connected_conform = _check_conform_node(node, source_rate, output_rate)
            elif node.find('conform-rate') is not None:
                raise ValueError('audio connection cannot have conform-rate')
            placement = parse_static_placement(node)
            if node.get('srcEnable') == 'audio' and placement is not None:
                raise ValueError('audio connection cannot have visual placement')
            if node.get('srcEnable') == 'video' and node.find('adjust-volume') is not None:
                raise ValueError('video connection cannot have audio volume')
            volume = node.find('adjust-volume')
            cue_output = parent_output + _read_time(node.get('offset')) - parent_start
            cue_duration = _read_time(node.get('duration'))
            if cue_output < 0 or cue_output + cue_duration > sequence_duration:
                raise ValueError('connected clip resolves outside output timeline')
            connected.append({'ref': node.get('ref'), 'name': node.get('name'),
                              'lane': node.get('lane'), 'offset': node.get('offset'),
                              'output_start': _fcp_time(cue_output),
                              'start': node.get('start'), 'duration': node.get('duration'),
                              'srcEnable': node.get('srcEnable'), 'audioRole': node.get('audioRole'),
                              'videoRole': node.get('videoRole'), 'conform_rate': connected_conform,
                              'placement': placement,
                              'source_size': ([int(video_format.get('width')), int(video_format.get('height'))]
                                              if node.get('srcEnable') == 'video' else None),
                              'gain': volume.get('amount') if volume is not None else None,
                              'audio_keyframes': _read_audio_animation(node),
                              'fade_in': volume.find('.//fadeIn').get('duration') if volume is not None and volume.find('.//fadeIn') is not None else None,
                              'fade_out': volume.find('.//fadeOut').get('duration') if volume is not None and volume.find('.//fadeOut') is not None else None})
    observed = {'duration': sequence.get('duration'), 'primary': primary,
                'connected': connected, 'markers': sorted(markers, key=lambda item: (item['start'], item['value'])),
                'asset_ids': sorted(asset_refs), 'resource_uris': resource_uris}
    if expected:
        required = {resource['id'] for resource in expected.get('resources', [])}
        actual = {node['ref'] for node in connected}
        if required != actual:
            raise ValueError(f'production XML resource mismatch: {required ^ actual}')
        if expected.get('audio_automation') is not None:
            parts = expected['audio_automation']['parts']
            dialogue = [item for item in connected if item['ref'] == 'production_dialogue']
            guard_db = 20 * math.log10(expected['audio_automation']['global_peak_guard_gain'])
            if (any(item['srcEnable'] != 'video' for item in primary) or len(dialogue) != 1 or
                    dialogue[0]['audioRole'] != 'dialogue' or dialogue[0]['gain'] != f'{guard_db:.9f}dB' or
                    dialogue[0]['audio_keyframes'] is not None):
                raise ValueError('measured dialogue or original audio muting changed')
            actual_parts = [item for item in connected if item['audioRole'] in {'music', 'effects'}]
            expected_signatures = sorted((part['cue_id'], part['output_start'], part['source_start'],
                part['duration'], part['keyframes_sha256']) for part in parts)
            actual_signatures = sorted((item['name'], item['output_start'], item['start'],
                item['duration'], _animation_digest(item['audio_keyframes'])) for item in actual_parts)
            if expected_signatures != actual_signatures:
                raise ValueError('measured audio automation differs from expected evidence')
        for item in expected.get('resources', []):
            local_path = resolve_media_path(resource_uris[item['id']], path)
            if not local_path.is_file() or hashlib.sha256(local_path.read_bytes()).hexdigest() != item['sha256']:
                raise ValueError('production XML media bytes changed')
        if expected.get('mode') == 'mix' and (any(item['srcEnable'] != 'video' for item in primary)
                                              or len(connected) != 1
                                              or connected[0]['ref'] != 'production_mix'):
            raise ValueError('mix XML would double original audio or omit mixed PCM')
    return observed


def _animation_digest(rows):
    return hashlib.sha256(json.dumps(rows, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def _read_audio_animation(clip):
    """Read the bounded generated volume automation; reject silent losses."""
    volumes = clip.findall('adjust-volume')
    animations = clip.findall('.//keyframeAnimation')
    if not animations:
        return None
    if len(volumes) != 1 or len(animations) != 1:
        raise ValueError('ambiguous audio keyframe animation')
    volume = volumes[0]
    if (volume.attrib != {'amount': '0dB'} or len(volume) != 1 or
            volume[0].tag != 'param' or volume[0].attrib != {'name': 'amount'} or
            len(volume[0]) != 1 or volume[0][0] is not animations[0] or animations[0].attrib):
        raise ValueError('unsupported audio keyframe placement')
    start = _read_time(clip.get('start', '0s'))
    finish = start + _read_time(clip.get('duration'))
    rows = []
    previous = None
    for frame in animations[0]:
        if (frame.tag != 'keyframe' or len(frame) or
                set(frame.attrib) != {'time', 'value', 'interp', 'curve'} or
                frame.get('interp') != 'linear' or frame.get('curve') != 'linear'):
            raise ValueError('unsupported audio keyframe attributes')
        time = _read_time(frame.get('time'))
        value = frame.get('value')
        if not value.endswith('dB'):
            raise ValueError('unsupported audio keyframe unit')
        try:
            db = float(value[:-2])
        except ValueError as exc:
            raise ValueError('invalid audio keyframe gain') from exc
        if (not math.isfinite(db) or not -96 <= db <= 24 or
                not start <= time < finish or previous is not None and time <= previous):
            raise ValueError('invalid audio keyframe time or gain')
        rows.append(dict(frame.attrib))
        previous = time
    if not rows or len(rows) > 20000 or _read_time(rows[0]['time']) != start:
        raise ValueError('invalid audio keyframe coverage')
    return rows


def _validate_audio_animation_context(root, spine):
    parents = {child: parent for parent in root.iter() for child in parent}
    for animation in root.iter('keyframeAnimation'):
        param = parents.get(animation)
        volume = parents.get(param)
        owner = parents.get(volume)
        primary = parents.get(owner)
        if (param is None or param.tag != 'param' or volume is None or volume.tag != 'adjust-volume' or
                owner is None or owner.tag != 'asset-clip' or owner.get('srcEnable') != 'audio' or
                primary is None or primary.tag != 'asset-clip' or parents.get(primary) is not spine):
            raise ValueError('audio animation outside connected audio clip')
        _read_audio_animation(owner)
    if any(parents.get(frame) is None or parents[frame].tag != 'keyframeAnimation'
           for frame in root.iter('keyframe')):
        raise ValueError('orphan audio keyframe')


def _validate_spatial_context(root, spine):
    """Only direct connected visual clips may carry static spatial nodes."""
    spatial = {'adjust-conform', 'adjust-transform', 'adjust-blend'}
    parents = {child: parent for parent in root.iter() for child in parent}
    connected = set()
    for node in root.iter():
        if node.tag not in spatial:
            continue
        owner = parents.get(node)
        primary = parents.get(owner)
        if (owner is None or owner.tag != 'asset-clip' or
                owner.get('srcEnable') != 'video' or
                primary is None or primary.tag != 'asset-clip' or
                parents.get(primary) is not spine):
            raise ValueError('visual placement is outside a connected video clip')
        connected.add(owner)
    for clip in connected:
        order = [child.tag for child in clip if child.tag in spatial]
        if order != ['adjust-conform', 'adjust-transform', 'adjust-blend']:
            raise ValueError('visual placement node order is unsupported')
        parse_static_placement(clip)


def compare_production_reexport(expected_xml, reexport_xml):
    """Structural, frame-time readback; refuses losses and unknown effects."""
    expected = inspect_production_xml(expected_xml)
    actual = inspect_production_xml(reexport_xml)
    if expected != actual:
        raise ValueError('FCP re-export changed media ranges, roles, gains, fades, or layers')
    return {'matched': True, 'expected': str(expected_xml), 'reexport': str(reexport_xml),
            'gui_playback': 'not_established_by_xml_match'}
