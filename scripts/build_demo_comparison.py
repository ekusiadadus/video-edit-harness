"""Offline BEFORE/AFTER comparison of a supplied beat-cut edit.

Inputs are already licensed, reviewed renders. This tool adds a restrained zoom
pulse; it never downloads media, supplies music, or claims platform playback.
"""
from __future__ import annotations

import argparse
from fractions import Fraction
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile


def _run(command, log):
    with Path(log).open('w', encoding='utf-8') as stream:
        stream.write(json.dumps(command, ensure_ascii=False) + '\n')
        stream.flush()
        completed = subprocess.run(command, stdout=stream, stderr=stream)
    if completed.returncode:
        detail = Path(log).read_text(encoding='utf-8', errors='replace').splitlines()[-12:]
        raise RuntimeError(f'FFmpeg failed ({completed.returncode}); see {log}: ' + ' | '.join(detail))


def _probe(path):
    return json.loads(subprocess.check_output(['ffprobe', '-v', 'error', '-show_streams',
                                               '-show_format', '-of', 'json', str(path)]))


def _video(path):
    info = _probe(path)
    picture = next((s for s in info['streams'] if s.get('codec_type') == 'video'), None)
    sound = next((s for s in info['streams'] if s.get('codec_type') == 'audio'), None)
    if picture is None or sound is None:
        raise ValueError(f'Comparison input needs video and embedded audio: {path}')
    rate = Fraction(picture.get('avg_frame_rate', '0'))
    if rate <= 0 or Fraction(picture.get('r_frame_rate', '0')) != rate:
        raise ValueError('Comparison requires a constant frame rate')
    duration = Fraction(str(picture.get('duration') or info['format']['duration']))
    if duration <= 0:
        raise ValueError('Comparison video duration must be positive')
    return {'fps': rate, 'duration': duration, 'width': int(picture['width']),
            'height': int(picture['height']), 'audio': sound}


