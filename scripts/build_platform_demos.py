"""Rebuild public demos from a prepared, licensed synthetic fixture (no API calls)."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from video_harness.common import fingerprint, read
from video_harness.vertical import caption_font, export_vertical
from render_demo_sample import render_sample


def run(args, log):
    with Path(log).open('w') as stream:
        subprocess.run(args, stdout=stream, stderr=subprocess.STDOUT, check=True)


def probe(path):
    return json.loads(subprocess.check_output(['ffprobe', '-v', 'error', '-show_streams', '-show_format', '-of', 'json', str(path)]))


def card(path, title, subtitle, lines=(), size=(1280, 720)):
    im = Image.new('RGB', size, '#122536')
    d = ImageDraw.Draw(im)
    def text(x, y, value, px=42, color='white'):
        d.text((x, y), value, font=ImageFont.load_default(size=px), fill=color)
    text(64, 50, 'VIDEO EDIT HARNESS  /  SYNTHETIC DEMO', 24, '#83e6d1')
    text(64, 180, title, 64)
    text(64, 280, subtitle, 30, '#d2dde3')
    for i, line in enumerate(lines):
        text(64, 380+i*60, line, 30)
    im.save(path)


def make_segment(source, target, log, duration=None, start=0, still=False, label=None):
    inputs = ['-loop', '1', '-framerate', '30', '-t', str(duration), '-i', str(source)] if still else ['-ss', str(start), '-i', str(source)]
    if still:
        inputs += ['-f', 'lavfi', '-t', str(duration), '-i', 'anullsrc=r=48000:cl=stereo']
    vf = 'scale=1280:720:force_original_aspect_ratio=decrease,pad=1280:720:(ow-iw)/2:(oh-ih)/2:color=0x122536,fps=30,setsar=1'
    tail = 'scale=out_color_matrix=bt709:out_range=tv,format=yuv420p,setsar=1,setparams=color_primaries=bt709:color_trc=bt709:colorspace=bt709'
    filters = ['-vf', vf+','+tail]
    video_map = '0:v:0'
    if label:
        vf = 'scale=1280:652:force_original_aspect_ratio=decrease,pad=1280:720:(ow-iw)/2:68:color=0x122536,fps=30,setsar=1'
        overlay = target.with_suffix('.png')
        im = Image.new('RGBA',(1280,720),(0,0,0,0)); draw = ImageDraw.Draw(im)
        draw.rectangle((0,0,1280,68), fill='#122536')
        draw.text((30,18),label,font=ImageFont.load_default(size=30),fill='white'); im.save(overlay)
        inputs += ['-loop','1','-framerate','30','-t',str(duration),'-i',str(overlay)]
        filters = ['-filter_complex',f'[0:v]{vf}[base];[base][1:v]overlay=0:0:shortest=1:format=auto,{tail}[v]']
        video_map = '[v]'
    run(['ffmpeg', '-hide_banner', '-nostdin', '-y', *inputs, '-t', str(duration), '-map', video_map, '-map', '1:a:0' if still else '0:a:0', *filters, '-af', 'aresample=48000', '-c:v', 'libx264', '-preset', 'medium', '-crf', '20', '-c:a', 'aac', '-b:a', '192k', '-ar', '48000', '-ac', '2', '-movflags', '+faststart', str(target)], log)



def build(sample, out, docs, font=None, youtube_session=None, tiktok_session=None):
    sample, out, docs = sample.resolve(), out.resolve(), docs.resolve()
    provenance = read(sample/'provenance.json')
    source = sample/'sample.mp4'
    if provenance.get('source_kind') != 'synthetic' or provenance['source_sha256'] != fingerprint(source)['sha256']:
        raise ValueError('Only a hash-verified public synthetic fixture may enter demo generation')
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
    timing = read(sample/'timing.json')
    first = [w for w in timing['words'] if w['id'] <= 17]
    captions = out/'tiktok-captions.srt'
    def stamp(seconds):
        ms = round(seconds*1000); h, ms = divmod(ms,3600000); m, ms = divmod(ms,60000); s, ms=divmod(ms,1000)
        return f'{h:02}:{m:02}:{s:02},{ms:03}'
    captions.write_text(f"1\n{stamp(first[0]['start'])} --> {stamp(first[-1]['end'])}\n机を片付けるコツは、\n使うものだけを戻すことです。\n",encoding='utf-8')
    chosen_font = Path(font) if font else Path(caption_font([{'text':'日本語'}]).path)
    vertical = export_vertical(tt, out/'vertical', framing='fit', subtitles=captions, font=chosen_font)
    shutil.copyfile(out/'vertical/video.mp4', out/'tiktok-demo.mp4')
    shutil.copyfile(yt, out/'youtube-result.mp4')
    intro = out/'intro.png'; command = out/'command.png'; end = out/'end.png'
    card(intro, 'Keep the story. Shorten the pause.', 'Real edits on a licensed desk-tip sample.', ['YouTube: both tips  /  TikTok: one complete tip'])
    card(command, 'Two commands. One workflow.', 'Example invocations in Claude Code:', ['/youtube sample.mp4', '/tiktok sample.mp4', 'Codex: $youtube / $tiktok'])
    card(end, 'Video + captions + editable timeline', 'Source-bound plans, review history and portable delivery.', ['Public illustration + AI voice. No personal footage.', 'Technical checks passed. Human listening / FCP pending.'])
    # Matched before/after excerpt starts on the same phrase and ends on the same phrase.
    excerpt_start, excerpt_end = 3.48, 8.24
    before_duration = excerpt_end-excerpt_start
    after_duration = before_duration-removed_gap
    segments = [
        (intro, 2, 0, True, None),
        (normalized, before_duration, excerpt_start, False, 'BEFORE  /  Same excerpt with the long pause'),
        (yt, after_duration, excerpt_start, False, f'AFTER  /  Same words - {removed_gap:.2f}s shorter pause'),
        (command, 3, 0, True, None),
        (out/'tiktok-demo.mp4', float(vertical['duration']), 0, False, 'TIKTOK RESULT  /  One complete tip - 9x16 + captions'),
        (end, 2.5, 0, True, None),
    ]
    clips = []
    for i,(media,dur,start,still,label) in enumerate(segments):
        target=out/f'part-{i}.mp4'; make_segment(media,target,out/f'part-{i}.log',dur,start,still,label); clips.append(target)
    concat = out/'concat.txt'
    concat.write_text(''.join(f"file '{p.name}'\n" for p in clips))
    overview = out/'youtube-demo.mp4'
    run(['ffmpeg','-hide_banner','-nostdin','-y','-f','concat','-safe','0','-i',str(concat),'-c','copy','-movflags','+faststart',str(overview)],out/'concat.log')
    outputs={}
    for name,path,dims in [('youtube',overview,(1280,720)),('tiktok',out/'tiktok-demo.mp4',(1080,1920)),('youtube-result',out/'youtube-result.mp4',(1280,720))]:
        info=probe(path); v=next(s for s in info['streams'] if s['codec_type']=='video')
        if (v['width'],v['height'])!=dims or v['r_frame_rate']!='30/1' or v.get('sample_aspect_ratio')!='1:1' or any(v.get(k)!='bt709' for k in ['color_space','color_transfer','color_primaries']) or not any(s['codec_type']=='audio' and s['codec_name']=='aac' for s in info['streams']):
            raise ValueError(f'{name}: format check failed')
        run(['ffmpeg','-hide_banner','-nostdin','-v','error','-i',str(path),'-f','null','-'],out/f'{name}-decode.log')
        outputs[name]={'filename':path.name,'sha256':fingerprint(path)['sha256'],'duration':float(info['format']['duration']),'dimensions':dims,'full_decode':'pass'}
        if name!='youtube-result':
            run(['ffmpeg','-hide_banner','-nostdin','-y','-ss','2' if name=='tiktok' else '7','-i',str(path),'-frames:v','1',str(docs/f'{name}-poster.png')],out/f'{name}-poster.log')
    # One small overview GIF; individual results use still posters and sound-enabled links.
    palette=out/'palette.png'
    run(['ffmpeg','-hide_banner','-nostdin','-y','-i',str(overview),'-vf','fps=3,scale=480:-2:flags=lanczos,palettegen=max_colors=48',str(palette)],out/'palette.log')
    run(['ffmpeg','-hide_banner','-nostdin','-y','-i',str(overview),'-i',str(palette),'-filter_complex','[0:v]fps=3,scale=480:-2:flags=lanczos[x];[x][1:v]paletteuse=dither=bayer:bayer_scale=4',str(docs/'youtube-preview.gif')],out/'gif.log')
    result={'source_sha256':provenance['source_sha256'],'source_kind':'synthetic','font_sha256':fingerprint(chosen_font)['sha256'],'pause_removed_seconds':removed_gap,'retained_words':{'youtube':41,'tiktok':17},'comparison_source_interval':[excerpt_start,excerpt_end],'outputs':outputs,'human_listening':'not_performed','fcp_gui':'not_performed','platform_playback':'not_performed','screen_recording':False}
    (out/'manifest.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(result,ensure_ascii=False,indent=2))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sample',type=Path,required=True)
    parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--docs-output',type=Path,default=ROOT/'docs/demo')
    parser.add_argument('--font',type=Path)
    parser.add_argument('--youtube-session',type=Path)
    parser.add_argument('--tiktok-session',type=Path)
    a=parser.parse_args()
    build(a.sample,a.out,a.docs_output,a.font,a.youtube_session,a.tiktok_session)
