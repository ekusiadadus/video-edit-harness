"""Decode one trimmed CFR loop period; repeat its frames without PTS drift."""

from fractions import Fraction
import json
from pathlib import Path
import subprocess

from .common import fingerprint


def prepare_video_loop(source, cue, fps, output, *, log_path):
    source, output = Path(source), Path(output)
    if output.exists():
        raise FileExistsError(output)
    rate = Fraction(str(fps))
    first, end = (Fraction(str(cue[key])) * rate for key in ('output_start', 'output_end'))
    if rate <= 0 or first.denominator != 1 or end.denominator != 1 or first < 0 or end <= first:
        raise ValueError('Video loops need an exact frame-aligned output interval')
    before = fingerprint(source)
    start, stop = (format(float(Fraction(str(cue[key]))), '.9f') for key in ('source_start', 'source_end'))
    graph = (f'trim=start={start}:end={stop},setpts=PTS-STARTPTS,'
             f'fps=fps={rate}:start_time=0:round=near,'
             f'settb=expr={rate.denominator}/{rate.numerator},setpts=N,format=bgra')
    command = ['ffmpeg', '-v', 'error', '-nostdin', '-i', str(source), '-an', '-vf', graph,
               '-c:v', 'ffv1', '-level', '3', '-pix_fmt', 'bgra', '-fps_mode', 'passthrough', str(output)]
    result = subprocess.run(command, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    Path(log_path).write_text(json.dumps(command) + '\n' + result.stderr.decode(errors='replace'))
    try:
        if result.returncode:
            raise ValueError('Unable to decode video loop period; inspect retained log')
        from .overlay_layers import _probe
        info = _probe(output)
        if info['frame_count'] < 1 or info['fps'] != rate or info['pix_fmt'] != 'bgra':
            raise ValueError('Video loop period has no frames or an invalid CFR clock')
        if fingerprint(source) != before:
            raise ValueError('Video loop source changed during period decode')
        period = fingerprint(output)
        return {'cue_id': cue['id'], 'source_sha256': before['sha256'],
                'source_start': cue['source_start'], 'source_end': cue['source_end'],
                'period_sha256': period['sha256'], 'period_bytes': period['bytes'],
                'period_frames': info['frame_count'], 'fps': str(rate),
                'output_first_frame': int(first), 'output_end_frame_exclusive': int(end),
                'policy': 'trim_and_conform_once_then_repeat_decoded_frames_on_project_clock'}
    except Exception:
        output.unlink(missing_ok=True)
        raise