def _sha(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(4 * 1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def _read_beats(path, duration):
    value = json.loads(Path(path).read_text())
    items = value.get('beats') if isinstance(value, dict) else value
    if not isinstance(items, list):
        raise ValueError('Beat file needs a list or {"beats": [...]}')
    times = []
    for item in items:
        if isinstance(item, dict):
            if item.get('protected_speech') is True or item.get('loop_seam_nearby') is True or item.get('cut_eligible') is False:
                continue
            point = item.get('output_time', item.get('frame_time'))
        else:
            point = item
        try:
            beat = Fraction(str(point))
        except (TypeError, ValueError, ZeroDivisionError) as exc:
            raise ValueError('Invalid output beat time') from exc
        if beat < 0 or beat > duration:
            raise ValueError('Beat lies outside the AFTER render')
        times.append(beat)
    chosen = []
    for beat in sorted(set(times)):
        if beat < Fraction(1, 5) or beat > duration - Fraction(1, 5):
            continue
        if not chosen or beat - chosen[-1] >= 1:
            chosen.append(beat)
        if len(chosen) == 12:
            break
    return chosen


def _font(explicit):
    candidates = [explicit] if explicit else [
        '/System/Library/Fonts/Supplemental/Arial.ttf',
        '/System/Library/Fonts/Supplemental/Helvetica.ttc',
        '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',
    ]
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return Path(candidate).resolve()
    raise ValueError('No usable font file; pass --font')


def _label_image(path, font_path, width, height, lines):
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError as exc:
        raise RuntimeError('Pillow is required for visible labels; run with uv run python') from exc
    canvas = Image.new('RGBA', (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(canvas)
    size = max(11, round(height * .035))
    pad = max(4, round(height * .012))
    y = max(3, round(height * .04))
    for line in lines:
        fitted = size
        while fitted > 8:
            font = ImageFont.truetype(str(font_path), fitted)
            bounds = draw.textbbox((0, 0), line, font=font)
            if bounds[2] - bounds[0] <= width - 2 * pad - 6:
                break
            fitted -= 1
        bounds = draw.textbbox((0, 0), line, font=font)
        text_width, text_height = bounds[2] - bounds[0], bounds[3] - bounds[1]
        x = max(3, round(width * .04))
        draw.rectangle((x, y, min(width - 1, x + text_width + 2 * pad),
                        min(height - 1, y + text_height + 2 * pad)), fill=(0, 0, 0, 180))
        draw.text((x + pad - bounds[0], y + pad - bounds[1]), line,
                  font=font, fill=(255, 255, 255, 255))
        y += text_height + 3 * pad
    canvas.save(path)


def _pulse_filter(rate, width, height, beats):
    # At most 12 smooth 2.5% zooms, separated by >=1 second. No flashes,
    # color pulses, or light/dark strobing are added.
    frames = [round(beat * rate) for beat in beats]
    terms = [f'max(0,1-abs(on-{frame})/5)' for frame in frames]
    envelope = '0'
    for term in terms:
        envelope = f'max({envelope},{term})'
    zoom = f'1+0.025*({envelope})'
    return (f'zoompan=z=\'{zoom}\':d=1:x=iw/2-iw/zoom/2:y=ih/2-ih/zoom/2:'
            f's={width}x{height}:fps={rate.numerator}/{rate.denominator},'
            'format=yuv420p,setsar=1')


def build(before, after, beats_file, output, font=None):
    before, after = Path(before).resolve(strict=True), Path(after).resolve(strict=True)
    if before == after:
        raise ValueError('BEFORE and AFTER must be distinct renders')
    first, second = _video(before), _video(after)
    if first['fps'] != second['fps']:
        raise ValueError('BEFORE and AFTER frame rates must match for direct comparison')
    fps = second['fps']
    width, height = second['width'], second['height']
    if width <= 0 or height <= 0 or width % 2 or height % 2:
        raise ValueError('AFTER dimensions must be positive and even')
    selected = _read_beats(beats_file, second['duration'])
    font_path = _font(font)
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    pulse_path = output / 'after-pulse.mp4'
    comparison_path = output / 'comparison.mp4'
    after_length = float(second['duration'])
    _run(['ffmpeg', '-hide_banner', '-nostdin', '-n', '-i', str(after),
          '-map', '0:v:0', '-map', '0:a:0', '-vf', _pulse_filter(fps, width, height, selected),
          '-af', f'aresample=48000:async=1:first_pts=0,apad=whole_dur={after_length},atrim=duration={after_length}',
          '-c:v', 'libx264', '-preset', 'fast', '-crf', '18', '-pix_fmt', 'yuv420p',
          '-c:a', 'aac', '-b:a', '192k', '-ar', '48000', '-ac', '2', '-t', str(after_length),
          '-movflags', '+faststart', str(pulse_path)], output / 'pulse-ffmpeg.log')
    with tempfile.TemporaryDirectory(prefix='comparison-labels-') as temporary:
        root = Path(temporary)
        before_label = root / 'before.png'
        after_label = root / 'after.png'
        _label_image(before_label, font_path, width, height, ['BEFORE  |  no added BGM'])
        _label_image(after_label, font_path, width, height,
                     ['AFTER  |  BGM + beat cuts', 'Subtle zoom on selected beats'])
        before_vf = (f'setpts=PTS-STARTPTS,fps={fps.numerator}/{fps.denominator},'
                     f'scale={width}:{height}:force_original_aspect_ratio=decrease,'
                     f'pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,setsar=1')
        after_vf = (f'setpts=PTS-STARTPTS,fps={fps.numerator}/{fps.denominator},'
                    f'scale={width}:{height}:force_original_aspect_ratio=decrease,'
                    f'pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,setsar=1')
        graph = (f'[0:v]{before_vf}[bv0];[1:v]{after_vf}[av0];'
                 '[2:v]format=rgba[bt];[3:v]format=rgba[at];'
                 '[bv0][bt]overlay=shortest=1:format=auto[bv];'
                 '[av0][at]overlay=shortest=1:format=auto[av];'
                 f'[0:a]aresample=48000:async=1:first_pts=0,aformat=channel_layouts=stereo,'
                 f'apad=whole_dur={float(first["duration"])},atrim=duration={float(first["duration"])},asetpts=PTS-STARTPTS[ba];'
                 f'[1:a]aresample=48000:async=1:first_pts=0,aformat=channel_layouts=stereo,'
                 f'apad=whole_dur={after_length},atrim=duration={after_length},asetpts=PTS-STARTPTS[aa];'
                 '[bv][ba][av][aa]concat=n=2:v=1:a=1[v][a]')
        _run(['ffmpeg', '-hide_banner', '-nostdin', '-n', '-i', str(before), '-i', str(pulse_path),
              '-loop', '1', '-framerate', str(fps), '-i', str(before_label),
              '-loop', '1', '-framerate', str(fps), '-i', str(after_label),
              '-filter_complex', graph, '-map', '[v]', '-map', '[a]',
              '-c:v', 'libx264', '-preset', 'fast', '-crf', '18', '-pix_fmt', 'yuv420p',
              '-c:a', 'aac', '-b:a', '192k', '-movflags', '+faststart', str(comparison_path)],
             output / 'comparison-ffmpeg.log')
    observed_after, observed_comparison = _video(pulse_path), _video(comparison_path)
    one_frame = Fraction(1, 1) / fps
    if abs(observed_after['duration'] - second['duration']) > one_frame:
        raise ValueError('Pulse edit changed AFTER duration by more than one frame')
    if abs(observed_comparison['duration'] - first['duration'] - second['duration']) > one_frame * 2:
        raise ValueError('Comparison duration differs from BEFORE + AFTER')
    for name, path in [('after-pulse', pulse_path), ('comparison', comparison_path)]:
        _run(['ffmpeg', '-v', 'error', '-xerror', '-i', str(path), '-f', 'null', '-'],
             output / f'{name}-decode.log')
    result = {'version': 1, 'before': {'path': str(before), 'sha256': _sha(before),
                                      'duration': float(first['duration'])},
              'after': {'path': str(after), 'sha256': _sha(after),
                        'duration': float(second['duration'])},
              'selected_beat_times': [float(point) for point in selected],
              'effect': 'smooth 2.5 percent zoom only; no flashes or color pulse',
              'font': str(font_path), 'fps': str(fps),
              'after_pulse': {'path': str(pulse_path), 'sha256': _sha(pulse_path),
                              'duration': float(observed_after['duration'])},
              'comparison': {'path': str(comparison_path), 'sha256': _sha(comparison_path),
                             'duration': float(observed_comparison['duration'])},
              'review': 'technical decode only; human visual/listening and public playback not verified'}
    (output / 'manifest.json').write_text(json.dumps(result, indent=2, ensure_ascii=False))
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--before', type=Path, required=True)
    parser.add_argument('--after', type=Path, required=True)
    parser.add_argument('--beats', type=Path, required=True, help='JSON output beat times in seconds')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--font', type=Path)
    args = parser.parse_args(argv)
    result = build(args.before, args.after, args.beats, args.output, args.font)
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == '__main__':
    main()
