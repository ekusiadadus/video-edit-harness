"""Local portrait derivatives of already graded Rec.709 edits; no uploads."""
from pathlib import Path
import hashlib
import importlib
import importlib.metadata
import math
import re
import shutil
import subprocess

from PIL import Image, ImageDraw, ImageFont, __version__ as pillow_version

from .common import fingerprint, probe, run, write
from .media import stream_bounds, verify

WIDTH, HEIGHT, FPS = 1080, 1920, 30


def load_captions(path, duration):
    text = Path(path).read_text(encoding='utf-8-sig').replace('\r\n', '\n')
    cues = []
    def seconds(value):
        h, m, s, ms = map(int, re.split('[:,]', value))
        if m >= 60 or s >= 60:
            raise ValueError('Invalid SRT timestamp')
        return h*3600+m*60+s+ms/1000
    for block in re.split(r'\n\s*\n', text.strip()):
        lines = block.splitlines()
        if len(lines) < 3 or not lines[0].isdigit():
            raise ValueError('Expected numbered SRT cues')
        match = re.fullmatch(r'(\d{2}:\d{2}:\d{2},\d{3}) --> (\d{2}:\d{2}:\d{2},\d{3})', lines[1])
        if not match:
            raise ValueError('Invalid SRT time range')
        start, end = map(seconds, match.groups())
        if not 0 <= start < end <= duration+.05 or (cues and start < cues[-1]['end']):
            raise ValueError('SRT overlaps or lies outside this input edit')
        caption = '\n'.join(lines[2:]).strip()
        if not caption or any(c in caption for c in ('<', '>', '{', '}')):
            raise ValueError('Use plain-text SRT captions')
        cues.append({'start': start, 'end': end, 'text': caption})
    return cues


def caption_font(cues, font_path=None):
    if font_path:
        return ImageFont.truetype(str(font_path), 52)
    paths = ['/System/Library/Fonts/ヒラギノ角ゴシック W3.ttc',
             '/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc',
             '/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc']
    for path in paths:
        if Path(path).is_file():
            return ImageFont.truetype(path, 52)
    if any(ord(c) > 127 for cue in cues for c in cue['text']):
        raise ValueError('CJK captions need a local CJK font; pass --font or install one')
    return ImageFont.load_default(size=52)


def resolve_caption_layout(setting):
    """Validate an explicit measured-wrap request and bind optional runtimes."""
    if (not isinstance(setting, dict) or set(setting) != {'version', 'language', 'protected_phrases'}
            or type(setting['version']) is not int or setting['version'] != 1
            or setting['language'] not in ('ja', 'en')
            or not isinstance(setting['protected_phrases'], list)
            or any(not isinstance(p, str) or not p or '\n' in p or '\r' in p
                   for p in setting['protected_phrases'])
            or len(set(setting['protected_phrases'])) != len(setting['protected_phrases'])):
        raise ValueError('caption_layout requires version 1, ja/en, and unique nonempty protected phrases')
    try:
        importlib.import_module('regex')
        regex_version = importlib.metadata.version('regex')
        budoux_version = None
        if setting['language'] == 'ja':
            importlib.import_module('budoux')
            budoux_version = importlib.metadata.version('budoux')
    except (ImportError, importlib.metadata.PackageNotFoundError) as exc:
        raise ImportError('Caption layout needs the text-layout extra; install with uv sync --extra text-layout') from exc
    return {**setting, 'protected_phrases': list(setting['protected_phrases']),
            'max_width': 820, 'max_lines': 3, 'max_codepoints': 512,
            'runtime': {'regex': regex_version, 'budoux': budoux_version}}


def _caption_ink_measure(measure, font, value):
    """Include advance, visible overhang and the stroke used by the tile."""
    left, _, right, _ = measure.textbbox((0, 0), value, font=font, stroke_width=1)
    bearing = min(left, 0)
    return max(right, measure.textlength(value, font=font)) - bearing, bearing


def _wrapped_caption_lines(text, font, layout, measure):
    if len(text) > 512:
        raise ValueError('Caption exceeds 512 Unicode codepoints; split the reviewed cue')
    from .text_layout import wrap_text
    lines = wrap_text(text, layout['language'], 820,
                      lambda value: _caption_ink_measure(measure, font, value)[0],
                      max_lines=3, protected_phrases=layout['protected_phrases'])
    if any(_caption_ink_measure(measure, font, line)[0] > 820 for line in lines):
        raise ValueError('Caption measured line exceeds 820 pixels')
    return lines


