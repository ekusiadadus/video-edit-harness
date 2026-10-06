"""Render a short, frame-matched effect comparison from two sealed full renders."""

from fractions import Fraction
from html import escape
import json
from pathlib import Path
import subprocess

from .common import fingerprint, read, run, write
from .feedback import map_output
from .media import stream_bounds
from .runs import evidence_run
from .session import check_ref, digest
from .video_effects import _probe, _verified_rate


def _parent(render):
    if not isinstance(render, dict) or render.get('preview') is not False:
        raise ValueError('Effect excerpts require a registered full render')
    files = render.get('files')
    if not isinstance(files, dict) or not {'video', 'mapping'} <= files.keys():
        raise ValueError('Full render video and mapping are required')
    video = check_ref(files['video'])
    mapping_path = check_ref(files['mapping'])
    mapping = read(mapping_path)
    if not isinstance(mapping, dict) or not isinstance(mapping.get('frame_count'), int) or isinstance(mapping['frame_count'], bool):
        raise ValueError('Invalid full render frame count')
    try:
        rate = Fraction(str(mapping['fps']))
        duration = Fraction(str(mapping['duration']))
    except (KeyError, TypeError, ValueError, ZeroDivisionError) as exc:
        raise ValueError('Invalid full render FPS') from exc
    if rate <= 0 or mapping['frame_count'] <= 0:
        raise ValueError('Invalid full render frame count or FPS')
    if abs(duration * rate - mapping['frame_count']) > Fraction(1, 100):
        raise ValueError('Full render mapping duration differs from its frame count')
    return video, mapping, rate


def _media_shape(path, rate, count):
    info = _probe(path, count=True)
    videos = [s for s in info['streams'] if s['codec_type'] == 'video']
    audios = [s for s in info['streams'] if s['codec_type'] == 'audio']
    if len(videos) != 1 or not audios:
        raise ValueError('Each full render needs one video track and audio')
    video = videos[0]
    if video.get('pix_fmt') != 'yuv420p':
        raise ValueError('Effect excerpts require an 8-bit yuv420p completed MP4')
    if int(video.get('nb_read_frames', -1)) != count or _verified_rate(path, video, count) != rate:
        raise ValueError('Full render FPS differs from its frame mapping')
    duration = Fraction(count, 1) / rate
    video_range = stream_bounds(info, 'video')
    audio_range = stream_bounds(info, 'audio')
    if video_range is None or audio_range is None or abs(video_range[0]) > .02 or abs(video_range[1] - float(duration)) > .02:
        raise ValueError('Full render video track does not cover its mapped timeline')
    if audio_range[0] > .05 or audio_range[1] < float(duration) - .05:
        raise ValueError('Full render audio does not cover its mapped timeline')
    return int(video['width']), int(video['height'])


def _excerpt(source, target, first, end, rate, log):
    # The decoded video frame index is the authority. The 48 kHz sample clock
    # places audio boundaries at the nearest representable samples.
    first_sample = round(Fraction(first * 48000, 1) / rate)
    end_sample = round(Fraction(end * 48000, 1) / rate)
    vf = f'trim=start_frame={first}:end_frame={end},setpts=N*{rate.denominator}/({rate.numerator}*TB)'
    af = (f'aresample=48000:first_pts=0,atrim=start_sample={first_sample}:'
          f'end_sample={end_sample},asetpts=PTS-STARTPTS')
    run(['ffmpeg', '-hide_banner', '-nostdin', '-y', '-i', str(source),
         '-filter_complex', f'[0:v:0]{vf}[v];[0:a:0]{af}[a]',
         '-map', '[v]', '-map', '[a]',
         '-fps_mode:v', 'passthrough', '-c:v', 'libx264', '-preset', 'fast', '-qp', '0',
         '-pix_fmt', 'yuv420p',
         '-c:a', 'aac', '-b:a', '384k', '-ar', '48000',
         '-map_metadata', '-1', '-movflags', '+faststart', str(target)], log)


