"""Rebuild public demos from a prepared, licensed synthetic fixture (no API calls)."""
import argparse
import json
from pathlib import Path
import shutil
import subprocess
import sys
import textwrap

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from video_harness.common import fingerprint, read
from video_harness.vertical import caption_font, export_vertical
from video_harness.transcript import load_transcript
from render_demo_sample import render_sample


def run(args, log):
    with Path(log).open('w') as stream:
        subprocess.run(args, stdout=stream, stderr=subprocess.STDOUT, check=True)


def probe(path):
    return json.loads(subprocess.check_output(['ffprobe', '-v', 'error', '-show_streams', '-show_format', '-of', 'json', str(path)]))


def display_font(px, font=None):
    return ImageFont.truetype(str(font), px) if font else ImageFont.load_default(size=px)


def language_content(language):
    if language == 'ja':
        return {
            'banner': '動画編集ハーネス / 合成素材デモ',
            'intro': ('話を残して、長い間を短く。', '同じ机の片付けの話を、用途に合わせて編集。', ['YouTube：2つのコツ / TikTok：1つのコツ']),
            'command': ('2つのコマンド。共通の編集手順。', 'Claude Codeでの入力例：', ['/youtube sample.mp4', '/tiktok sample.mp4', 'Codex：$youtube / $tiktok']),
            'end': ('動画・字幕・編集できるタイムライン', '素材と結び付いた編集計画、確認履歴、持ち運べる成果物。', ['オリジナルの図とAI音声。個人の映像は含みません。', '技術検証済み。人による試聴・FCP確認は未実施。']),
            'before': '編集前 / 同じ話に長い間がある状態',
            'after': '編集後 / 話を残して、間を{gap:.2f}秒短縮',
            'portrait': 'TikTokの結果 / 1つのコツ・縦長9:16・字幕付き',
        }
    if language == 'en':
        return {
            'banner': 'VIDEO EDIT HARNESS / SYNTHETIC DEMO',
            'intro': ('Keep the story. Shorten the pause.', 'Real edits on a licensed desk-tip sample.', ['YouTube: both tips / TikTok: one complete tip']),
            'command': ('Two commands. One workflow.', 'Example invocations in Claude Code:', ['/youtube sample.mp4', '/tiktok sample.mp4', 'Codex: $youtube / $tiktok']),
            'end': ('Video + captions + editable timeline', 'Source-bound plans, review history and portable delivery.', ['Public illustration + AI voice. No personal footage.', 'Technical checks passed. Human listening / FCP pending.']),
            'before': 'BEFORE / Same excerpt with the long pause',
            'after': 'AFTER / Same words - {gap:.2f}s shorter pause',
            'portrait': 'TIKTOK RESULT / One complete tip - 9:16 + captions',
        }
    raise ValueError('Demo language must be ja or en')


def fixture_language(provenance, timing):
    language = provenance.get('voice', {}).get('language')
    if language not in ('ja', 'en') or timing.get('language') != language:
        raise ValueError('Voice and measured transcript languages must agree (ja or en)')
    return language


def card(path, title, subtitle, lines=(), size=(1280, 720), font=None, banner='VIDEO EDIT HARNESS / SYNTHETIC DEMO'):
    im = Image.new('RGB', size, '#122536')
    d = ImageDraw.Draw(im)
    def text(x, y, value, px=42, color='white'):
        while d.textbbox((0, 0), value, font=display_font(px, font))[2] > size[0]-128 and px > 18:
            px -= 2
        d.text((x, y), value, font=display_font(px, font), fill=color)
    text(64, 50, banner, 24, '#83e6d1')
    text(64, 180, title, 64)
    text(64, 280, subtitle, 30, '#d2dde3')
    for i, line in enumerate(lines):
        text(64, 380+i*60, line, 30)
    im.save(path)