def caption_images(cues, font, layout=None, rendered_lines=None):
    # Yield one tile at a time; lengthy transcripts must not retain all images.
    measure = ImageDraw.Draw(Image.new('RGB', (1, 1)))
    for index, cue in enumerate(cues):
        if layout is not None:
            if rendered_lines is not None and index < len(rendered_lines):
                lines = rendered_lines[index]['lines']
            else:
                lines = _wrapped_caption_lines(cue['text'], font, layout, measure)
            if rendered_lines is not None and index >= len(rendered_lines):
                rendered_lines.append({'start': cue['start'], 'end': cue['end'],
                                       'text': cue['text'], 'lines': lines.copy()})
        else:
            lines = []
            for original in cue['text'].splitlines():
                line = ''
                for char in original:
                    candidate = line+char
                    if measure.textlength(candidate, font=font) > 820 and line:
                        lines.append(line); line = char
                    else:
                        line = candidate
                if line:
                    lines.append(line)
        if len(lines) > 3:
            raise ValueError('Caption exceeds three readable lines; split the reviewed cue')
        tile = Image.new('RGBA', (860, 42+72*len(lines)), (0, 0, 0, 0))
        draw = ImageDraw.Draw(tile)
        draw.rounded_rectangle((0, 0, tile.width-1, tile.height-1), radius=18, fill=(8, 12, 20, 224))
        for index, line in enumerate(lines):
            left = _caption_ink_measure(measure, font, line)[1] if layout is not None else 0
            draw.text((20-left, 12+72*index), line, font=font, fill='white', stroke_width=1, stroke_fill='black')
        yield cue, tile


