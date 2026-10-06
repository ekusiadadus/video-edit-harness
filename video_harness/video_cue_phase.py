"""Retain the actual secondary-video samples through a cue phase map.

The old cue is first composited onto a transparent canvas at the project
clock.  Raw RGBA frames are then omitted or repeated according to the map.
This keeps source trim, FFmpeg framesync, scale, placement, and opacity ahead
of the temporal edit, including source alpha where present.
"""

from __future__ import annotations

from fractions import Fraction
from pathlib import Path
import hashlib
import json
import subprocess

from .cues import validate_video_phase
from .common import fingerprint


def _read_frame(stream, size):
    chunks = []
    remaining = size
    while remaining:
        chunk = stream.read(remaining)
        if not chunk:
            break
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def capture_overlay_clock(source, cue, rate):
    """Observe the original base picture clock instead of inventing timestamps."""
    rate = Fraction(rate)
    first = Fraction(str(cue['output_start'])) * rate
    end = Fraction(str(cue['output_end'])) * rate
    if first.denominator != 1 or end.denominator != 1 or not 1 <= end-first <= 4096:
        return None
    before = fingerprint(source)
    document = json.loads(subprocess.check_output(['ffprobe', '-v', 'error', '-select_streams', 'v:0',
        '-show_streams', '-show_frames', '-show_entries',
        'stream=time_base:frame=best_effort_timestamp', '-of', 'json', str(source)]))
    after = fingerprint(source)
    if before != after:
        raise ValueError('Overlay base changed while observing its clock')
    ticks = [int(row['best_effort_timestamp']) for row in document['frames']]
    if first < 0 or end > len(ticks):
        raise ValueError('Overlay interval exceeds observed base frames')
    return {'cue_id': cue['id'], 'base_sha256': before['sha256'],
            'original_start_frame': first.numerator, 'original_frame_count': int(end-first),
            'original_time_base': document['streams'][0]['time_base'],
            'original_timestamps': ticks[first.numerator:end.numerator]}


def _clock_expression(ticks):
    """Compact exact observed timestamps into piecewise arithmetic runs."""
    runs = []
    index = 0
    while index < len(ticks):
        step = ticks[index+1]-ticks[index] if index+1 < len(ticks) else 0
        end = index+1
        while end < len(ticks) and ticks[end] == ticks[index] + (end-index)*step:
            end += 1
        runs.append((index, f'{ticks[index]}+(N-{index})*{step}'))
        index = end
    def tree(rows):
        if len(rows) == 1:
            return rows[0][1]
        half = len(rows)//2
        return f'if(lt(N,{rows[half][0]}),{tree(rows[:half])},{tree(rows[half:])})'
    expression = tree(runs)
    if len(expression) > 65536:
        raise ValueError('Observed video cue clock exceeds expression limits')
    return expression