def _check_excerpt(path, count, rate, shape, log):
    info = _probe(path, count=True)
    videos = [s for s in info['streams'] if s['codec_type'] == 'video']
    audios = [s for s in info['streams'] if s['codec_type'] == 'audio']
    if len(videos) != 1 or len(audios) != 1:
        raise ValueError('Excerpt must contain one video and one audio track')
    video = videos[0]
    if (int(video.get('nb_read_frames', -1)) != count or
            _verified_rate(path, video, count) != rate or
            (int(video['width']), int(video['height'])) != shape):
        raise ValueError('Excerpt frame count, FPS, or dimensions differ from parent')
    duration = float(Fraction(count, 1) / rate)
    video_range = stream_bounds(info, 'video')
    audio_range = stream_bounds(info, 'audio')
    if (video_range is None or audio_range is None or
            abs(video_range[0]) > .02 or abs(video_range[1] - duration) > .02 or
            abs(audio_range[0]) > .05 or abs(audio_range[1] - duration) > .05):
        raise ValueError('Excerpt video/audio coverage is incomplete')
    run(['ffmpeg', '-v', 'error', '-xerror', '-i', str(path),
         '-map', '0:v:0', '-map', '0:a:0', '-f', 'null', '-'], log)


def _page(before, after, first, end, rate):
    start = float(Fraction(first, 1) / rate)
    stop = float(Fraction(end, 1) / rate)
    rows = [("変更前", before), ("変更後", after)]
    cards = ''.join(f'<article><h2>{label}</h2><video preload="metadata" playsinline '
                    f'src="{escape(ref["path"], quote=True)}"></video>'
                    f'<p>Parent SHA-256: <code>{escape(ref["sha256"])}</code></p></article>'
                    for label, ref in rows)
    return ('''<!doctype html><html lang="ja"><meta charset="utf-8">
<meta name="viewport" content="width=device-width"><title>エフェクト範囲の比較</title>
<style>body{font:16px system-ui;background:#171717;color:#eee;margin:24px}
main{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:18px}
article{padding:12px;border:1px solid #777;border-radius:8px}video{width:100%}
button,input{font:inherit;margin:6px;padding:8px}code{overflow-wrap:anywhere;font-size:11px}</style>
<h1>エフェクト範囲の比較</h1>
<p>元の完成動画の出力範囲: ''' + f'{start:.6f}–{stop:.6f}' + ''' 秒。この短い動画は0秒から始まります。
音声はAACで再符号化されています。映像・音声の人による確認は未実施です。</p>
<button id="play">再生／停止</button><button id="restart">先頭に戻す</button>
<label>再生位置 <input id="seek" type="range" min="0" max="''' +
            f'{stop-start:.9f}' + '''" step="0.001" value="0"></label>
<button id="audio">音声: 変更前</button><output id="time">0.000秒</output>
<p id="status" role="status"></p><main>''' + cards + '''</main>
<script>
const videos=[...document.querySelectorAll('video')],seek=document.querySelector('#seek');
const status=document.querySelector('#status');let playing=false,audio=0;
videos[1].muted=true;
function stop(){playing=false;videos.forEach(v=>v.pause());}
function position(t){videos.forEach(v=>{if(Number.isFinite(t))v.currentTime=t;});seek.value=t;}
document.querySelector('#play').onclick=async()=>{if(playing){stop();return;}
if(!videos.every(v=>v.readyState>=1)){status.textContent='両方の動画の読み込みを待ってください';return;}
try{await Promise.all(videos.map(v=>v.play()));playing=true;status.textContent='再生中';}
catch(e){stop();status.textContent='再生に失敗しました';}};
document.querySelector('#restart').onclick=()=>{stop();position(0);};
seek.oninput=()=>{stop();position(Number(seek.value));};
document.querySelector('#audio').onclick=()=>{audio=1-audio;videos.forEach((v,i)=>v.muted=i!==audio);
document.querySelector('#audio').textContent='音声: '+(audio?'変更後':'変更前');};
videos.forEach(v=>{v.addEventListener('loadedmetadata',()=>{
const durations=videos.map(x=>x.duration).filter(Number.isFinite);
if(durations.length===videos.length)seek.max=String(Math.min(...durations));});
v.addEventListener('ended',()=>{stop();status.textContent='再生が終了しました';});
v.addEventListener('error',()=>{stop();status.textContent='動画を読み込めませんでした';});});
function tick(){if(playing){const t=videos[0].currentTime;seek.value=t;
if(Math.abs(videos[1].currentTime-t)>.12)videos[1].currentTime=t;}
document.querySelector('#time').textContent=Number(seek.value).toFixed(3)+'秒';
requestAnimationFrame(tick);}tick();
</script></html>''')