def make_segment(source, target, log, duration=None, start=0, still=False, label=None, font=None, cues=()):
    inputs = ['-loop', '1', '-framerate', '30', '-t', str(duration), '-i', str(source)] if still else ['-ss', str(start), '-i', str(source)]
    if still:
        inputs += ['-f', 'lavfi', '-t', str(duration), '-i', 'anullsrc=r=48000:cl=stereo']
    vf = 'scale=1280:720:force_original_aspect_ratio=decrease,pad=1280:720:(ow-iw)/2:(oh-ih)/2:color=0x122536,fps=30,setsar=1'
    tail = 'scale=out_color_matrix=bt709:out_range=tv,format=yuv420p,setsar=1,setparams=color_primaries=bt709:color_trc=bt709:colorspace=bt709'
    filters = ['-vf', vf+','+tail]
    video_map = '0:v:0'
    if label:
        vf = f'scale=1280:{528 if cues else 652}:force_original_aspect_ratio=decrease,pad=1280:720:(ow-iw)/2:68:color=0x122536,fps=30,setsar=1'
        overlay = target.with_suffix('.png')
        im = Image.new('RGBA',(1280,720),(0,0,0,0)); draw = ImageDraw.Draw(im)
        draw.rectangle((0,0,1280,68), fill='#122536')
        draw.text((30,18),label,font=display_font(30, font),fill='white'); im.save(overlay)
        inputs += ['-loop','1','-framerate','30','-t',str(duration),'-i',str(overlay)]
        filters = ['-filter_complex',f'[0:v]{vf}[base];[base][1:v]overlay=0:0:shortest=1:format=auto,{tail}[v]']
        video_map = '[v]'
        if cues:
            chain = f'[0:v]{vf}[base];[base][1:v]overlay=0:0:shortest=1:format=auto[c0]'
            for index, cue in enumerate(cues):
                tile = target.with_name(f'{target.stem}-cue-{index}.png')
                im = Image.new('RGBA',(1280,720),(0,0,0,0)); draw=ImageDraw.Draw(im)
                draw.rectangle((0,604,1280,720),fill='#122536')
                text = '\n'.join(textwrap.wrap(cue['text'], width=38 if any(ord(c)>127 for c in cue['text']) else 68))
                draw.multiline_text((40,619),text,font=display_font(30,font),fill='white',spacing=8)
                im.save(tile)
                inputs += ['-loop','1','-framerate','30','-t',str(duration),'-i',str(tile)]
                chain += f";[c{index}][{index+2}:v]overlay=0:0:shortest=1:format=auto:enable='gte(t,{cue['start']})*lt(t,{cue['end']})'[c{index+1}]"
            filters=['-filter_complex',chain+f';[c{len(cues)}]{tail}[v]']
    run(['ffmpeg', '-hide_banner', '-nostdin', '-y', *inputs, '-t', str(duration), '-map', video_map, '-map', '1:a:0' if still else '0:a:0', *filters, '-af', 'aresample=48000', '-c:v', 'libx264', '-preset', 'medium', '-crf', '20', '-c:a', 'aac', '-b:a', '192k', '-ar', '48000', '-ac', '2', '-movflags', '+faststart', str(target)], log)



def join_segments(clips, target, log):
    """Decode segments onto an exact frame/sample grid and encode one MP4 stream.

    Stream-copying independently encoded H.264/AAC files preserves incompatible
    codec state and AAC priming at joins; a full decode alone misses browser issues.
    """
    inputs, filters, ordered = [], [], []
    total_frames = 0
    for index, clip in enumerate(clips):
        info = probe(clip)
        video = next(row for row in info['streams'] if row['codec_type']=='video')
        frames = int(video['nb_frames'])
        duration = frames/30
        total_frames += frames
        inputs += ['-i',str(clip)]
        filters += [f'[{index}:v]trim=end_frame={frames},setpts=N/(30*TB),setsar=1[v{index}]',
                    f'[{index}:a]aresample=48000,apad,atrim=duration={duration},asetpts=N/SR/TB[a{index}]']
        ordered += [f'[v{index}][a{index}]']
    filters.append(''.join(ordered)+f'concat=n={len(clips)}:v=1:a=1[v][a]')
    run(['ffmpeg','-hide_banner','-nostdin','-y',*inputs,'-filter_complex',';'.join(filters),
         '-map','[v]','-map','[a]','-t',str(total_frames/30),'-r','30','-fps_mode','cfr',
         '-c:v','libx264','-profile:v','high','-level:v','4.0','-pix_fmt','yuv420p','-preset','medium','-crf','20',
         '-color_primaries','bt709','-color_trc','bt709','-colorspace','bt709',
         '-c:a','aac','-b:a','192k','-ar','48000','-ac','2','-movflags','+faststart',str(target)],log)
    return total_frames


