"""Video cue phase maps retain the old composited secondary frames."""

from fractions import Fraction
from pathlib import Path
import hashlib
import subprocess
import tempfile
import unittest

import numpy as np

from video_harness.visual import render_overlays
from video_harness.video_cue_phase import capture_overlay_clock


def run(*args):
    subprocess.run(['ffmpeg', '-v', 'error', '-nostdin', '-y', *map(str, args)], check=True)


def registered(path):
    return {'asset_id': 'secondary', 'kind': 'video', 'path': str(path),
            'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}


def pictures(path, width, height):
    raw = subprocess.check_output(['ffmpeg', '-v', 'error', '-i', str(path),
                                   '-map', '0:v:0', '-f', 'rawvideo', '-pix_fmt',
                                   'rgb24', 'pipe:1'])
    return np.frombuffer(raw, dtype=np.uint8).reshape(-1, height, width, 3)


class VideoCuePhaseTests(unittest.TestCase):
    def _case(self, output_fps, source_fps, alpha=False, coarse_clock=False):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            width, height = 160, 90
            source = root / ('secondary.mkv' if alpha else 'secondary.mp4')
            base = root / 'base.mp4'
            count = int(Fraction(source_fps))
            frames = np.empty((count, height, width, 4 if alpha else 3), dtype=np.uint8)
            for frame in range(count):
                frames[frame, :, :, :3] = [(frame*73)%256, (frame*151)%256, (frame*197)%256]
                if alpha:
                    frames[frame, :, :, 3] = [64, 192, 128, 255][frame%4]
            subprocess.run(['ffmpeg', '-v', 'error', '-nostdin', '-y', '-f', 'rawvideo',
                '-pixel_format', 'rgba' if alpha else 'rgb24', '-video_size', f'{width}x{height}',
                '-framerate', str(source_fps), '-i', 'pipe:0', '-frames:v', str(count),
                '-c:v', 'ffv1' if alpha else 'libx264', '-pix_fmt', 'bgra' if alpha else 'yuv420p',
                str(source)], input=frames.tobytes(), check=True, capture_output=True)
            run('-f', 'lavfi', '-i', f'color=c=0x202030:s={width}x{height}:r={output_fps}:d=1',
                '-f', 'lavfi', '-i', 'sine=frequency=440:sample_rate=48000:duration=1',
                '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-c:a', 'aac', base)
            if coarse_clock:
                remux = root/'coarse-base.mkv'
                run('-i', base, '-map', '0', '-c', 'copy', '-avoid_negative_ts', 'disabled', remux)
                base = remux
            original_count = 8
            selected = [0, 0, 2, 2, 4, 5, 7, 7]
            old_first, new_first = 3, 5
            source_start = Fraction(2, 1) / Fraction(source_fps)
            source_end = source_start + Fraction(12, 1) / Fraction(output_fps)
            common = {'id': 'secondary-cue', 'asset_id': 'secondary', 'role': 'video',
                      'source_start': str(source_start), 'source_end': str(source_end),
                      'position': 'top', 'opacity': .6}
            old = {**common, 'output_start': str(Fraction(old_first, 1) / Fraction(output_fps)),
                   'output_end': str(Fraction(old_first + original_count, 1) / Fraction(output_fps))}
            observed_clock = capture_overlay_clock(base, old, Fraction(output_fps))
            mapped = {**common, 'output_start': str(Fraction(new_first, 1) / Fraction(output_fps)),
                      'output_end': str(Fraction(new_first + len(selected), 1) / Fraction(output_fps)),
                      'phase_map': {'version': 1, 'original_start_frame': old_first,
                                    'original_frame_count': original_count,
                                    'original_time_base': observed_clock['original_time_base'],
                                    'original_timestamps': observed_clock['original_timestamps'],
                                    'frames': selected}}
            records = [registered(source)]
            old_output, new_output = root / 'old.mp4', root / 'mapped.mp4'
            render_overlays(base, [old], records, old_output, 1)
            result = render_overlays(base, [mapped], records, new_output, 1)
            def pcm(path):
                return subprocess.check_output(['ffmpeg', '-v', 'error', '-nostdin', '-i', str(path),
                    '-map', '0:a:0', '-f', 's16le', 'pipe:1'])
            self.assertEqual(pcm(old_output), pcm(new_output))
            original = pictures(old_output, width, height)
            retimed = pictures(new_output, width, height)
            # Compare the actual placement ROI, including lossy output encoding.
            roi = (slice(10, 40), slice(25, 135))
            for new_index, old_index in enumerate(selected):
                difference = np.abs(retimed[new_first + new_index][roi].astype(np.int16) -
                                    original[old_first + old_index][roi].astype(np.int16))
                self.assertLess(float(np.mean(difference)), 8)
            provenance = result['video_phase_layers'][0]
            self.assertEqual(provenance['cue_id'], 'secondary-cue')
            self.assertEqual(provenance['source_sha256'], records[0]['sha256'])
            self.assertEqual(provenance['phase_map'], mapped['phase_map'])
            self.assertEqual(provenance['frame_count'], len(selected))
            self.assertEqual(provenance['output_fps'], str(Fraction(output_fps)))
            self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(), records[0]['sha256'])

    def test_native_60_fps_overlay_samples(self):
        self._case('60', '60')

    def test_fractional_project_clock_and_mixed_source_fps(self):
        self._case('30000/1001', '24')

    def test_observed_millisecond_base_clock_is_preserved(self):
        self._case('30000/1001', '24', coarse_clock=True)

    def test_video_source_alpha_is_preserved(self):
        self._case('30', '30', alpha=True)

    def test_stale_asset_and_invalid_map_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source, base = root / 'secondary.mp4', root / 'base.mp4'
            for path in (source, base):
                run('-f', 'lavfi', '-i', 'color=c=red:s=160x90:r=30:d=1',
                    '-c:v', 'libx264', '-pix_fmt', 'yuv420p', path)
            record = registered(source)
            cue = {'id': 'v', 'asset_id': 'secondary', 'role': 'video',
                   'output_start': '0', 'output_end': '2/30',
                   'source_start': '0', 'source_end': '4/30',
                   'phase_map': {'version': 1, 'original_start_frame': 0,
                                 'original_frame_count': 3, 'original_time_base': '1/15360',
                                 'original_timestamps': [0, 512, 1024], 'frames': [0, 2]}}
            for bad in ({'version': 1, 'original_start_frame': 0, 'original_frame_count': 3, 'frames': [0, 3]},
                        {'version': 1, 'original_start_frame': 0, 'original_frame_count': 3, 'frames': [2, 1]},
                        {'version': 1, 'original_start_frame': 0, 'original_frame_count': 3, 'frames': [0, True]}):
                with self.subTest(bad=bad), self.assertRaises(ValueError):
                    render_overlays(base, [{**cue, 'phase_map': bad}], [record],
                                    root / 'invalid.mp4', 1)
            stale = {**record, 'sha256': '0' * 64}
            with self.assertRaisesRegex(ValueError, 'SHA-256 mismatch'):
                render_overlays(base, [cue], [stale], root / 'stale.mp4', 1)


if __name__ == '__main__':
    unittest.main()