def export_effect_preview(original_render, revised_render, folder, first_frame: int,
                          end_frame_exclusive: int, metadata: dict):
    """Return a fingerprint of preview.json; this records no approval or adoption."""
    before_path, before_mapping, rate = _parent(original_render)
    after_path, after_mapping, after_rate = _parent(revised_render)
    if digest(before_mapping) != digest(after_mapping) or rate != after_rate:
        raise ValueError('Effect comparison requires exactly equal frame mappings')
    count = before_mapping['frame_count']
    if (not isinstance(first_frame, int) or isinstance(first_frame, bool) or
            not isinstance(end_frame_exclusive, int) or isinstance(end_frame_exclusive, bool) or
            not 0 <= first_frame < end_frame_exclusive <= count or
            Fraction(end_frame_exclusive - first_frame, 1) / rate > 30):
        raise ValueError('Select a finite mapped frame interval of at most 30 seconds')
    if not isinstance(metadata, dict):
        raise ValueError('Effect preview metadata must be an object')
    json.dumps(metadata, allow_nan=False)
    before_shape = _media_shape(before_path, rate, count)
    after_shape = _media_shape(after_path, rate, count)
    if before_shape != after_shape:
        raise ValueError('Full render dimensions differ')
    first_time = Fraction(first_frame, 1) / rate
    end_time = Fraction(end_frame_exclusive, 1) / rate
    mapped = map_output(before_mapping, float(first_time), float(end_time))
    folder = Path(folder)
    started = False
    try:
        with evidence_run({'source': str(after_path)}, 'effect-preview', folder,
                          {'first_frame': first_frame, 'end_frame_exclusive': end_frame_exclusive,
                           'parent_mapping_sha256': digest(before_mapping)}) as run_manifest:
            started = True
            try:
                for name, source in (('before', before_path), ('after', after_path)):
                    target = folder / f'{name}.mp4'
                    _excerpt(source, target, first_frame, end_frame_exclusive, rate,
                             folder / f'{name}-render.log')
                    _check_excerpt(target, end_frame_exclusive - first_frame, rate,
                                   before_shape, folder / f'{name}-decode.log')
                for render in (original_render, revised_render):
                    check_ref(render['files']['video'])
                    check_ref(render['files']['mapping'])
                before_excerpt = fingerprint(folder / 'before.mp4')
                after_excerpt = fingerprint(folder / 'after.mp4')
                page = folder / 'preview.html'
                page.write_text(_page({'path': 'before.mp4', 'sha256': original_render['files']['video']['sha256']},
                                      {'path': 'after.mp4', 'sha256': revised_render['files']['video']['sha256']},
                                      first_frame, end_frame_exclusive, rate))
                preview = {
                    'version': 1, 'run_id': run_manifest['run_id'], 'kind': 'effect_excerpt_comparison',
                    'parents': {
                        'before': {'render_id': original_render['id'],
                                   'video': original_render['files']['video'],
                                   'mapping': original_render['files']['mapping']},
                        'after': {'render_id': revised_render['id'],
                                  'video': revised_render['files']['video'],
                                  'mapping': revised_render['files']['mapping']}},
                    'mapping_digest': digest(before_mapping),
                    'first_frame': first_frame, 'end_frame_exclusive': end_frame_exclusive,
                    'fps': str(rate), 'output_start': str(first_time), 'output_end': str(end_time),
                    'audio_sample_bounds': {'sample_rate': 48000,
                        'first_sample': round(first_time * 48000),
                        'end_sample_exclusive': round(end_time * 48000),
                        'rounding': 'nearest sample on parent output clock'},
                    'parent_source_mapping': mapped, 'metadata': metadata,
                    'excerpts': {'before': before_excerpt, 'after': after_excerpt},
                    'page': fingerprint(page), 'audio_encoding': 'AAC 384 kb/s, 48 kHz; re-encoded',
                    'review_status': 'pending', 'adopted': False}
                write(folder / 'preview.json', preview)
            except BaseException:
                for name in ('before.mp4', 'after.mp4', 'preview.html', 'preview.json'):
                    (folder / name).unlink(missing_ok=True)
                raise
    except BaseException:
        # Context-exit verification can fail after the body completed, too.
        # Never delete an older folder when evidence_run could not create ours.
        if started:
            for name in ('before.mp4', 'after.mp4', 'preview.html', 'preview.json'):
                (folder / name).unlink(missing_ok=True)
        raise
    return fingerprint(folder / 'preview.json')
