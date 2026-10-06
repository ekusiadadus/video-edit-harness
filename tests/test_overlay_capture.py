"""Saved output samples must match the original render, including CFR duplication."""
from fractions import Fraction
from pathlib import Path
import subprocess
import tempfile
import unittest

import numpy as np

from video_harness.common import fingerprint, write
from video_harness.overlay_placement import measure_placement
from video_harness.session import Session
from video_harness.visual import render_overlays
from test_video_cue_phase import pictures, registered, run


class OverlayCaptureTests(unittest.TestCase):
    def _case(self, coarse=False, alpha=False):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            rate = Fraction(30000, 1001)
            width, height = 160, 90
            source, base = root / 'secondary.mkv', root / 'base.mp4'
            channels = 4 if alpha else 3
            frames = np.empty((24, height, width, channels), dtype=np.uint8)
            for i in range(24):
                frames[i, :, :, :3] = [(73*i)%256, (151*i)%256, (197*i)%256]
                if alpha:
                    frames[i, :, :, 3] = [64, 192, 128, 255][i%4]
            subprocess.run(['ffmpeg', '-v', 'error', '-f', 'rawvideo', '-pix_fmt',
                'rgba' if alpha else 'rgb24', '-s:v', '160x90', '-r', '24', '-i', 'pipe:0',
                '-c:v', 'ffv1', '-pix_fmt', 'bgra' if alpha else 'yuv444p', str(source)],
                input=frames.tobytes(), capture_output=True, check=True)
            run('-f', 'lavfi', '-i', f'color=c=0x202030:s=160x90:r={rate}:d=1',
                '-f', 'lavfi', '-i', 'sine=frequency=440:sample_rate=48000:duration=1',
                '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-c:a', 'aac', base)
            if coarse:
                remux = root / 'coarse.mkv'
                run('-i', base, '-map', '0', '-c', 'copy', '-avoid_negative_ts', 'disabled', remux)
                base = remux
            first, end = 3, 11
            cue = {'id': 'secondary', 'asset_id': 'secondary', 'role': 'video',
                   'source_start': str(Fraction(2, 24)), 'source_end': str(Fraction(14, 24)),
                   'output_start': str(first/rate), 'output_end': str(end/rate),
                   'position': 'top', 'opacity': .6}
            output, legacy = root / 'saved.mp4', root / 'legacy.mp4'
            result = render_overlays(base, [cue], [registered(source)], output, 1)
            placement = measure_placement(cue, width, height, width, height)
            graph = (f"[1:v]trim=start={float(Fraction(2,24)):.9f}:end={float(Fraction(14,24)):.9f},"
                     f"setpts=PTS-STARTPTS+{cue['output_start']}/TB,"
                     f"scale={placement['rendered_size'][0]}:{placement['rendered_size'][1]},"
                     "format=rgba,colorchannelmixer=aa=0.6[layer];"
                     f"[0:v][layer]overlay=x={placement['x_pixels']}:y={placement['y_pixels']}:"
                     f"enable='between(t,{cue['output_start']},{cue['output_end']})':"
                     "eof_action=pass:shortest=0[v]")
            run('-i', base, '-i', source, '-filter_complex', graph, '-map', '[v]',
                '-map', '0:a?', '-c:v', 'libx264', '-preset', 'medium', '-crf', '18',
                '-pix_fmt', 'yuv420p', '-c:a', 'copy', '-t', '1', legacy)
            actual = pictures(output, width, height)
            self.assertTrue(np.array_equal(actual, pictures(legacy, width, height)))
            reference = result['video_cue_layers'][0]['layer']
            self.assertEqual(result['video_cue_clocks'][0]['original_layer'], reference)
            self.assertEqual(reference['frame_count'], end-first)
            raw = subprocess.check_output(['ffmpeg', '-v', 'error', '-i', reference['path'],
                '-fps_mode', 'passthrough', '-f', 'rawvideo', '-pix_fmt', 'rgba', 'pipe:1'])
            layer = np.frombuffer(raw, dtype=np.uint8).reshape(-1, height, width, 4)
            background = pictures(base, width, height)[0].astype(float)
            for i in range(end-first):
                opacity = layer[i, :, :, 3:4].astype(float)/255
                composite = layer[i, :, :, :3]*opacity + background*(1-opacity)
                roi = (slice(10, 40), slice(25, 135))
                error = np.mean(np.abs(composite[roi] - actual[first+i][roi]))
                self.assertLess(error, 8, f'output sample {i}')
            self.assertTrue(np.all(layer[:, -1, :, 3] == 0))
            # A layer is a session artifact, not just an unverified path in JSON.
            evidence, empty, outcome = root/'overlays.json', root/'empty.json', root/'result.json'
            write(evidence, result)
            write(empty, {})
            write(outcome, {'technical_status': 'pass'})
            files = {'overlays': fingerprint(evidence), 'result': fingerprint(outcome),
                     'overlay_layer_0': fingerprint(reference['path'])}
            render = {'path': str(root), 'project': fingerprint(empty),
                      'plan': fingerprint(empty), 'files': files}
            Session._verify_render(render)
            payload = bytearray(Path(reference['path']).read_bytes())
            payload[-1] ^= 1
            Path(reference['path']).write_bytes(payload)
            with self.assertRaises(ValueError):
                Session._verify_render(render)

    def test_fractional_clock(self):
        self._case()

    def test_coarse_clock_with_initial_cfr_duplication(self):
        self._case(coarse=True)

    def test_source_alpha(self):
        self._case(alpha=True)