def build(sample, out, docs, font=None, youtube_session=None, tiktok_session=None, language=None):
    sample, out, docs = sample.resolve(), out.resolve(), docs.resolve()
    provenance = read(sample/'provenance.json')
    timing = read(sample/'timing.json')
    actual_language = fixture_language(provenance, timing)
    language = language or actual_language
    if language != actual_language:
        raise ValueError('Requested demo language does not match the actual voice and word timing')
    content = language_content(language)
    source = sample/'sample.mp4'
    if provenance.get('source_kind') != 'synthetic' or provenance['source_sha256'] != fingerprint(source)['sha256']:
        raise ValueError('Only a hash-verified public synthetic fixture may enter demo generation')
    if timing.get('source_sha256') != provenance['source_sha256']:
        raise ValueError('Demo timing belongs to a different source')
    sealed = load_transcript(sample/'transcript/transcript.json', source)
    if any(timing.get(key) != sealed.get(key) for key in ('words', 'segments', 'duration', 'language')):
        raise ValueError('Demo timing differs from the sealed transcript')
    if out.exists():
        raise FileExistsError('Choose a new output directory; demo builds preserve prior evidence')
    out.mkdir(parents=True)
    docs.mkdir(parents=True, exist_ok=True)
    renderings = {}
    for mode, existing in [('youtube', youtube_session), ('tiktok', tiktok_session)]:
        if existing:
            result = read(existing/'sample-render.json')
        else:
            result = render_sample(sample, out/f'{mode}-session', mode)
            (out/f'{mode}-session'/'sample-render.json').write_text(json.dumps(result, indent=2)+'\n')
        if read(Path(result['render']['path'])/'frame-mapping.json')['source']['sha256'] != provenance['source_sha256']:
            raise ValueError('Render does not belong to the public fixture')
        video = Path(result['render']['files']['video']['path'])
        if fingerprint(video)['sha256'] != result['render']['files']['video']['sha256']:
            raise ValueError('Render changed after registration')
        renderings[mode] = result
    yt = Path(renderings['youtube']['render']['files']['video']['path'])
    tt = Path(renderings['tiktok']['render']['files']['video']['path'])
    yt_mapping = read(Path(renderings['youtube']['render']['path'])/'frame-mapping.json')
    removed_gap = yt_mapping['sequence'][1]['source_start']-yt_mapping['sequence'][0]['source_end']
    # Comparison uses the same speech on both sides, with full-source loudness normalization.
    normalized = out/'before-normalized.mp4'
    run(['ffmpeg','-hide_banner','-nostdin','-y','-i',str(source),'-c:v','copy','-af','loudnorm=I=-18:TP=-1.5:LRA=7','-c:a','aac','-b:a','192k','-ar','48000','-ac','2',str(normalized)],out/'before-normalize.log')
    # These are the actual word times of the published fixture, not synthetic alignment.
    words = timing['words']
    gap, split = max((right['start']-left['end'], index) for index, (left, right) in enumerate(zip(words, words[1:])))
    if gap < 1:
        raise ValueError('Expected a measured sentence gap of at least one second')
    first = words[:split+1]
    captions = out/'tiktok-captions.srt'
    def stamp(seconds):
        ms = round(seconds*1000); h, ms = divmod(ms,3600000); m, ms = divmod(ms,60000); s, ms=divmod(ms,1000)
        return f'{h:02}:{m:02}:{s:02},{ms:03}'
    script = provenance['voice']['script'][0]
    caption_text = script.replace('、', '、\n', 1) if language=='ja' else '\n'.join(textwrap.wrap(script, width=28))
    tt_start = read(Path(renderings['tiktok']['render']['path'])/'frame-mapping.json')['sequence'][0]['source_start']
    captions.write_text(f"1\n{stamp(max(0, first[0]['start']-tt_start))} --> {stamp(first[-1]['end']-tt_start)}\n{caption_text}\n",encoding='utf-8')
    font_path = font or getattr(caption_font([{'text':'日本語' if language=='ja' else 'English'}]), 'path', None)
    chosen_font = Path(font_path) if font_path else None
    vertical = export_vertical(tt, out/'vertical', framing='fit', subtitles=captions, font=chosen_font)
    shutil.copyfile(out/'vertical/video.mp4', out/f'tiktok-demo-{language}.mp4')
    shutil.copyfile(yt, out/f'youtube-result-{language}.mp4')
    shutil.copyfile(Path(renderings['youtube']['render']['path'])/'subtitles.srt', out/f'youtube-result-{language}.srt')
    shutil.copyfile(captions, out/f'tiktok-demo-{language}.srt')
    intro = out/'intro.png'; command = out/'command.png'; end = out/'end.png'
    for image, key in [(intro, 'intro'), (command, 'command'), (end, 'end')]:
        card(image, *content[key], font=chosen_font, banner=content['banner'])
    # Anchor the matched excerpt to the actual frame-mapped sentence boundary.
    excerpt_start = yt_mapping['sequence'][0]['source_start']
    excerpt_end = yt_mapping['sequence'][-1]['source_end']
    before_duration = excerpt_end-excerpt_start
    after_duration = before_duration-removed_gap
    script = provenance['voice']['script']
    before_cues = [{'start':first[0]['start']-excerpt_start,'end':first[-1]['end']-excerpt_start,'text':script[0]},
                   {'start':first[-1]['end']-excerpt_start,'end':words[split+1]['start']-excerpt_start,'text':'長い間があります（映像の停止ではありません）' if language=='ja' else 'Long pause in the source (not frozen playback)'},
                   {'start':words[split+1]['start']-excerpt_start,'end':words[-1]['end']-excerpt_start,'text':script[1]}]
    after_cues = [{'start':first[0]['start']-excerpt_start,'end':first[-1]['end']-excerpt_start,'text':script[0]},
                  {'start':words[split+1]['start']-excerpt_start-removed_gap,'end':words[-1]['end']-excerpt_start-removed_gap,'text':script[1]}]
    segments = [
        (intro, 2, 0, True, None, ()),
        (normalized, before_duration, excerpt_start, False, content['before'], before_cues),
        (yt, after_duration, excerpt_start-yt_mapping['sequence'][0]['source_start'], False, content['after'].format(gap=removed_gap), after_cues),
        (command, 3, 0, True, None, ()),
        (out/f'tiktok-demo-{language}.mp4', float(vertical['duration']), 0, False, content['portrait'], ()),
        (end, 2.5, 0, True, None, ()),
    ]
    clips = []
    for i,(media,dur,start,still,label,cues) in enumerate(segments):
        target=out/f'part-{i}.mp4'; make_segment(media,target,out/f'part-{i}.log',dur,start,still,label,chosen_font,cues); clips.append(target)
    overview = out/f'youtube-demo-{language}.mp4'
    expected_frames = join_segments(clips, overview, out/'concat.log')
    outputs={}
    for name,path,dims in [('youtube',overview,(1280,720)),('tiktok',out/f'tiktok-demo-{language}.mp4',(1080,1920)),('youtube-result',out/f'youtube-result-{language}.mp4',(1280,720))]:
        info=probe(path); v=next(s for s in info['streams'] if s['codec_type']=='video')
        if (v['width'],v['height'])!=dims or v['r_frame_rate']!='30/1' or v.get('sample_aspect_ratio')!='1:1' or any(v.get(k)!='bt709' for k in ['color_space','color_transfer','color_primaries']) or not any(s['codec_type']=='audio' and s['codec_name']=='aac' for s in info['streams']):
            raise ValueError(f'{name}: format check failed')
        if name=='youtube' and (int(v['nb_frames'])!=expected_frames or abs(float(v.get('start_time',0)))>.001):
            raise ValueError('Overview frame count or zero-based timeline check failed')
        run(['ffmpeg','-hide_banner','-nostdin','-v','error','-i',str(path),'-f','null','-'],out/f'{name}-decode.log')
        outputs[name]={'filename':path.name,'sha256':fingerprint(path)['sha256'],'duration':float(info['format']['duration']),'dimensions':dims,'full_decode':'pass'}
        if name!='youtube-result':
            run(['ffmpeg','-hide_banner','-nostdin','-y','-ss','2' if name=='tiktok' else '7','-i',str(path),'-frames:v','1',str(docs/f'{name}-poster.png')],out/f'{name}-poster.log')
    # One small overview GIF; individual results use still posters and sound-enabled links.
    palette=out/'palette.png'
    run(['ffmpeg','-hide_banner','-nostdin','-y','-i',str(overview),'-vf','fps=3,scale=480:-2:flags=lanczos,palettegen=max_colors=48',str(palette)],out/'palette.log')
    run(['ffmpeg','-hide_banner','-nostdin','-y','-i',str(overview),'-i',str(palette),'-filter_complex','[0:v]fps=3,scale=480:-2:flags=lanczos[x];[x][1:v]paletteuse=dither=bayer:bayer_scale=4',str(docs/'youtube-preview.gif')],out/'gif.log')
    result={'language':language,'source_sha256':provenance['source_sha256'],'source_kind':'synthetic','font_sha256':fingerprint(chosen_font)['sha256'] if chosen_font else None,'pause_removed_seconds':removed_gap,'retained_words':{mode: result['retained_words'] for mode, result in renderings.items()},'comparison_source_interval':[excerpt_start,excerpt_end],'overview_join':'single_encode_frame_sample_grid','overview_frames':expected_frames,'outputs':outputs,'human_listening':'not_performed','fcp_gui':'not_performed','platform_playback':'not_performed','screen_recording':False}
    (out/'manifest.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(result,ensure_ascii=False,indent=2))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sample',type=Path,required=True)
    parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--docs-output',type=Path,default=ROOT/'docs/demo')
    parser.add_argument('--font',type=Path)
    parser.add_argument('--language',choices=['ja','en'],help='Must match the fixture voice and measured transcript')
    parser.add_argument('--youtube-session',type=Path)
    parser.add_argument('--tiktok-session',type=Path)
    a=parser.parse_args()
    build(a.sample,a.out,a.docs_output,a.font,a.youtube_session,a.tiktok_session,a.language)