def export_vertical(source, out, framing='fit', subtitles=None, font=None, *, caption_layout=None):
    source, out = Path(source).expanduser().resolve(), Path(out).expanduser().resolve()
    if framing not in ('fit', 'center_crop'):
        raise ValueError('Framing must be fit or center_crop')
    original = fingerprint(source)
    info = probe(source)
    video = next((s for s in info['streams'] if s['codec_type']=='video'), None)
    if not video or any(video.get(k) != 'bt709' for k in ('color_space','color_transfer','color_primaries')):
        raise ValueError('Input must already be graded and tagged SDR/Rec.709; convert Apple Log/HDR first')
    start, end = stream_bounds(info, 'video')
    if abs(start) > .05:
        raise ValueError('Use a zero-based graded edit for vertical export')
    duration = end-start
    if not math.isfinite(duration):
        raise ValueError('Invalid input duration')
    audio = next((s for s in info['streams'] if s['codec_type']=='audio'), None)
    subtitle_id = fingerprint(subtitles) if subtitles else None
    cues = load_captions(subtitles, duration) if subtitles else []
    resolved_layout = resolve_caption_layout(caption_layout) if caption_layout is not None else None
    used_font = caption_font(cues, font) if cues else None
    font_path = getattr(used_font, 'path', None)
    font_id = fingerprint(font_path) if isinstance(font_path, (str, Path)) else (
        {'kind': 'pillow_default', 'pillow_version': pillow_version,
         'sha256': hashlib.sha256(bytes(used_font.getmask('The quick brown fox 0123456789'))).hexdigest()}
        if used_font else None)
    rendered_lines = None
    if resolved_layout is not None:
        measure = ImageDraw.Draw(Image.new('RGB', (1, 1))) if cues else None
        rendered_lines = [{'start': cue['start'], 'end': cue['end'], 'text': cue['text'],
                           'lines': _wrapped_caption_lines(cue['text'], used_font, resolved_layout, measure)}
                          for cue in cues]
    tiles = iter(caption_images(cues, used_font, resolved_layout, rendered_lines)) if cues else iter(())
    out.mkdir(parents=True, exist_ok=False)
    try:
        verify(source, out/'input-check', require_audio=bool(audio), expected_audio_range=stream_bounds(info,'audio') if audio else None)
        # Honor non-square source pixels before fitting; FFmpeg autorotates inputs.
        geometry = 'scale=trunc(iw*sar/2)*2:ih,setsar=1,'
        geometry += ('scale=1080:1920:force_original_aspect_ratio=decrease:force_divisible_by=2,pad=1080:1920:(ow-iw)/2:(oh-ih)/2:color=0x10131a'
                     if framing=='fit' else 'scale=1080:1920:force_original_aspect_ratio=increase:force_divisible_by=2,crop=1080:1920')
        geometry += ',setsar=1,fps=30,setparams=color_primaries=bt709:color_trc=bt709:colorspace=bt709'
        target = out/'video.mp4'
        encoding = ['-c:v','libx264','-preset','fast','-crf','20','-pix_fmt','yuv420p',
                    '-color_primaries','bt709','-color_trc','bt709','-colorspace','bt709',
                    '-metadata:s:v:0','rotate=0','-movflags','+faststart']
        audio_args = ['-c:a','copy'] if audio and audio.get('codec_name')=='aac' else ['-c:a','aac','-b:a','192k']
        if not cues:
            run(['ffmpeg','-hide_banner','-nostdin','-i',str(source),'-map','0:v:0','-map','0:a:0?',
                 '-vf',geometry,*encoding,*audio_args,str(target)], out/'render.log')
        else:
            with (out/'decode-frames.log').open('w') as dec_log, (out/'render.log').open('w') as enc_log:
                decoder = subprocess.Popen(['ffmpeg','-hide_banner','-nostdin','-i',str(source),'-an','-vf',geometry,
                                            '-f','rawvideo','-pix_fmt','rgb24','pipe:1'], stdout=subprocess.PIPE, stderr=dec_log)
                encoder = None
                try:
                    encoder = subprocess.Popen(['ffmpeg','-hide_banner','-nostdin','-f','rawvideo','-pixel_format','rgb24',
                        '-video_size','1080x1920','-framerate','30','-i','pipe:0','-i',str(source),
                        '-map','0:v:0','-map','1:a:0?','-vf','scale=out_color_matrix=bt709:out_range=tv,format=yuv420p,setsar=1,setparams=color_primaries=bt709:color_trc=bt709:colorspace=bt709',*encoding,*audio_args,str(target)],stdin=subprocess.PIPE,stderr=enc_log)
                    size = WIDTH*HEIGHT*3; index = 0; active = next(tiles, None)
                    while True:
                        data = decoder.stdout.read(size)
                        if not data:
                            break
                        if len(data)!=size:
                            raise ValueError('Incomplete decoded video frame')
                        frame = Image.frombytes('RGB',(WIDTH,HEIGHT),data)
                        t = index/FPS
                        while active and t>=active[0]['end']:
                            active = next(tiles, None)
                        if active and active[0]['start']<=t<active[0]['end']:
                            tile=active[1]
                            frame.paste(tile,(80,1480-tile.height),tile)
                        encoder.stdin.write(frame.tobytes()); index += 1
                    encoder.stdin.close()
                    if decoder.wait()!=0 or encoder.wait()!=0:
                        raise ValueError('Vertical frame encoding failed; inspect render/decode logs')
                finally:
                    decoder.stdout.close()
                    for process in (decoder,encoder):
                        if process is not None and process.poll() is None:
                            process.kill(); process.wait()
                    if encoder is not None and encoder.stdin and not encoder.stdin.closed:
                        encoder.stdin.close()
            shutil.copyfile(subtitles,out/'subtitles.srt')
        audio_range = stream_bounds(info,'audio') if audio else None
        checked=verify(target,out/'output-check',expected_duration=duration,require_audio=bool(audio),expected_audio_range=audio_range)
        stream=next(s for s in checked['streams'] if s['codec_type']=='video')
        if (stream['width'],stream['height'],stream.get('sample_aspect_ratio'))!=(1080,1920,'1:1'):
            raise ValueError('Portrait dimensions or pixel aspect verification failed')
        if fingerprint(source)!=original:
            raise ValueError('Source changed during export')
        if subtitles and fingerprint(subtitles)!=subtitle_id:
            raise ValueError('Subtitle file changed during export')
        if font_id and font_id.get('path') and fingerprint(font_id['path'])!=font_id:
            raise ValueError('Font file changed during export')
        result={'version':1,'source':original,'video':fingerprint(target),'framing':framing,
                'width':1080,'height':1920,'fps':30,'duration':duration,'subtitles_burned':bool(cues),
                'subtitles_source':subtitle_id,
                'font_source':font_id,
                'technical_status':'pass','perceptual_status':'not_reviewed','platform_playback':'not_checked',
                'caption_margins':'Working placement only; verify actual TikTok UI. No official safe-zone guarantee.',
                'fcpxml':'Source-aspect XML is unchanged; portrait framing requires separate FCP application/review.'}
        if resolved_layout is not None:
            result['caption_layout'] = resolved_layout
            result['caption_lines'] = rendered_lines
        write(out/'result.json',result)
        return result
    except BaseException as exc:
        if not (out/'result.json').exists():
            write(out/'result.json',{'technical_status':'failed','error':str(exc),'source':original})
        raise