def retime_video_cue_layer(source, cue, placement, canvas_size, rate, output, *, log_path=None):
    """Write a lossless, full-canvas alpha layer with the mapped cue frames.

    The caller verifies the original asset hash and CFR clock, and validates
    phase-map shape.  This function checks the map again before starting FFmpeg
    so direct callers cannot request an unbounded or backward stream.
    """
    phase = validate_video_phase(cue, rate)
    if phase is None:
        raise ValueError('Video cue layer requires a phase map')
    old_count, frames = phase['original_frame_count'], phase['frames']
    if (type(old_count) is not int or not 1 <= old_count <= 4096 or
            not isinstance(frames, list) or not 1 <= len(frames) <= 4096 or
            any(type(frame) is not int or not 0 <= frame < old_count for frame in frames) or
            any(a > b for a, b in zip(frames, frames[1:]))):
        raise ValueError('Invalid video cue phase map')
    rate = Fraction(rate)
    if rate <= 0:
        raise ValueError('Invalid video cue project rate')
    width, height = canvas_size
    if width <= 0 or height <= 0:
        raise ValueError('Invalid video cue canvas')
    old_duration = Fraction(old_count, 1) / rate
    if Fraction(str(cue['source_end'])) - Fraction(str(cue['source_start'])) < old_duration:
        raise ValueError('Video cue source is shorter than original phase duration')
    output = Path(output)
    if output.exists():
        raise FileExistsError(output)
    expected_sha = cue.get('_source_sha256')
    if not isinstance(expected_sha, str) or len(expected_sha) != 64:
        raise ValueError('Video cue source SHA-256 is missing')
    source = Path(source)
    if fingerprint(source)['sha256'] != expected_sha:
        raise ValueError('Video cue source SHA-256 mismatch before sampling')
    original_start_frame = phase['original_start_frame']
    if type(original_start_frame) is not int or original_start_frame < 0:
        raise ValueError('Invalid video cue original start frame')
    original_start = format(float(Fraction(original_start_frame, 1) / rate), '.9f')
    original_end = format(float(Fraction(original_start_frame + old_count, 1) / rate), '.17g')
    gate_start = format(float(Fraction(original_start_frame, 1) / rate), '.17g')
    original_tb = Fraction(phase['original_time_base'])
    original_clock = _clock_expression(phase['original_timestamps'])
    source_start = format(float(Fraction(str(cue['source_start']))), '.9f')
    source_end = format(float(Fraction(str(cue['source_end']))), '.9f')
    source_filter = (f"[1:v]trim=start={source_start}:end={source_end},"
                     f"setpts=PTS-STARTPTS+{original_start}/TB,"
                     f"scale={placement['rendered_size'][0]}:{placement['rendered_size'][1]},"
                     f"format=rgba,colorchannelmixer=aa={placement['opacity']}[layer]")
    graph = (f"[0:v]settb=expr={original_tb.numerator}/{original_tb.denominator},"
             f"setpts='{original_clock}',format=rgba,colorchannelmixer=aa=0[canvas];"
             f"{source_filter};"
             f"[canvas][layer]overlay=x={placement['x_pixels']}:y={placement['y_pixels']}:"
             f"enable='between(t,{gate_start},{original_end})':"
             "eof_action=pass:shortest=0:format=auto,format=rgba[out]")
    # Put the generated canvas on input 0, matching the normal overlay order.
    producer_command = [
        "ffmpeg", "-v", "error", "-nostdin", "-f", "lavfi", "-i",
        f"color=c=black:s={width}x{height}:r={rate}:d={format(float(old_duration), '.9f')}",
        "-i", str(source), "-filter_complex", graph, "-map", "[out]",
        "-frames:v", str(old_count), "-fps_mode", "passthrough", "-f", "rawvideo",
        "-pix_fmt", "rgba", "pipe:1"]
    consumer_command = ["ffmpeg", "-v", "error", "-nostdin", "-y", "-f", "rawvideo",
                        "-pixel_format", "rgba", "-video_size", f"{width}x{height}",
                        "-framerate", str(rate), "-i", "pipe:0", "-frames:v", str(len(frames)),
                        "-c:v", "ffv1", "-level", "3", "-pix_fmt", "bgra", str(output)]
    frame_bytes = width * height * 4
    log_path = Path(log_path) if log_path is not None else output.with_suffix('.phase.log')
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open('w') as log:
        log.write(json.dumps({'producer': producer_command, 'consumer': consumer_command}) + '\n')
        log.flush()
        producer = subprocess.Popen(producer_command, stdout=subprocess.PIPE, stderr=log)
        consumer = None
        try:
            consumer = subprocess.Popen(consumer_command, stdin=subprocess.PIPE, stderr=log)
            assert producer.stdout is not None and consumer.stdin is not None
            requested = iter(enumerate(frames))
            pending = next(requested, None)
            for old_index in range(old_count):
                picture = _read_frame(producer.stdout, frame_bytes)
                if len(picture) != frame_bytes:
                    raise ValueError('Video cue layer ended before original phase frame count')
                while pending is not None and pending[1] == old_index:
                    consumer.stdin.write(picture)
                    pending = next(requested, None)
            if pending is not None or producer.stdout.read(1):
                raise ValueError('Video cue layer frame count is inconsistent')
            consumer.stdin.close()
            producer.stdout.close()
            if producer.wait() or consumer.wait():
                raise ValueError('Video cue phase encoding failed; see raw FFmpeg log')
        except Exception:
            producer.kill()
            if consumer is not None:
                consumer.kill()
                if consumer.stdin is not None and not consumer.stdin.closed:
                    consumer.stdin.close()
                consumer.wait()
            producer.wait()
            output.unlink(missing_ok=True)
            raise
    if fingerprint(source)['sha256'] != expected_sha:
        output.unlink(missing_ok=True)
        raise ValueError('Video cue source SHA-256 mismatch after sampling')
    digest = hashlib.sha256(json.dumps(phase, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    return {'cue_id': cue['id'], 'source_sha256': cue['_source_sha256'],
            'phase_map_sha256': digest, 'phase_map': phase,
            'original_frame_count': old_count, 'frame_count': len(frames),
            'output_fps': str(rate), 'content': 'lossless_rgba_layer_remap'}
