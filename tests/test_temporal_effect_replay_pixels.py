"""Decoded old-stage samples survive holds and skips on the exact CFR clock."""
from copy import deepcopy
from fractions import Fraction
from pathlib import Path
import subprocess
import tempfile
import unittest
import numpy as np

from tests.test_temporal_effect_samples import pixels
from tests.test_video_effects import digest, pcm_hash
from video_harness.common import fingerprint
from video_harness.video_effects import resolve_effects, render_effects
from video_harness.temporal_effect_phase import new_plan_binding, picture_binding


def encode(path, frames, rate):
    subprocess.run(['ffmpeg', '-v', 'error', '-n', '-f', 'rawvideo', '-pixel_format', 'rgb24',
        '-video_size', '160x90', '-framerate', str(rate), '-i', 'pipe:0', '-f', 'lavfi', '-i',
        f'sine=frequency=440:sample_rate=48000:duration={float(Fraction(len(frames), 1)/rate)}',
        '-c:v', 'libx264', '-crf', '0', '-pix_fmt', 'yuv420p', '-c:a', 'aac', str(path)],
        input=b''.join(frame.tobytes() for frame in frames), check=True, capture_output=True)


class TemporalReplayPixelsTests(unittest.TestCase):
    def test_actual_history_and_secondary_frames_survive_hold_skip_and_compression(self):
        for rate in (Fraction(30), Fraction(30000, 1001)):
            for kind, layout in (('motion_trail', None), ('comparison_wipe', 'wipe'),
                                 ('comparison_wipe', 'side_by_side')):
                with self.subTest(rate=rate, kind=kind, layout=layout), tempfile.TemporaryDirectory() as tmp:
                    root = Path(tmp); source = root/'source.mp4'
                    images = []
                    for i in range(12):
                        frame = np.zeros((90, 160, 3), np.uint8)
                        frame[:, i*10:i*10+10] = (255, 255, 255)
                        images.append(frame)
                    encode(source, images, rate)
                    asset = {**fingerprint(source), 'asset_id': 'secondary', 'kind': 'video'}
                    mapping = {'fps': str(rate), 'duration': str(Fraction(12, 1)/rate), 'sequence': []}
                    row = {'id': 'temporal', 'type': kind, 'output_start': str(Fraction(2, 1)/rate),
                           'output_end': str(Fraction(10, 1)/rate), 'strength': .7, 'reason': 'Synthetic stage replay'}
                    if kind == 'comparison_wipe':
                        row['parameters'] = {'asset_id': 'secondary', 'source_start': float(Fraction(1, 1)/rate), 'layout': layout}
                    original = resolve_effects({'version': 1, 'mapping_sha256': digest(mapping), 'events': [row]}, mapping, [asset])
                    proof = render_effects(source, original, root/'original.mp4', [asset])
                    old_stage = pixels(proof['temporal_effect_samples'][0]['original_layer']['path'])
                    primary = pixels(source)
                    for label, frame_map in [('hold-skip', [0, 1, 2, 2, 2, 4, 6, 8, 10, 11]),
                                             ('one-frame', [0, 1, 7, 10, 11]),
                                             ('whole-window', [2, 4, 6, 8]), ('whole-single', [7])]:
                        current = root/f'{label}.mp4'; encode(current, primary[frame_map], rate)
                        selected = [(j, frame-2) for j, frame in enumerate(frame_map) if 2 <= frame < 10]
                        event = deepcopy(original['events'][0])
                        event['output_start'] = str(Fraction(selected[0][0], 1)/rate)
                        event['output_end'] = str(Fraction(selected[-1][0]+1, 1)/rate)
                        new_mapping = {'fps': str(rate), 'duration': str(Fraction(len(frame_map), 1)/rate), 'sequence': []}
                        picture_sha = picture_binding({})
                        event['content_map'] = {'version': 1, 'original_sample': proof['temporal_effect_samples'][0],
                            'original_event': original['events'][0], 'original_events': original['events'],
                            'frames': [frame for _, frame in selected], 'project_picture_sha256': picture_sha,
                            'new_plan_sha256': new_plan_binding([event], digest(new_mapping))}
                        plan = resolve_effects({'version': 1, 'mapping_sha256': digest(new_mapping), 'events': [event]}, new_mapping, [asset])
                        target = root/f'{label}-replayed.mp4'
                        replay = render_effects(current, plan, target, [asset], project_picture_sha256=picture_sha)
                        actual = pixels(target)
                        self.assertEqual(len(actual), len(frame_map))
                        self.assertEqual(pcm_hash(current), pcm_hash(target))
                        reference = replay['temporal_replay'][0]['remapped_layer']
                        sealed = pixels(reference['path'])
                        expected = old_stage[[frame for _, frame in selected]]
                        self.assertTrue(np.array_equal(sealed, expected))
                        for j, relative in selected:
                            self.assertLess(np.abs(actual[j].astype(float)-old_stage[relative].astype(float)).mean(), 8)
                        untouched = pixels(current)
                        for j in set(range(len(frame_map))) - {j for j, _ in selected}:
                            self.assertLess(np.abs(actual[j].astype(float)-untouched[j].astype(float)).mean(), 4)
                        invalid = deepcopy(event)
                        invalid['content_map']['frames'][0] = True
                        with self.assertRaisesRegex(ValueError, 'frame index'):
                            resolve_effects({'version': 1, 'mapping_sha256': digest(new_mapping), 'events': [invalid]}, new_mapping, [asset])
                        with self.assertRaisesRegex(ValueError, 'picture changed'):
                            render_effects(current, plan, root/f'{label}-stale.mp4', [asset], project_picture_sha256='f'*64)
                        original_layer = Path(event['content_map']['original_sample']['original_layer']['path'])
                        original_bytes = original_layer.read_bytes()
                        try:
                            original_layer.write_bytes(original_bytes+b'tamper')
                            failed = root/f'{label}-tampered.mp4'
                            with self.assertRaisesRegex(ValueError, 'size changed'):
                                render_effects(current, plan, failed, [asset], project_picture_sha256=picture_sha)
                            self.assertFalse(failed.exists())
                        finally:
                            original_layer.write_bytes(original_bytes)
                        damaged = deepcopy(event); damaged['strength'] = .8
                        with self.assertRaisesRegex(ValueError, 'parameters changed'):
                            resolve_effects({'version': 1, 'mapping_sha256': digest(new_mapping), 'events': [damaged]}, new_mapping, [asset])

    def test_collapsed_starts_keep_original_comparison_stage_order(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); source = root/'source.mp4'; rate = Fraction(30000, 1001)
            images = []
            for i in range(12):
                frame = np.zeros((90, 160, 3), np.uint8)
                frame[:, i*10:i*10+10] = 255
                images.append(frame)
            encode(source, images, rate)
            asset = {**fingerprint(source), 'asset_id': 'secondary', 'kind': 'video'}
            mapping = {'fps': str(rate), 'duration': str(Fraction(12, 1)/rate), 'sequence': []}
            first = {'id': 'z-first', 'type': 'comparison_wipe', 'output_start': str(Fraction(2, 1)/rate),
                     'output_end': str(Fraction(10, 1)/rate), 'strength': .7, 'reason': 'Original first stage',
                     'parameters': {'asset_id': 'secondary', 'source_start': float(Fraction(1, 1)/rate)}}
            second = {**first, 'id': 'a-second', 'output_start': str(Fraction(3, 1)/rate),
                      'strength': .4, 'reason': 'Original second stage',
                      'parameters': {'asset_id': 'secondary', 'source_start': float(Fraction(2, 1)/rate),
                                     'layout': 'side_by_side'}}
            old = resolve_effects({'version': 1, 'mapping_sha256': digest(mapping), 'events': [second, first]}, mapping, [asset])
            proof = render_effects(source, old, root/'original.mp4', [asset])
            frame_map = [0, 1, 3, 3, 5, 7, 10, 11]
            current = root/'selected.mp4'; encode(current, pixels(source)[frame_map], rate)
            new_mapping = {'fps': str(rate), 'duration': str(Fraction(8, 1)/rate), 'sequence': []}
            current_events = []
            for old_event, sample in zip(old['events'], proof['temporal_effect_samples']):
                event = deepcopy(old_event); event['output_start'] = str(Fraction(2, 1)/rate)
                event['output_end'] = str(Fraction(6, 1)/rate)
                begin = sample['original_start_frame']
                event['content_map'] = {'version': 1, 'original_sample': sample,
                    'original_event': old_event, 'original_events': old['events'],
                    'frames': [frame-begin for frame in frame_map[2:6]],
                    'new_plan_sha256': '0'*64, 'project_picture_sha256': picture_binding({})}
                current_events.append(event)
            current_events.sort(key=lambda row: (Fraction(row['output_start']), row['type'], row['id']))
            self.assertEqual([row['id'] for row in current_events], ['a-second', 'z-first'])
            binding = new_plan_binding(current_events, digest(new_mapping))
            for event in current_events:
                event['content_map']['new_plan_sha256'] = binding
            plan = resolve_effects({'version': 1, 'mapping_sha256': digest(new_mapping), 'events': current_events}, new_mapping, [asset])
            target = root/'replayed.mp4'
            result = render_effects(current, plan, target, [asset], project_picture_sha256=picture_binding({}))
            self.assertEqual([row['event_id'] for row in result['temporal_replay']], ['z-first', 'a-second'])
            original = pixels(proof['temporal_effect_samples'][1]['original_layer']['path'])
            expected = original[[frame-3 for frame in frame_map[2:6]]]
            self.assertLess(np.abs(pixels(target)[2:6].astype(float)-expected.astype(float)).mean(), 8)
            self.assertEqual(pcm_hash(current), pcm_hash(target))
