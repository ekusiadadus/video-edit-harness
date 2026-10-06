"""Execute a source-bound EDL and expose before/after listening at edit points."""
from copy import deepcopy
from fractions import Fraction
from pathlib import Path
import html
import json
import math
import shutil
import subprocess
import time
import wave
import xml.etree.ElementTree as ET

from .common import ROOT, fingerprint, probe, read, run, write
from .edl import derive_edit, validate_plan, write_srt
from .fcp import export_timeline
from .media import loudness_filter, stream_bounds, verify
from .color import build_lut
from .profiles import resolve
from .regions import region_filter
from .runs import evidence_run, code_hash
from .render_cache import RenderCache, digest


PIPELINE_SIGNATURE = 'edit-render-v4-retained-speech-assembly-20261006'


def revise_plan(plan_path, output, enable=(), disable=(), note=''):
    """Create a review revision without modifying the original proposal."""
    if not note.strip():
        raise ValueError('Record why these edit decisions were reviewed')
    plan = read(plan_path)
    validate_plan(plan, verify_source=True)
    enable, disable = set(enable), set(disable)
    ids = {cut['id'] for cut in plan['cuts']}
    if not (enable | disable) <= ids or enable & disable:
        raise ValueError('Unknown or conflicting cut IDs')
    if not enable and not disable:
        raise ValueError('Select at least one cut decision')
    revised = deepcopy(plan)
    for cut in revised['cuts']:
        if cut['id'] in enable | disable:
            cut['enabled'] = cut['id'] in enable
            cut['review_note'] = note
    revised['parent_plan'] = fingerprint(plan_path)
    revised['status'] = 'reviewed_selection'
    validate_plan(revised, verify_source=True)
    write(output, revised)
    return output


def frame_ranges(xml):
    root = ET.parse(xml).getroot()
    clips = root.findall('./library/event/project/sequence/spine/asset-clip')
    return [(Fraction(c.get('start').removesuffix('s')),
             Fraction(c.get('start').removesuffix('s')) + Fraction(c.get('duration').removesuffix('s')))
            for c in clips]


def export_edit(cfg, plan, out):
    validate_plan(plan, verify_source=True)
    if fingerprint(cfg['source']) != plan['source']:
        raise ValueError('Project source differs from edit plan')
    keep = derive_edit(plan)['keep']
    source_probe = probe(cfg['source'])
    video = next(s for s in source_probe['streams'] if s['codec_type'] == 'video')
    video_end = float(video.get('duration') or source_probe['format']['duration'])
    frame = float(1 / Fraction(video['avg_frame_rate']))
    # AAC/container tails can extend a fraction of a frame beyond the last video frame.
    # Only recover this small terminal discrepancy; never silently clip a larger range.
    for index, (start, end) in enumerate(keep):
        if end > video_end:
            if end - video_end > frame + .000001 or start >= video_end:
                raise ValueError('Edit extends beyond source video')
            keep[index] = (start, video_end)
    ordered = plan.get('version') == 3
    result = export_timeline(Path(cfg['source']), source_probe, keep,
                             out / 'timeline.fcpxml', cfg['name'] + ' Edit Review', ordered=ordered)
    aligned = frame_ranges(out / 'timeline.fcpxml')
    mapping = {
        'source': plan['source'], 'keep': [[float(s), float(e)] for s, e in aligned],
        'duration': sum(float(e - s) for s, e in aligned), 'xml': {**result, 'output':'timeline.fcpxml'},
        'note': 'Subtitles and preview use the same frame-aligned source ranges as FCPXML.'}
    if ordered:
        elapsed = 0.0
        mapping['sequence'] = []
        mapping['sequence_ids'] = []
        for item, (start, end) in zip(plan['sequence'], aligned):
            length = float(end - start)
            mapping['sequence_ids'].append(item['id'])
            mapping['sequence'].append({'id': item['id'], 'source_start': float(start),
                'source_end': float(end), 'output_start': elapsed, 'output_end': elapsed + length,
                'chapter_id': item.get('chapter_id')})
            elapsed += length
    write(out / 'frame-mapping.json', mapping)
    write(out / 'plan.json', plan)
    write_srt(plan, out / 'subtitles.srt', keep=[(float(s), float(e)) for s, e in aligned])
    write(out / 'fcp-delivery.json', {
        'timing': 'FCPXML and preview share frame-aligned source ranges',
        'color': 'FCPXML references original media; apply look.cube manually and disable Camera LUT for Apple Log',
        'audio': 'FCPXML retains natural source audio; per-span fades and normalized mix in video.mp4 require separate FCP work',
        'subtitles': 'Import subtitles.srt separately',
        'spatial_corrections': cfg.get('region_corrections', []),
        'spatial_note': 'Fixed spatial corrections require manual FCP masks; cube LUT contains global grade only',
        'gui_import': 'not_verified', 'effect_fidelity': 'not_verified'})
    return aligned


