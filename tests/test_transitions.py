"""Pixel and real FFmpeg fixture checks; no aesthetic/human review claim."""
from copy import deepcopy
from fractions import Fraction
from pathlib import Path
import subprocess
import tempfile
import unittest

import numpy as np

from video_harness.retime_mapping import conform_source_frames
from video_harness.common import fingerprint
from video_harness.transition_mapping import compile_transitions
from video_harness.transitions import compose_frame, probe_binding, render_transitions, _frames


class TransitionPixelsTests(unittest.TestCase):
    def test_endpoints_and_all_push_directions_have_no_seams(self):
        left = np.arange(48, dtype=np.uint8).reshape(4, 4, 3)
        right = 200 + np.arange(48, dtype=np.uint8).reshape(4, 4, 3)
        for kind, direction in [('dissolve', None)] + [('push', d) for d in ('left', 'right', 'up', 'down')]:
            for p, expected in [('0/1', left), ('1/1', right)]:
                np.testing.assert_array_equal(compose_frame(left, right, kind, p, direction)[0], expected)
        expectations = {
            'left': np.concatenate((left[:, 2:], right[:, :2]), axis=1),
            'right': np.concatenate((right[:, 2:], left[:, :2]), axis=1),
            'up': np.concatenate((left[2:], right[:2]), axis=0),
            'down': np.concatenate((right[2:], left[:2]), axis=0),
        }
        for direction, expected in expectations.items():
            pixels, operator = compose_frame(left, right, 'push', '1/2', direction)
            np.testing.assert_array_equal(pixels, expected)
            self.assertEqual(operator['shift_pixels'], 2)
        pixels, operator = compose_frame(left, right, 'dissolve', '1/2')
        np.testing.assert_array_equal(pixels, left + 100)
        self.assertEqual(operator['operator'], 'encoded_rgb_dissolve')

    def test_pixel_contract(self):
        frame = np.zeros((2, 2, 3), np.uint8)
        for kind, progress, direction in [('push', '1/2', []), ('dissolve', '2', None),
                                          ('dissolve', '1/0', None), ('dissolve', .5, None)]:
            with self.assertRaises(ValueError):
                compose_frame(frame, frame, kind, progress, direction)
        with self.assertRaises(ValueError):
            compose_frame(frame, frame.astype(float), 'dissolve', '0')


