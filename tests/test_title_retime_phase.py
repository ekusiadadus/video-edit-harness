"""A retimed keyword title keeps the source fade and rise frame phases."""
from __future__ import annotations

from fractions import Fraction
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

from PIL import Image, ImageChops, ImageStat

from video_harness.video_effects import (
    _mapped_title_clock, _mapped_title_frame, render_effects, resolve_effects,
)


RATE = Fraction(60)
MAPPING = {'fps': '60', 'duration': '1/2', 'sequence': []}
SHA = hashlib.sha256(json.dumps(MAPPING, sort_keys=True, ensure_ascii=False,
    separators=(',', ':'), allow_nan=False).encode()).hexdigest()
SELECTED = [0, 1, 1, 2, 3, 5, 6, 7, 8, 9, 10, 11, 12, 13, 13, 13, 13, 13]
PHASE = {'version': 1, 'original_frame_count': 14, 'frames': SELECTED}


def title(motion, phase=None):
    row = {'id': 'keyword', 'type': 'keyword_title', 'output_start': '1/10',
           'output_end': '1/3' if phase is None else '2/5',
           'strength': 1, 'reason': 'Retain the original title animation',
           'parameters': {'text': 'R', 'motion': motion, 'background': '#000000',
                          'y': .5, 'font_size_fraction': .12}}
    if phase is not None:
        row['phase_map'] = phase
    return row


def plan(row):
    return resolve_effects({'version': 1, 'mapping_sha256': SHA,
                            'events': [row]}, MAPPING)


def decoded(path):
    raw = subprocess.check_output(['ffmpeg', '-v', 'error', '-nostdin',
                                   '-i', str(path), '-map', '0:v:0',
                                   '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-'])
    frame_bytes = 240 * 720 * 3
    if len(raw) % frame_bytes:
        raise AssertionError('Decoded RGB frame data was truncated')
    return [Image.frombytes('RGB', (240, 720), raw[i:i + frame_bytes])
            for i in range(0, len(raw), frame_bytes)]


