"""Source-bound visual EDL render without transcript or cloud speech recognition."""
from __future__ import annotations

from copy import deepcopy
from fractions import Fraction
from pathlib import Path
import json
import math
import wave
import xml.etree.ElementTree as ET

from .assets import validate_asset
from .audio_mix import render_mix
from .color import build_lut
from .common import fingerprint, probe, run, write
from .editing import _video_filter
from .media import loudness_filter, verify
from .production import resolve_production, verify_production
from .profiles import resolve
from .runs import evidence_run
from .visual import render_visual_edl, render_overlays, validate_visual_edl


_FCP_SOURCE_RATES = {
    Fraction(24000, 1001): '23.98', Fraction(24): '24', Fraction(25): '25',
    Fraction(30000, 1001): '29.97', Fraction(30): '30', Fraction(60): '60',
    Fraction(48000, 1001): '47.95', Fraction(48): '48', Fraction(50): '50',
    Fraction(60000, 1001): '59.94',
}


def _time(value):
    value = Fraction(value)
    return f'{value.numerator}/{value.denominator}s' if value.denominator != 1 else f'{value.numerator}s'


def _write_xml(path, plan, mapping, assets, name):
    """Base FCPXML carries original source cuts and source ambience only."""
    rows = mapping['sequence']
    rate = Fraction(mapping['fps'])
    first_probe = probe(assets[rows[0]['asset_id']]['path'])
    video = next(s for s in first_probe['streams'] if s['codec_type'] == 'video')
    root = ET.Element('fcpxml', version='1.10')
    resources = ET.SubElement(root, 'resources')
    ET.SubElement(resources, 'format', id='fmt', frameDuration=_time(1 / rate),
                  width=str(video['width']), height=str(video['height']),
                  colorSpace='1-1-1 (Rec. 709)')
    ids = {aid: f'asset{i}' for i, aid in enumerate(dict.fromkeys(row['asset_id'] for row in rows), 1)}
    for aid, xml_id in ids.items():
        asset = assets[aid]
        source = Path(asset['path'])
        info = probe(source)
        picture = next(s for s in info['streams'] if s['codec_type'] == 'video')
        audio = next((s for s in info['streams'] if s['codec_type'] == 'audio'), None)
        source_rate = Fraction(picture['r_frame_rate'])
        if source_rate <= 0:
            raise ValueError('Invalid source frame rate for FCPXML')
        format_id = f'fmt-{xml_id}'
        ET.SubElement(resources, 'format', id=format_id, frameDuration=_time(1 / source_rate),
                      width=str(picture['width']), height=str(picture['height']))
        attrs = {'id': xml_id, 'name': source.stem, 'start': '0s',
                 'duration': _time(Fraction(str(picture.get('duration') or info['format']['duration']))),
                 'hasVideo': '1', 'format': format_id}
        if audio is not None:
            attrs.update(hasAudio='1', audioSources='1', audioChannels=str(audio['channels']),
                         audioRate=str(audio['sample_rate']))
        node = ET.SubElement(resources, 'asset', attrs)
        ET.SubElement(node, 'media-rep', kind='original-media', src=source.resolve().as_uri())
    event = ET.SubElement(ET.SubElement(root, 'library'), 'event', name=name)
    project = ET.SubElement(event, 'project', name=name)
    sequence = ET.SubElement(project, 'sequence', format='fmt', duration=_time(Fraction(mapping['frame_count'], 1) / rate),
                             tcStart='0s', tcFormat='NDF', audioLayout='stereo', audioRate='48k')
    spine = ET.SubElement(sequence, 'spine')
    for row in rows:
        source_rate = Fraction(row['source_fps'])
        start = Fraction(row['source_first_frame'], 1) / source_rate
        length = Fraction(row['output_end_frame_exclusive'] - row['output_first_frame'], 1) / rate
        offset = Fraction(row['output_first_frame'], 1) / rate
        clip = ET.SubElement(spine, 'asset-clip', ref=ids[row['asset_id']], name=Path(assets[row['asset_id']]['path']).stem,
                             offset=_time(offset), start=_time(start), duration=_time(length))
        if source_rate != rate:
            attrs = {'scaleEnabled': '1'}
            if source_rate in _FCP_SOURCE_RATES:
                attrs['srcFrameRate'] = _FCP_SOURCE_RATES[source_rate]
            ET.SubElement(clip, 'conform-rate', attrs)
    content = ET.tostring(root, encoding='utf-8', xml_declaration=True)
    content = content.replace(b'?>\n', b'?>\n<!DOCTYPE fcpxml>\n', 1)
    with Path(path).open('xb') as stream:
        stream.write(content)


