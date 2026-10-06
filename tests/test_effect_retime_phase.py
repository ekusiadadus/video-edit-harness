"""Pure checks for retained pulse phase after a frame-remapped retime."""
from __future__ import annotations

from fractions import Fraction
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

from PIL import Image, ImageChops, ImageStat
from video_harness.video_effects import _filter_graph, _phase_value, render_effects, resolve_effects


RATE = Fraction(10)
MAPPING = {'fps': '10', 'duration': '2', 'sequence': []}
MAPPING_SHA = hashlib.sha256(json.dumps(
    MAPPING, sort_keys=True, ensure_ascii=False, separators=(',', ':'),
    allow_nan=False).encode()).hexdigest()


def event(kind='zoom_pulse', phase=None):
    row = {'id': kind, 'type': kind, 'output_start': '1/2', 'output_end': '13/10',
           'strength': 0.6, 'reason': 'Retained source pulse phase'}
    if kind != 'zoom_pulse':
        row['parameters'] = {'easing': 'smoothstep'}
    if phase is not None:
        row['phase_map'] = phase
    return row


def resolve(row):
    return resolve_effects({'version': 1, 'mapping_sha256': MAPPING_SHA,
                            'events': [row]}, MAPPING)['events'][0]


class EffectRetimePhaseTest(unittest.TestCase):
    def test_held_peak_and_skipped_frames_use_original_zoom_triangle(self):
        phase = {'version': 1, 'original_frame_count': 7,
                 'frames': [0, 2, 3, 3, 3, 5, 6, 6]}
        row = resolve(event(phase=phase))
        self.assertEqual(row['phase_map'], phase)
        self.assertIsNot(row['phase_map']['frames'], phase['frames'])
        expected = [1/7, 5/7, 1, 1, 1, 3/7, 1/7, 1/7]
        for frame, value in enumerate(expected, 5):
            self.assertAlmostEqual(_phase_value(row, frame, RATE), value)
        self.assertEqual(_phase_value(row, 4, RATE), 0)
        self.assertEqual(_phase_value(row, 13, RATE), 0)
        graph, _ = _filter_graph([row], 160, 90, RATE)
        self.assertIn('if(lt(on,5),0,if(gte(on,13),0,', graph)
        self.assertIn('1.000000000000', graph)

    def test_smooth_and_saturation_keep_old_easing_and_frame_runs(self):
        phase = {'version': 1, 'original_frame_count': 7,
                 'frames': [0, 1, 1, 2, 3, 3, 5, 6]}
        for kind, variable in [('smooth_zoom', 'on'), ('saturation_pulse', 'n')]:
            row = resolve(event(kind, phase))
            self.assertAlmostEqual(_phase_value(row, 6, RATE), 7/27)
            self.assertEqual(_phase_value(row, 6, RATE), _phase_value(row, 7, RATE))
            self.assertEqual(_phase_value(row, 9, RATE), _phase_value(row, 10, RATE))
            self.assertEqual(_phase_value(row, 5, RATE), 0)
            self.assertEqual(_phase_value(row, 12, RATE), 0)
            graph, _ = _filter_graph([row], 160, 90, RATE)
            self.assertIn(f'if(lt({variable},5),0,if(gte({variable},13),0,', graph)
        cosine = event('saturation_pulse', phase)
        cosine['parameters']['easing'] = 'cosine'
        self.assertAlmostEqual(_phase_value(resolve(cosine), 6, RATE), .25)

    def test_legacy_events_keep_their_existing_expressions(self):
        zoom_graph, _ = _filter_graph([resolve(event())], 160, 90, RATE)
        self.assertIn('0.600000*max(0,1-abs(on-8.500)/4.000)', zoom_graph)
        sat_graph, _ = _filter_graph([resolve(event('saturation_pulse'))], 160, 90, RATE)
        self.assertIn("hue=s='1-", sat_graph)
        self.assertIn('max(0,min(1,(t-', sat_graph)

    def test_malformed_maps_and_unsupported_types_reject(self):
        valid = {'version': 1, 'original_frame_count': 7,
                 'frames': [0, 1, 2, 3, 3, 4, 5, 6]}
        variants = [None, [], {'version': 1, 'original_frame_count': 7},
                    {**valid, 'extra': 1}, {**valid, 'version': True},
                    {**valid, 'original_frame_count': 0},
                    {**valid, 'original_frame_count': True},
                    {**valid, 'frames': valid['frames'][:-1]},
                    {**valid, 'frames': [0, 1, 2, 3, 4, 5, 6, 7]},
                    {**valid, 'frames': [0, 1, True, 3, 4, 5, 6, 6]},
                    {**valid, 'frames': [0, 2, 1, 3, 4, 5, 6, 6]},
                    {**valid, 'original_frame_count': 4097}]
        for phase in variants:
            with self.subTest(phase=phase), self.assertRaisesRegex(ValueError, 'Phase map'):
                resolve(event(phase=phase) if phase is not None else
                        {**event(), 'phase_map': None})
        unsupported = {'id': 'other', 'type': 'monochrome', 'output_start': '1/2',
                       'output_end': '13/10', 'strength': .6,
                       'reason': 'Unsupported temporal map', 'phase_map': valid}
        with self.assertRaisesRegex(ValueError, 'Phase map is unsupported'):
            resolve(unsupported)

    def test_compressed_smooth_pulses_can_retain_one_or_two_original_values(self):
        for frames in ([2], [0, 4]):
            row = event('smooth_zoom', {'version': 1, 'original_frame_count': 5,
                                        'frames': frames})
            row['output_end'] = str(Fraction(5 + len(frames), 10))
            resolved = resolve(row)
            self.assertEqual([_phase_value(resolved, 5 + i, RATE)
                              for i in range(len(frames))],
                             [1.0] if len(frames) == 1 else [0.0, 0.0])
        legacy = event('smooth_zoom')
        legacy['output_end'] = '7/10'
        with self.assertRaisesRegex(ValueError, 'at least three frames'):
            resolve(legacy)

    def test_ffmpeg_renders_mapped_zoom_and_saturation_at_old_phase(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / 'source.mp4'
            subprocess.run([
                'ffmpeg', '-v', 'error', '-nostdin', '-y', '-f', 'lavfi',
                '-i', 'color=c=red:s=160x90:r=10:d=0.8,drawgrid=w=20:h=20:t=2:c=white',
                '-f', 'lavfi', '-i', 'sine=frequency=440:sample_rate=48000:duration=0.8',
                '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-c:a', 'aac',
                '-shortest', str(source)], check=True, capture_output=True)
            mapping = {'fps': '10', 'duration': '4/5', 'sequence': []}
            mapping_sha = hashlib.sha256(json.dumps(mapping, sort_keys=True,
                ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode()).hexdigest()
            selected = [0, 1, 2, 3, 3, 4, 5, 6]
            for kind in ('zoom_pulse', 'saturation_pulse'):
                original = event(kind)
                original['output_start'] = '0'
                original['output_end'] = '7/10'
                migrated = {**original, 'output_end': '4/5',
                            'phase_map': {'version': 1, 'original_frame_count': 7,
                                          'frames': selected}}
                old_plan = resolve_effects({'version': 1, 'mapping_sha256': mapping_sha,
                                            'events': [original]}, mapping)
                new_plan = resolve_effects({'version': 1, 'mapping_sha256': mapping_sha,
                                            'events': [migrated]}, mapping)
                old_file, new_file = root / f'{kind}-old.mp4', root / f'{kind}-new.mp4'
                render_effects(source, old_plan, old_file)
                render_effects(source, new_plan, new_file)
                old_frames = self._decode_rgb_frames(old_file)
                new_frames = self._decode_rgb_frames(new_file)
                self.assertEqual(len(old_frames), 8)
                self.assertEqual(len(new_frames), 8)
                for new_index, old_index in enumerate(selected):
                    delta = ImageStat.Stat(ImageChops.difference(
                        old_frames[old_index], new_frames[new_index])).mean
                    self.assertLess(max(delta), 5, (kind, new_index, old_index, delta))

    @staticmethod
    def _decode_rgb_frames(path):
        raw = subprocess.check_output(['ffmpeg', '-v', 'error', '-nostdin',
                                       '-i', str(path), '-map', '0:v:0',
                                       '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-'])
        frame_bytes = 160 * 90 * 3
        if len(raw) % frame_bytes:
            raise AssertionError('Decoded frame data was truncated')
        return [Image.frombytes('RGB', (160, 90), raw[i:i + frame_bytes])
                for i in range(0, len(raw), frame_bytes)]


if __name__ == '__main__':
    unittest.main()