def _video_filter(cfg, lut, preview):
    escaped = str(lut.resolve()).replace('\\', '\\\\').replace(':', '\\:').replace("'", "'\\''")
    filters = f"format=gbrpf32le,lut3d=file='{escaped}':interp=tetrahedral"
    if preview:
        filters += ',scale=-2:720'
    filters += ',setparams=color_primaries=bt709:color_trc=bt709:colorspace=gbr:range=full,scale=out_color_matrix=bt709:out_range=tv'
    filters += region_filter(cfg)
    return filters + ',format=yuv420p,setsar=1,setparams=color_primaries=bt709:color_trc=bt709:colorspace=bt709:range=limited'


def _concat_file(path, files):
    # ffconcat single-quote escaping is separate from shell quoting; no shell is used.
    path.write_text('ffconcat version 1.0\n' + ''.join(
        "file '" + str(p.resolve()).replace("'", "'\\''") + "'\n" for p in files))


def render_edit(cfg, plan, out, preview=True):
    """Render exact XML ranges; AAC and loudness normalization happen after assembly."""
    source_probe = probe(cfg['source'])
    source_audio = stream_bounds(source_probe, 'audio')
    source_video = stream_bounds(source_probe, 'video')
    if source_audio is None or source_video is None:
        raise ValueError('Talking-head edit requires source video and audio')
    if any(abs(bounds[0]) > .01 for bounds in (source_video, source_audio)):
        raise ValueError('Editing currently requires zero-start video and audio tracks')
    if any(abs(a - v) > .15 for a, v in zip(source_audio, source_video)):
        raise ValueError('Editing currently requires full source audio coverage; inspect partial tracks first')
    validate_plan(plan, verify_source=True)
    if plan.get('version') == 3 and plan.get('status') != 'reviewed_selection':
        raise ValueError('V3 render requires reviewed_selection')
    duration = derive_edit(plan)['duration']
    estimated = duration * 6_000_000 + 256 * 1024 ** 2
    disk = out.parent
    while not disk.exists():
        disk = disk.parent
    if shutil.disk_usage(disk).free < estimated:
        raise ValueError('Insufficient free space for edit segments and final output')
    resolved = resolve(cfg)
    effective = deepcopy(cfg)
    effective['_resolved'] = resolved
    started = time.monotonic()
    with evidence_run(effective, 'edit-preview' if preview else 'edit-render', out,
                      {'plan_sha256': _plan_digest(plan), 'preview': preview, 'normalize_after_edit': True}):
        ranges = export_edit(cfg, plan, out)
        lut = build_lut(effective, None, out / 'look.cube')
        ffmpeg_version = subprocess.check_output(['ffmpeg', '-version'], text=True).splitlines()[0]
        cache = RenderCache(cfg.get('render_cache_root', ROOT / 'output' / 'render-cache'),
                            cfg['source'], plan['source'])
        common_key = {'source': plan['source'], 'ffmpeg': ffmpeg_version,
                      'pipeline': PIPELINE_SIGNATURE, 'code_sha256': code_hash()}
        video_style = {'resolved': resolved, 'input_color': cfg.get('input_color'),
                       'regions': cfg.get('region_corrections', []), 'lut': fingerprint(lut)['sha256'],
                       'preview': preview}
        work = out / 'segments'
        work.mkdir()
        videos, full_videos, audio, video_keys, audio_keys = [], [], [], [], []
        for i, (start, end) in enumerate(ranges):
            length = float(end - start)
            video = work / f'{i:04d}.mov'
            wav = work / f'{i:04d}.wav'
            interval = {'start': str(start), 'end': str(end)}
            def common():
                return ['ffmpeg', '-hide_banner', '-nostdin', '-n', '-ss', str(float(start)),
                        '-i', cfg['source'], '-t', str(length)]
            video_event = cache.get('video', {**common_key, 'interval': interval, 'style': video_style},
                '.mov', video,
                lambda artifact, log: run(common() + ['-map', '0:v:0', '-an', '-filter_threads', '4', '-vf',
                    _video_filter(effective, lut, preview), '-c:v', 'libx264', '-preset', 'fast', '-crf', '18',
                    '-profile:v', 'high', '-pix_fmt', 'yuv420p', '-map_metadata', '-1',
                    '-metadata:s:v:0', 'rotate=0', str(artifact)], log), work / f'{i:04d}-video.log')
            # PCM segments avoid a new AAC priming delay at every splice.
            span = plan['sequence'][i] if plan.get('version') == 3 else {}
            fade_in = float(span.get('fade_in_seconds', 0))
            fade_out = float(span.get('fade_out_seconds', 0))
            if fade_in < 0 or fade_out < 0 or fade_in + fade_out > length:
                raise ValueError('Invalid per-span audio fades after frame alignment')
            if plan.get('version') == 3:
                kept_words = [w for w in plan['transcript']['words'] if float(start) <= w['start'] and w['end'] <= float(end)]
                if kept_words and (float(start) + fade_in > kept_words[0]['start'] + 1e-6 or float(end) - fade_out < kept_words[-1]['end'] - 1e-6):
                    raise ValueError('Frame alignment moves the fade into retained speech; explicitly shorten the fade or increase padding')
            # Preserve missing source audio time instead of collapsing timestamp gaps in PCM.
            af = f'aresample=48000:async=1:first_pts=0,atrim=duration={length},asetpts=N/SR/TB'
            if fade_in:
                af += f',afade=t=in:st=0:d={fade_in}'
            if fade_out:
                af += f',afade=t=out:st={length-fade_out}:d={fade_out}'
            audio_event = cache.get('pcm', {**common_key, 'interval': interval,
                'sample_rate': 48000, 'sample_format': 's16', 'timestamps': 'preserve_gaps_async1_firstpts0', 'fade_in': fade_in, 'fade_out': fade_out},
                '.wav', wav,
                lambda artifact, log: run(common() + ['-map', '0:a:0', '-vn', '-af', af,
                    '-ar', '48000', '-c:a', 'pcm_s16le', str(artifact)], log),
                work / f'{i:04d}-audio.log')
            with wave.open(str(wav), 'rb') as pcm:
                pcm_length = pcm.getnframes() / pcm.getframerate()
                if abs(pcm_length - length) > .03:
                    raise ValueError('PCM segment does not preserve the selected timeline duration')
            videos.append(video)
            full_video = video
            if preview:
                full_video = work / f'{i:04d}-full.mov'
                cache.get('video', {**common_key, 'interval': interval,
                          'style': {**video_style, 'preview': False}}, '.mov', full_video,
                    lambda artifact, log: run(common() + ['-map', '0:v:0', '-an', '-filter_threads', '4', '-vf',
                        _video_filter(effective, lut, False), '-c:v', 'libx264', '-preset', 'fast', '-crf', '18',
                        '-profile:v', 'high', '-pix_fmt', 'yuv420p', '-map_metadata', '-1',
                        '-metadata:s:v:0', 'rotate=0', str(artifact)], log), work / f'{i:04d}-full-video.log')
            full_videos.append(full_video)
            audio.append(wav)
            video_keys.append(video_event['key'])
            audio_keys.append(audio_event['key'])
        _concat_file(out / 'video.ffconcat', videos)
        _concat_file(out / 'audio.ffconcat', audio)
        _concat_file(out / 'speech-video.ffconcat', full_videos)
        total = sum(float(end - start) for start, end in ranges)
        # Retain the selected, graded picture and per-span PCM before production
        # cues or loudness normalization. Copying picture adds no encode pass.
        assembled = out / 'speech-base.wav'
        run(['ffmpeg', '-v', 'error', '-nostdin', '-n', '-f', 'concat', '-safe', '0',
             '-i', str(out/'audio.ffconcat'), '-c:a', 'pcm_s16le', str(assembled)],
            out/'speech-assemble-audio.log')
        run(['ffmpeg', '-v', 'error', '-nostdin', '-n', '-f', 'concat', '-safe', '0',
             '-i', str(out/'speech-video.ffconcat'), '-i', str(assembled), '-map', '0:v:0',
             '-map', '1:a:0', '-c:v', 'copy', '-c:a', 'pcm_s16le', '-map_metadata', '-1',
             '-t', str(total), str(out/'speech-base.mov')], out/'speech-assemble.log')
        assembly_evidence = {'version':2, 'picture_dimensions_scope':'full_resolution',
              'source':fingerprint(out/'speech-base.mov'),
              'mapping':fingerprint(out/'frame-mapping.json'),
              'plan':fingerprint(out/'plan.json'), 'stage':'pre_production_speech_assembly',
              'picture':'frame-aligned cuts with baked grade; copied from retained segments',
              'audio':'48 kHz per-span PCM and selected fades; before normalization or added assets',
              'review_required':True}
        retimed = None
        if cfg.get('retime'):
            from .production import frozen_pattern
            from .speech_retime import verify_speech_setting, remap_speech_mapping, remapped_subtitles
            from .retime import render_retime
            pattern = frozen_pattern(cfg)
            if pattern['id'] == 'natural' or pattern['intensity'] == 'off':
                raise ValueError('Retime conflicts with natural/off')
            original_mapping = read(out/'frame-mapping.json')
            setting = verify_speech_setting(out/'speech-base.mov', plan, original_mapping, cfg['retime'])
            (out/'frame-mapping.json').rename(out/'pre-retime-mapping.json')
            assembly_evidence['mapping'] = fingerprint(out/'pre-retime-mapping.json')
            (out/'timeline.fcpxml').rename(out/'original-cut-reference.fcpxml')
            retimed = out/'speech-retimed.mp4'
            assembled = out/'speech-retimed.wav'
            write(out/'retime-evidence.json', render_retime(out/'speech-base.mov',
                  setting['proposal'], retimed, pcm_output=assembled))
            write(out/'frame-mapping.json', remap_speech_mapping(original_mapping, setting['proposal']['mapping']))
            (out/'subtitles.srt').write_text(remapped_subtitles(setting), encoding='utf-8')
            total = float(Fraction(setting['proposal']['mapping']['output_frame_count'], 1) /
                          Fraction(setting['proposal']['mapping']['fps']))
            export_timeline(retimed, probe(retimed), [(0, total)], out/'timeline.fcpxml',
                            cfg.get('name', 'Retimed Speech Edit'))
        write(out/'speech-assembly.json', assembly_evidence)
        from .production import resolve_production, mix_key, production_sources
        production = resolve_production(cfg, read(out / 'frame-mapping.json'))
        audio_cues = [c for c in production['cues'] if c['role'] in ('music', 'sfx')]
        visual_cues = [c for c in production['cues'] if c['role'] not in ('music', 'sfx')]
        if production['cues'] or production.get('effects', {}).get('events'):
            write(out / 'production.json', production)
        mixed = out / 'mix.m4a'
        def build_mix(artifact, log):
            joined = artifact.parent / 'assembled.wav'
            if retimed is not None:
                shutil.copyfile(assembled, joined)
            else:
                concat = artifact.parent / 'audio.ffconcat'
                _concat_file(concat, audio)
                run(['ffmpeg', '-v', 'error', '-nostdin', '-n', '-f', 'concat', '-safe', '0', '-i',
                     str(concat), '-c:a', 'pcm_s16le', str(joined)], artifact.parent / 'assemble-audio.log')
            mix_input = joined
            if audio_cues:
                from .audio_mix import render_mix
                mix_input = artifact.parent / 'production-mix.wav'
                mix_evidence = render_mix(joined, audio_cues, production_sources(production),
                                          mix_input, total, effective['audio'])
                write(artifact.parent / 'production-mix.json', mix_evidence)
            af = loudness_filter(effective, str(mix_input), 0, total, artifact.parent)
            run(['ffmpeg', '-hide_banner', '-nostdin', '-n', '-i', str(mix_input), '-af', af,
                 '-c:a', 'aac', '-b:a', '384k', '-ar', '48000', str(artifact)], log)
            with log.open('a') as evidence:
                for name in ('assemble-audio.log', 'audio-measure.log'):
                    path = artifact.parent / name
                    if path.exists():
                        evidence.write('\n' + name + '\n' + path.read_text())
        mix_settings = {**common_key, 'pcm': audio_keys,
                        'audio': effective['audio'], 'duration': total}
        if retimed is not None:
            mix_settings['retime'] = {'setting':cfg['retime'], 'pcm_sha256':fingerprint(assembled)['sha256']}
        if audio_cues:
            mix_settings['production'] = mix_key(production)
        mix_event = cache.get('mix', mix_settings, '.m4a', mixed, build_mix,
            out / 'mix.log')
        final = out / 'video.mp4'
        picture_input = ['-i', str(retimed)] if retimed is not None else ['-f', 'concat', '-safe', '0', '-i', str(out/'video.ffconcat')]
        picture_codec = (['-vf', 'scale=-2:720',
                          '-c:v', 'libx264', '-preset', 'fast', '-crf', '18', '-pix_fmt', 'yuv420p']
                         if retimed is not None and preview else ['-c:v', 'copy'])
        run(['ffmpeg', '-hide_banner', '-nostdin', '-n', *picture_input,
             '-i', str(mixed), '-map', '0:v:0', '-map', '1:a:0',
             *picture_codec, '-c:a', 'copy',
             '-map_metadata', '-1', '-t', str(total),
             *(['-movie_timescale','48000'] if retimed is not None else []),
             '-movflags', '+faststart', str(final)], out / 'render.log')
        if visual_cues:
            from .visual import render_overlays
            base = out / 'base-video.mp4'
            final.rename(base)
            write(out / 'overlay-evidence.json', render_overlays(
                base, visual_cues, production_sources(production), final, total, preview=preview,
                preserve_audio_end=retimed is not None))
        if production.get('effects', {}).get('events'):
            from .video_effects import render_effects
            base = out / 'before-effects.mp4'
            final.rename(base)
            write(out / 'effects-evidence.json', render_effects(base, production['effects'], final,
                production['assets'], production.get('composition'), preserve_audio_end=retimed is not None))
        verify(final, out, total, True, (0, total))
        run(['ffmpeg', '-v', 'error', '-n', '-i', str(final), '-vn', '-c:a', 'libmp3lame',
             '-b:a', '192k', str(out / 'audio-only.mp3')], out / 'audio-only.log')
        run(['ffmpeg', '-v', 'error', '-xerror', '-i', str(out / 'audio-only.mp3'), '-f', 'null', '-'],
            out / 'audio-only-decode.log')
        measure = run(['ffmpeg', '-hide_banner', '-nostdin', '-i', str(final), '-map', '0:a:0',
                       '-af', 'loudnorm=print_format=json', '-f', 'null', '-'], out / 'audio-output-measure.log')
        import re
        actual = json.loads(re.findall(r'\{\s*"input_i".*?\}', measure, re.S)[-1])
        warnings = []
        if effective['audio'].get('normalize'):
            if abs(float(actual['input_i']) - effective['audio']['target_lufs']) > .5:
                warnings.append('Integrated loudness differs from target by >0.5 LU')
            if float(actual['input_tp']) > effective['audio']['true_peak_db'] + .3:
                warnings.append('True peak exceeds target +0.3dB tolerance')
        write(out / 'audio-output-measure.json', {'measured': actual, 'targets': effective['audio'], 'warnings': warnings})
        if production['cues'] or production.get('effects', {}).get('events') or cfg.get('retime'):
            from .production import prepare_fcp_handoff
            prepare_fcp_handoff(cfg, production, out)
        cache_report = cache.report()
        cache_report.update({'elapsed_seconds': round(time.monotonic() - started, 3),
            'estimated_capacity_bytes': estimated, 'video_keys': video_keys,
            'pcm_keys': audio_keys, 'mix_key': mix_event['key']})
        write(out / 'cache-report.json', cache_report)
        junctions = audition(cfg, plan, out / 'junctions')
        _gallery(out, junctions)
    return out