class TitleRetimePhaseTest(unittest.TestCase):
    def test_resolves_old_relative_phase_with_nonzero_event_start(self):
        row = plan(title('rise', PHASE))['events'][0]
        self.assertEqual(row['phase_map'], PHASE)
        self.assertIsNot(row['phase_map']['frames'], SELECTED)
        self.assertEqual([_mapped_title_frame(row, i, RATE)
                          for i in (5, 6, 7, 8, 23, 24)],
                         [None, 0, 1, 1, 13, None])
        self.assertIn('if(lt(N,6),0,if(gte(N,24),0,',
                      _mapped_title_clock(row, RATE))

    def test_rational_rate_uses_exact_output_frame_indices(self):
        rate = Fraction(30000, 1001)
        mapping = {'fps': str(rate), 'duration': '1001/2500', 'sequence': []}
        sha = hashlib.sha256(json.dumps(mapping, sort_keys=True, ensure_ascii=False,
            separators=(',', ':'), allow_nan=False).encode()).hexdigest()
        phase = {'version': 1, 'original_frame_count': 6,
                 'frames': [0, 1, 1, 3, 4, 5]}
        row = title('rise', phase)
        row['output_start'], row['output_end'] = '1001/10000', '3003/10000'
        resolved = resolve_effects({'version': 1, 'mapping_sha256': sha,
                                    'events': [row]}, mapping)['events'][0]
        self.assertEqual([_mapped_title_frame(resolved, frame, rate)
                          for frame in range(2, 10)],
                         [None, 0, 1, 1, 3, 4, 5, None])

    def test_malformed_or_unsupported_maps_are_rejected(self):
        invalid = [
            {'version': 1, 'original_frame_count': 14, 'frames': [0]},
            {'version': 1, 'original_frame_count': 14, 'frames': [0] * 17 + [14]},
            {'version': 1, 'original_frame_count': 14, 'frames': [1, 0] + [0] * 16},
            {'version': 1, 'original_frame_count': 4097, 'frames': [0] * 18},
        ]
        for phase in invalid:
            with self.subTest(phase=phase), self.assertRaisesRegex(ValueError, 'Phase map'):
                plan(title('fade', phase))
        unsupported = title('fade', PHASE)
        unsupported['type'] = 'tracked_title'
        with self.assertRaises(ValueError):
            plan(unsupported)

    def test_decoded_fade_and_rise_match_selected_old_frames(self):
        import math
        selections = [SELECTED, [2, 2, 3, 5, 6, 7, 8, 9, 10, 11, 12, 13, 13, 13, 13, 13, 13, 13]]
        for rate in (Fraction(60), Fraction(30000, 1001)):
            with tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                source = root / 'gray.mp4'
                subprocess.run(['ffmpeg', '-v', 'error', '-nostdin', '-y',
                                '-f', 'lavfi', '-i', f'color=c=gray:s=240x720:r={rate}:d={float(30/rate):.9f}',
                                '-f', 'lavfi', '-i',
                                f'sine=frequency=440:sample_rate=48000:duration={float(30/rate):.9f}',
                                '-frames:v', '30', '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-c:a', 'aac',
                                str(source)], check=True, capture_output=True)
                mapping = {'fps': str(rate), 'duration': str(30/rate), 'sequence': []}
                sha = hashlib.sha256(json.dumps(mapping, sort_keys=True, ensure_ascii=False,
                    separators=(',', ':'), allow_nan=False).encode()).hexdigest()
                def local_plan(row):
                    return resolve_effects({'version': 1, 'mapping_sha256': sha, 'events': [row]}, mapping)
                base_frames = decoded(source)
                for motion in ('fade', 'rise'):
                    old = title(motion)
                    old.update(output_start=str(6/rate), output_end=str(20/rate))
                    original = root / f'{motion}-old.mp4'
                    old_report = render_effects(source, local_plan(old), original)
                    old_frames = decoded(original)
                    bounds = old_report['text_assets'][0]['bounds']
                    roi = (max(0, math.floor(bounds[0]*240)), max(0, math.floor(bounds[1]*720)),
                           min(240, math.ceil(bounds[2]*240)), min(720, math.ceil((bounds[3]+.02)*720)))
                    visible = ImageStat.Stat(ImageChops.difference(old_frames[13].crop(roi), base_frames[13].crop(roi))).mean
                    self.assertGreater(max(visible), 10, (rate, motion, 'fixture title must be visible'))
                    for index, selected in enumerate(selections):
                        with self.subTest(rate=rate, motion=motion, selection=index):
                            new = {**old, 'output_end': str(24/rate), 'phase_map': {
                                'version': 1, 'original_frame_count': 14, 'frames': selected}}
                            retimed = root / f'{motion}-new-{index}.mp4'
                            new_report = render_effects(source, local_plan(new), retimed)
                            new_frames = decoded(retimed)
                            self.assertEqual(len(old_frames), 30)
                            self.assertEqual(len(new_frames), 30)
                            self.assertEqual(old_report['frame_count'], new_report['frame_count'])
                            for offset, old_index in enumerate(selected):
                                delta = ImageStat.Stat(ImageChops.difference(
                                    old_frames[6+old_index].crop(roi), new_frames[6+offset].crop(roi))).mean
                                self.assertLess(max(delta), 3, (motion, offset, old_index, delta))
                            if motion == 'rise':
                                old_positions = {row['frame']: row for row in old_report['text_assets'][0]['frame_positions']}
                                new_positions = {row['frame']: row for row in new_report['text_assets'][0]['frame_positions']}
                                for offset, old_index in enumerate(selected):
                                    self.assertEqual(new_positions[6+offset]['y_pixels'], old_positions[6+old_index]['y_pixels'])

    def test_one_original_frame_stays_transparent_when_held(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / 'gray.mp4'
            subprocess.run(['ffmpeg', '-v', 'error', '-nostdin', '-y',
                            '-f', 'lavfi', '-i', 'color=c=gray:s=240x720:r=60:d=0.5',
                            '-f', 'lavfi', '-i',
                            'sine=frequency=440:sample_rate=48000:duration=0.5',
                            '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-c:a', 'aac',
                            '-shortest', str(source)], check=True, capture_output=True)
            old = title('fade')
            old['output_end'] = '7/60'
            new = title('fade', {'version': 1, 'original_frame_count': 1,
                                 'frames': [0, 0, 0]})
            new['output_end'] = '3/20'
            original, retimed = root / 'one-old.mp4', root / 'one-new.mp4'
            render_effects(source, plan(old), original)
            render_effects(source, plan(new), retimed)
            old_frames, new_frames = decoded(original), decoded(retimed)
            for frame in (6, 7, 8):
                delta = ImageStat.Stat(ImageChops.difference(
                    old_frames[6], new_frames[frame])).mean
                self.assertLess(max(delta), 3, (frame, delta))


if __name__ == '__main__':
    unittest.main()