def _nonzero_pcm(path):
    with wave.open(str(path), 'rb') as stream:
        while chunk := stream.readframes(48000):
            if any(chunk):
                return True
    return False


def visual_pipeline_version(cfg):
    """Unversioned existing projects retain their composed-picture grade."""
    version=cfg.get('visual_pipeline_version',1)
    if type(version) is not int or version not in (1,2):
        raise ValueError('visual_pipeline_version must be 1 or 2')
    return version


def _composed_output_filter(preview):
    """Scale/tag an already graded composite without another LUT or mask."""
    return ('scale=-2:720,' if preview else '') + ('format=yuv420p,setsar=1,'
        'setparams=color_primaries=bt709:color_trc=bt709:colorspace=bt709:range=limited')


def render_visual_edit(cfg, plan, out, preview=True):
    """Render reviewed v4 source-frame selections and optional licensed additions.

    The XML is an original-source cut reference. Creative additions, grade and
    normalized sound are established by the reviewed MP4, not this XML.
    """
    pipeline_version=visual_pipeline_version(cfg)
    has_transitions = cfg.get('transitions') is not None
    if has_transitions:
        from .transitions import _eligible
        _eligible(cfg)
    has_audio_cuts = cfg.get('audio_cuts') is not None
    if has_audio_cuts and cfg.get('retime'):
        raise ValueError('J/L audio cuts and retime require a joint audio-word mapping; this combination is unsupported')
    if has_audio_cuts and cfg.get('fcp_handoff') == 'editable':
        raise ValueError('J/L audio cuts require baked mix/video_only handoff; editable FCP audio cuts are unsupported')
    if cfg.get('input_color') not in {'rec709', 'apple_log'}:
        raise ValueError('Visual edit needs explicit rec709 or apple_log input color')
    records = cfg.get('assets')
    if not isinstance(records, list) or not records:
        raise ValueError('Visual edit needs registered local assets')
    from .patterns import resolve_asset_policy
    policy = resolve_asset_policy(cfg)
    assets = {a['asset_id']: validate_asset(a, policy) for a in records}
    if len(assets) != len(records):
        raise ValueError('Duplicate registered asset ID')
    normalized = validate_visual_edl(plan, list(assets.values()))
    if normalized['status'] != 'reviewed_selection':
        raise ValueError('Visual EDL requires explicit selection review')
    used = {row['asset_id'] for row in normalized['sequence']}
    if not used <= assets.keys():
        raise ValueError('Visual EDL refers to unregistered source')
    primary = assets[normalized['sequence'][0]['asset_id']]['path']
    effective = deepcopy(cfg)
    effective['source'] = primary
    effective['_resolved'] = resolve(effective)
    effective.setdefault('audio', {'normalize': True, 'target_lufs': -16,
                                   'true_peak_db': -1.5, 'loudness_range': 7})
    out = Path(out)
    identities = {aid: fingerprint(assets[aid]['path']) for aid in used}
    with evidence_run(effective, 'visual-edit-preview' if preview else 'visual-edit-render', out,
                      {'visual_plan_sources': identities, 'preview': bool(preview)}):
        # The visual renderer assembles actual source spans and fills absent audio
        # tracks with 48 kHz silence, preserving the ordered output timeline.
        base = render_visual_edl(normalized, list(assets.values()), out / 'visual-base.mp4')
        rate = Fraction(base['fps'])
        rows = []
        for row in base['frame_mapping']:
            asset = assets[row['asset_id']]
            rows.append({**row, 'source_path': asset['path'], 'source_sha256': asset['sha256'],
                         'source_start': _time(Fraction(row['source_first_frame'], 1) / Fraction(row['source_fps'])),
                         'source_end': _time(Fraction(row['source_end_frame_exclusive'], 1) / Fraction(row['source_fps'])),
                         'output_start': _time(Fraction(row['output_first_frame'], 1) / rate),
                         'output_end': _time(Fraction(row['output_end_frame_exclusive'], 1) / rate)})
        mapping = {'version': 4, 'edit_basis': 'visual', 'duration': base['duration'],
                   'frame_count': base['frame_count'], 'fps': base['fps'], 'sequence': rows,
                   'has_source_audio': any(any(s['codec_type'] == 'audio' for s in probe(assets[aid]['path'])['streams'])
                                           for aid in used),
                   'audio': 'source audio in actual segment order; absent tracks are explicit silence'}
        visual_input=out/'visual-base.mp4'
        subtitle_text=''
        if effective.get('retime'):
            from .retime import render_retime,captions_srt
            from .retime_mapping import remap_visual_mapping
            from .render_cache import digest
            setting=effective['retime']
            if not isinstance(setting,dict) or set(setting)!={'version','proposal','input_mapping_sha256'} or setting['version']!=1:
                raise ValueError('Use a session source-bound retime candidate')
            if effective['input_color']!='rec709':raise ValueError('Session retime needs a Rec.709 source stage')
            from .production import frozen_pattern
            pattern=frozen_pattern(effective)
            if pattern['id']=='natural' or pattern['intensity']=='off':raise ValueError('Retime conflicts with natural/off')
            if setting['input_mapping_sha256']!=digest(mapping):raise ValueError('Retime base mapping changed; propose again')
            write(out/'pre-retime-mapping.json',mapping)
            _write_xml(out/'original-cut-reference.fcpxml',normalized,mapping,assets,cfg.get('name','Visual Edit'))
            visual_input=out/'visual-retimed.mp4'
            evidence=render_retime(out/'visual-base.mp4',setting['proposal'],visual_input,
                                   pcm_output=out/'visual-retimed.wav')
            write(out/'retime-evidence.json',evidence)
            mapping=remap_visual_mapping(mapping,evidence['mapping'])
            base={**base,'duration':mapping['duration'],'frame_count':mapping['frame_count']}
            subtitle_text=captions_srt(evidence['captions'])
        if has_transitions:
            from .transitions import render_transition_setting
            from .transition_feedback import attach_transitions
            write(out/'pre-transition-mapping.json', mapping)
            _write_xml(out/'original-cut-reference.fcpxml',normalized,mapping,assets,cfg.get('name','Visual Edit'))
            transitioned = out/'visual-transitioned.mp4'
            transition_evidence = render_transition_setting(visual_input,mapping,effective,
                                                            effective['transitions'],transitioned)
            write(out/'transition-evidence.json',transition_evidence)
            mapping = attach_transitions(mapping, transition_evidence['compiled'])
            visual_input = transitioned
        write(out / 'frame-mapping.json', mapping)
        write(out / 'plan.json', normalized)
        (out / 'subtitles.srt').write_text(subtitle_text, encoding='utf-8')
        if effective.get('retime') or has_transitions:
            from .fcp import export_timeline
            export_timeline(visual_input,probe(visual_input),[(0,base['duration'])],out/'timeline.fcpxml',cfg.get('name','Retimed Visual Edit'))
        else:
            _write_xml(out / 'timeline.fcpxml', normalized, mapping, assets, cfg.get('name', 'Visual Edit'))
        production = resolve_production(effective, mapping)
        verify_production(production)
        write(out / 'production.json', production)
        audio_cues = [c for c in production['cues'] if c['role'] in {'music', 'sfx'}]
        visual_cues = [c for c in production['cues'] if c['role'] in {'image', 'video', 'title'}]
        lut = build_lut(effective, None, out / 'look.cube')
        grade_input=fingerprint(visual_input)
        if pipeline_version==2:
            graded=out/'visual-graded.mp4'
            run(['ffmpeg','-hide_banner','-nostdin','-n','-i',str(visual_input),
                 '-map','0:v:0','-map','0:a:0','-vf',_video_filter(effective,lut,False),
                 '-c:v','libx264','-preset','fast','-crf','18','-pix_fmt','yuv420p',
                 '-c:a','copy','-map_metadata','-1',
                 *(['-movie_timescale','48000'] if effective.get('retime') else []),
                 '-movflags','+faststart',str(graded)],out/'grade.log')
            from .video_effects import _probe,_stream,_verified_rate
            observed=_probe(graded,count=True);picture=_stream(observed,'video')
            if not picture or int(picture['nb_read_frames'])!=mapping['frame_count'] or _verified_rate(graded,picture,mapping['frame_count'])!=rate:
                raise ValueError('Footage grade changed frame count or FPS')
            visual_input=graded
        write(out/'visual-pipeline.json',{
            'version':pipeline_version,'grade_scope':'assembled_footage_before_overlays_and_effects' if pipeline_version==2 else 'composed_picture_after_overlays_and_effects',
            'grade_input':grade_input,'lut':fingerprint(lut),
            'graded_picture':fingerprint(visual_input) if pipeline_version==2 else None,
            'overlay_grade':'not applied' if pipeline_version==2 else 'same final LUT as footage',
            'effect_scope':'Existing picture effects apply to composed picture; effect titles are inserted afterward',
            'secondary_color':'Overlay/comparison inputs retain their own colors in pipeline 2; no implicit common LUT',
            'preview_scale_stage':'final composed picture' if pipeline_version==2 else 'final grade'})
        if visual_cues:
            rendered = out / 'visual-overlays.mp4'
            render_overlays(visual_input, visual_cues, production['assets'], rendered, base['duration'], preview,
                            preserve_audio_end=bool(effective.get('retime')))
            visual_input = rendered
        if production.get('effects', {}).get('events'):
            from .video_effects import render_effects
            rendered = out / 'visual-effects.mp4'
            write(out / 'effects-evidence.json', render_effects(visual_input, production['effects'], rendered,
                production['assets'], production.get('composition'), preserve_audio_end=bool(effective.get('retime'))))
            visual_input = rendered
        # Retimed PCM avoids another intermediate AAC decode. Other timelines
        # retain the existing decode/pad path before ducking and normalization.
        speech = out / 'environment.wav'
        environment_input = out/'visual-retimed.wav' if effective.get('retime') else visual_input
        run(['ffmpeg', '-v', 'error', '-nostdin', '-n', '-i', str(environment_input), '-vn',
             '-af', f'aresample=48000:async=1:first_pts=0,apad=whole_dur={base["duration"]},atrim=duration={base["duration"]},asetpts=N/SR/TB',
             '-ar', '48000', '-ac', '2', '-c:a', 'pcm_s16le', str(speech)], out / 'environment.log')
        if has_audio_cuts:
            from .audio_cuts import verify_audio_cuts, render_audio_cuts, captions_srt
            compiled = verify_audio_cuts(mapping, normalized, effective, cfg['audio_cuts'])
            original = out/'environment-original.wav'
            speech.rename(original)
            audio_evidence = render_audio_cuts(original, compiled, speech)
            write(out/'audio-cuts.json', {'setting':cfg['audio_cuts'], 'compiled':compiled, 'render':audio_evidence})
            subtitle_text = captions_srt(compiled)
            (out/'subtitles.srt').write_text(subtitle_text, encoding='utf-8')
        audio_source = speech
        if audio_cues:
            audio_source = out / 'creative-mix.wav'
            write(out / 'mix-evidence.json', render_mix(speech, audio_cues, production['assets'],
                                                       audio_source, base['duration'], effective['audio']))
        audio_cfg = deepcopy(effective)
        if not _nonzero_pcm(audio_source):
            audio_cfg['audio']['normalize'] = False
        audio_filter = loudness_filter(audio_cfg, str(audio_source), 0, base['duration'], out)
        run(['ffmpeg', '-hide_banner', '-nostdin', '-n', '-i', str(visual_input), '-i', str(audio_source),
             '-map', '0:v:0', '-map', '1:a:0', '-vf',
             _composed_output_filter(preview) if pipeline_version==2 else _video_filter(effective, lut, preview),
             '-af', audio_filter, '-c:v', 'libx264', '-preset', 'fast', '-crf', '18',
             '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-b:a', '384k', '-ar', '48000',
             '-map_metadata', '-1', '-t', str(base['duration']),
             *(['-movie_timescale','48000'] if effective.get('retime') or has_audio_cuts else []), '-movflags', '+faststart',
             str(out / 'video.mp4')], out / 'render.log')
        verify(out / 'video.mp4', out, base['duration'], True, (0, base['duration']))
        run(['ffmpeg', '-v', 'error', '-nostdin', '-n', '-i', str(out / 'video.mp4'),
             '-vn', '-c:a', 'libmp3lame', '-b:a', '192k', str(out / 'audio-only.mp3')], out / 'audio-only.log')
        run(['ffmpeg', '-v', 'error', '-xerror', '-i', str(out / 'audio-only.mp3'),
             '-f', 'null', '-'], out / 'audio-only-decode.log')
        (out / 'fcp-delivery.json').write_text(json.dumps({
            'timeline': 'Baked transition picture; original-cut-reference.fcpxml is hard-cut reference only' if has_transitions else ('Baked retimed picture/audio; original-cut-reference.fcpxml is pre-retime only' if effective.get('retime') else ('Source-cut XML is a pre-J/L reference; baked mix contains selected audio handles' if has_audio_cuts else 'Original source video and environment audio only')),
            'creative_additions': 'MP4 reference; separate FCP recreation required',
            'color': 'Apply look.cube to original source-cut XML only; baked MP4 picture is already graded',
            'visual_pipeline_version':pipeline_version, 'subtitles': 'No transcript or captions generated',
            'silent_audio': 'Synthetic 48 kHz silence for source sections without audio'}))
        from .production import prepare_fcp_handoff
        prepare_fcp_handoff(effective, production, out)
        for aid in used:
            if fingerprint(assets[aid]['path']) != identities[aid]:
                raise ValueError('Visual source changed during render')
    return out