def _plan_digest(plan):
    import hashlib
    return hashlib.sha256(json.dumps(plan, sort_keys=True, ensure_ascii=False,
                                    separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def audition(cfg, plan, out, cut_ids=None, context=1.5, offset=0, limit=24):
    """Listen to proposed edits without applying them to the plan."""
    validate_plan(plan, verify_source=True)
    if fingerprint(cfg['source']) != plan['source']:
        raise ValueError('Project source differs from edit plan')
    if not math.isfinite(context) or not .1 <= context <= 10:
        raise ValueError('Audition context must be 0.1..10 seconds')
    if type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= 24:
        raise ValueError('Audition offset must be nonnegative and limit must be 1..24')
    if plan.get('version') == 3:
        return _audition_sequence(cfg, plan, out, cut_ids, context, offset, limit)
    out.mkdir(parents=True, exist_ok=False)
    cuts = plan['cuts'] if cut_ids is None else [c for c in plan['cuts'] if c['id'] in set(cut_ids)]
    if cut_ids is not None and len(cuts) != len(set(cut_ids)):
        raise ValueError('Unknown cut ID')
    # More candidates are accessible by explicit IDs rather than an unbounded preview render.
    all_ids = [cut['id'] for cut in plan['cuts']]
    if len(cuts) > limit:
        if cut_ids is not None:
            raise ValueError('At most 24 explicit cut IDs per audition; split the selection')
        cuts = cuts[offset:offset + limit]
    elif cut_ids is None:
        cuts = cuts[offset:offset + limit]
    evidence = []
    for cut in cuts:
        s, e = cut['start'], cut['end']
        first, last = max(0, s - context), min(plan['duration'], e + context)
        before, after = out / f"{cut['id']}-before.mp3", out / f"{cut['id']}-after.mp3"
        run(['ffmpeg', '-v', 'error', '-nostdin', '-n', '-ss', str(first), '-i', cfg['source'],
             '-t', str(last - first), '-map', '0:a:0', '-vn', '-c:a', 'libmp3lame',
             '-b:a', '192k', str(before)], out / f"{cut['id']}-before.log")
        # One encode of both sides retains natural audio and makes discontinuities audible.
        sides = [(a, b) for a, b in [(first, s), (e, last)] if b > a]
        if not sides:
            raise ValueError('Audition would remove all surrounding audio')
        if len(sides) == 1:
            a, b = sides[0]
            graph = f'[0:a:0]atrim=start={a}:end={b},asetpts=PTS-STARTPTS[out]'
        else:
            graph = (f"[0:a:0]asplit=2[a][b];[a]atrim=start={first}:end={s},asetpts=PTS-STARTPTS[l];"
                     f"[b]atrim=start={e}:end={last},asetpts=PTS-STARTPTS[r];[l][r]concat=n=2:v=0:a=1[out]")
        run(['ffmpeg', '-v', 'error', '-nostdin', '-n', '-i', cfg['source'], '-filter_complex', graph,
             '-map', '[out]', '-c:a', 'libmp3lame', '-b:a', '192k', str(after)], out / f"{cut['id']}-after.log")
        for label, path in [('before', before), ('after', after)]:
            run(['ffmpeg', '-v', 'error', '-xerror', '-i', str(path), '-f', 'null', '-'],
                out / f"{cut['id']}-{label}-decode.log")
        evidence.append({'id': cut['id'], 'start': s, 'end': e, 'enabled': cut['enabled'],
                         'reason': cut['reason'], 'previous_words': cut.get('previous_words', []),
                         'next_words': cut.get('next_words', []), 'before': before.name, 'after': after.name})
    generated_ids = [item['id'] for item in evidence]
    write(out / 'junctions.json', {'plan_sha256': _plan_digest(plan), 'context': context,
                                 'items': evidence, 'total_candidates': len(all_ids), 'all_ids': all_ids,
                                 'generated_count': len(evidence), 'remaining_ids': [i for i in all_ids if i not in generated_ids],
                                 'offset': offset, 'limit': limit,
                                 'note': 'Before/after auditions are proposals, including disabled cuts. No automatic approval.'})
    return evidence


def _audition_sequence(cfg, plan, out, selected_ids, context, offset=0, limit=24):
    """Audition actual adjoining playback spans, including reordered joins."""
    sequence = plan['sequence']
    junctions = [(left, right) for left, right in zip(sequence, sequence[1:])]
    if selected_ids is not None:
        wanted = set(selected_ids)
        if len(wanted) != len(selected_ids) or not wanted <= {left['id'] for left, _ in junctions}:
            raise ValueError('Unknown or duplicate junction ID')
        junctions = [(left, right) for left, right in junctions if left['id'] in wanted]
    else:
        junctions = junctions[offset:offset + limit]
    if len(junctions) > 24:
        raise ValueError('At most 24 junctions per audition')
    out.mkdir(parents=True, exist_ok=False)
    evidence = []
    for left, right in junctions:
        left_a = max(left['start'], left['end'] - context)
        right_b = min(right['end'], right['start'] + context)
        def make_pair(label, spans, target):
            graph = (f'[0:a:0]asplit=2[a][b];'
                     f'[a]atrim=start={spans[0][0]}:end={spans[0][1]},asetpts=PTS-STARTPTS[l];'
                     f'[b]atrim=start={spans[1][0]}:end={spans[1][1]},asetpts=PTS-STARTPTS[r];'
                     '[l][r]concat=n=2:v=0:a=1[out]')
            run(['ffmpeg', '-v', 'error', '-nostdin', '-n', '-i', cfg['source'],
                 '-filter_complex', graph, '-map', '[out]', '-c:a', 'libmp3lame',
                 '-b:a', '192k', str(target)], out / f"{left['id']}-{label}.log")
            run(['ffmpeg', '-v', 'error', '-xerror', '-i', str(target), '-f', 'null', '-'],
                out / f"{left['id']}-{label}-decode.log")
        before = out / f"{left['id']}-before.mp3"
        after = out / f"{left['id']}-after.mp3"
        make_pair('before', [(max(0, left['end'] - context), min(plan['duration'], left['end'] + context)),
                             (max(0, right['start'] - context), min(plan['duration'], right['start'] + context))], before)
        make_pair('after', [(left_a, left['end']), (right['start'], right_b)], after)
        evidence.append({'id': left['id'], 'next_id': right['id'], 'start': left['end'],
                         'end': right['start'], 'reason': left['reason'], 'previous_words': [],
                         'next_words': [], 'before': before.name, 'after': after.name,
                         'scope': 'actual adjoining selected source spans'})
    all_ids = [left['id'] for left, _ in zip(sequence, sequence[1:])]
    generated_ids = [item['id'] for item in evidence]
    write(out / 'junctions.json', {'plan_sha256': _plan_digest(plan), 'context': context,
        'items': evidence, 'total_candidates': len(all_ids), 'all_ids': all_ids,
        'generated_count': len(evidence), 'remaining_ids': [i for i in all_ids if i not in generated_ids],
        'offset': offset, 'limit': limit,
        'note': 'Audition files require listening review; generation is not approval.'})
    return evidence


def _gallery(out, junctions):
    metadata = json.loads((out / 'junctions' / 'junctions.json').read_text())
    cards = []
    for item in junctions:
        text = html.escape(''.join(item['previous_words']) + ' → ' + ''.join(item['next_words']))
        cards.append(f"<article><h2>編集点 {item['id']} / {item['start']:.2f}–{item['end']:.2f}s</h2>"
                     f"<p>{text}</p><p>{html.escape(item['reason'])}</p><p>元の間</p>"
                     f"<audio controls src='junctions/{item['before']}'></audio><p>カットした場合</p>"
                     f"<audio controls src='junctions/{item['after']}'></audio></article>")
    (out / 'index.html').write_text('<!doctype html><html lang="ja"><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width"><title>編集と試聴</title>'
        '<style>body{font:16px system-ui;max-width:1000px;margin:auto;padding:24px;background:#151515;color:#eee}'
        'video{max-width:100%;max-height:65vh}article{padding:16px;border:1px solid #666;margin:16px 0}a{color:#bdf}</style>'
        '<h1>編集と試聴</h1><video controls src="video.mp4"></video><p><a href="audio-only.mp3">音声のみ</a> · '
        '<a href="timeline.fcpxml">FCPXML</a> · <a href="subtitles.srt">字幕</a> · <a href="plan.json">編集計画</a></p>'
        '<p>動画には編集計画で有効にした選択を反映します。内容と切り口は試聴して確認してください。下の比較音声には未採用の候補も含みます。</p>'
        f"<p>試聴生成: {metadata['generated_count']} / {metadata['total_candidates']}。未生成ID: {html.escape(', '.join(map(str, metadata['remaining_ids'])) or 'なし')}</p>"
        + ''.join(cards) + '</html>')