class TransitionRenderTests(unittest.TestCase):
    def test_exact_decode_with_distinct_frames_and_repeated_cfr_samples(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            originals = np.zeros((12, 48, 64, 3), np.uint8)
            for i in range(12):
                originals[i] = [i*19, 255-i*17, i*13]
            source = root/'indexed.mkv'
            subprocess.run(['ffmpeg', '-v', 'error', '-f', 'rawvideo', '-pix_fmt', 'rgb24',
                '-s', '64x48', '-r', '24', '-i', '-', '-c:v', 'ffv1', str(source)],
                input=originals.tobytes(), check=True)
            indices = [2, 2, 4, 7, 7]
            with _frames(source, indices, 64, 48, root/'decoder.log') as decoded:
                for index, actual in zip(indices, decoded):
                    np.testing.assert_array_equal(actual, originals[index])

    def test_actual_handles_audio_and_output_frames(self):
        for fps in ('24', '30000/1001'):
            with self.subTest(fps=fps), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                sources = {}
                for i, color in enumerate(('red', 'blue')):
                    path = root/f'{i}.mp4'
                    subprocess.run(['ffmpeg', '-v', 'error', '-threads', '1', '-filter_threads', '1',
                        '-f', 'lavfi', '-i', f'color=c={color}:s=64x48:r={fps}',
                        '-frames:v', '24', '-c:v', 'libx264', '-threads', '1',
                        '-pix_fmt', 'yuv420p', str(path)], check=True)
                    sources[str(i)] = probe_binding(path)
                base = root/'base.mp4'
                subprocess.run(['ffmpeg', '-v', 'error', '-filter_complex_threads', '1',
                    '-i', sources['0']['path'], '-i', sources['1']['path'],
                    '-f', 'lavfi', '-i', 'sine=frequency=440:sample_rate=48000',
                    '-filter_complex', '[0:v]trim=start_frame=6:end_frame=14,setpts=PTS-STARTPTS[l];'
                    '[1:v]trim=start_frame=6:end_frame=14,setpts=PTS-STARTPTS[r];'
                    '[l][r]concat=n=2:v=1:a=0[v]', '-map', '[v]', '-map', '2:a',
                    '-t', str(float(Fraction(16)/Fraction(fps))), '-r', fps, '-c:v', 'libx264',
                    '-threads', '1', '-c:a', 'aac', str(base)], check=True)
                rows = []
                for i in range(2):
                    rows.append({'id': str(i), 'asset_id': str(i), 'source_path': sources[str(i)]['path'],
                        'source_sha256': sources[str(i)]['sha256'], 'source_fps': fps, 'output_fps': fps,
                        'source_first_frame': 6, 'source_end_frame_exclusive': 14,
                        'output_first_frame': i*8, 'output_end_frame_exclusive': (i+1)*8,
                        'source_frame_map': conform_source_frames(6, 14, fps, 8, fps)})
                mapping = {'version': 4, 'edit_basis': 'visual', 'sequence': rows,
                           'fps': fps, 'frame_count': 16, 'duration': float(Fraction(16)/Fraction(fps))}
                for kind in ('dissolve', 'push'):
                    event = {'id': kind, 'left_segment_id': '0', 'before_frames': 2,
                             'after_frames': 2, 'type': kind, 'reason': 'fixture transition'}
                    if kind == 'push':
                        event['direction'] = 'left'
                    compiled = compile_transitions(mapping, {'version': 1, 'events': [event]}, sources,
                                                   'automation', 'technical fixture')
                    target = root/f'{kind}.mp4'
                    evidence = render_transitions(base, mapping, compiled, target,
                                                  input_color='rec709', base_binding=fingerprint(base))
                    self.assertTrue(evidence['full_decode'])
                    self.assertFalse(evidence['adopted'])
                    self.assertEqual([r['output_frame'] for r in evidence['operators']], [6, 7, 8, 9])
                    self.assertIsNotNone(evidence['decoded_pcm_sha256'])
                    data = subprocess.check_output(['ffmpeg', '-v', 'error', '-i', str(target),
                        '-an', '-pix_fmt', 'rgb24', '-f', 'rawvideo', '-'])
                    frames = np.frombuffer(data, np.uint8).reshape(16, 48, 64, 3)
                    self.assertGreater(frames[5, :, :, 0].mean(), 200)
                    self.assertGreater(frames[10, :, :, 2].mean(), 200)
                    self.assertGreater(frames[6, :, :, 0].mean(), 200)
                    self.assertGreater(frames[9, :, :, 2].mean(), 200)
                    if kind == 'dissolve':
                        self.assertGreater(frames[7, :, :, 2].mean(), 60)
                        self.assertGreater(frames[7, :, :, 0].mean(), 120)
                    else:
                        self.assertGreater(frames[7, :, -16:, 2].mean(), 200)
                        self.assertGreater(frames[7, :, :32, 0].mean(), 200)
                    stale = deepcopy(compiled)
                    stale['events'][0]['frames'][0]['left']['source_frame'] += 1
                    with self.assertRaisesRegex(ValueError, 'proposal'):
                        render_transitions(base, mapping, stale, root/f'stale-{kind}.mp4',
                                           input_color='rec709', base_binding=fingerprint(base))
                    stale = deepcopy(compiled)
                    stale['adopted'] = 0  # Python equality alone considers this False.
                    with self.assertRaisesRegex(ValueError, 'proposal'):
                        render_transitions(base, mapping, stale, root/f'bool-{kind}.mp4',
                                           input_color='rec709', base_binding=fingerprint(base))
                    with self.assertRaisesRegex(ValueError, 'Rec.709'):
                        render_transitions(base, mapping, compiled, root/'log.mp4',
                                           input_color='apple_log', base_binding=fingerprint(base))
                    with self.assertRaisesRegex(ValueError, 'base video binding'):
                        render_transitions(base, mapping, compiled, root/'bad-base.mp4',
                                           input_color='rec709', base_binding={})


if __name__ == '__main__':
    unittest.main()
