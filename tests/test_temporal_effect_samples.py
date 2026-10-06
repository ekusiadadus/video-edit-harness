"""Actual original-stage temporal pixels; no aesthetic or retime approval."""
from fractions import Fraction
from pathlib import Path
import subprocess
import tempfile
import unittest

import numpy as np
from tests.test_video_effects import fixture, digest, pcm_hash
from video_harness.common import fingerprint
from video_harness.video_effects import render_effects, resolve_effects
from video_harness.overlay_layers import _probe


def pixels(path, width=160, height=90, fmt='rgb24'):
    raw = subprocess.check_output(['ffmpeg', '-v', 'error', '-i', str(path),
                                  '-map', '0:v:0', '-f', 'rawvideo', '-pix_fmt', fmt, '-'])
    return np.frombuffer(raw, np.uint8).reshape(-1, height, width, 4 if fmt == 'rgba' else 3)


class TemporalEffectSampleTests(unittest.TestCase):
    def test_capture_preserves_normal_picture_audio_and_original_window(self):
        for kind in ('motion_trail', 'comparison_wipe'):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as temp:
                root = Path(temp); source = root/'source.mp4'; fixture(source)
                assets = []
                event = {'id': 'temporal', 'type': kind, 'output_start': '1/5',
                         'output_end': '4/5', 'strength': .7, 'reason': 'Synthetic stage sample'}
                if kind == 'comparison_wipe':
                    assets = [{**fingerprint(source), 'asset_id': 'secondary', 'kind': 'video'}]
                    event['parameters'] = {'asset_id': 'secondary', 'source_start': .1}
                mapping = {'fps': '10', 'duration': '6/5', 'sequence': []}
                plan = resolve_effects({'version': 1, 'mapping_sha256': digest(mapping), 'events': [event]}, mapping, assets)
                before = render_effects(source, plan, root/'legacy.mp4', assets, capture_temporal_samples=False)
                after = render_effects(source, plan, root/'captured.mp4', assets)
                self.assertEqual(before['temporal_effect_samples'], [])
                self.assertTrue(np.array_equal(pixels(root/'legacy.mp4'), pixels(root/'captured.mp4')))
                self.assertEqual(pcm_hash(source), pcm_hash(root/'captured.mp4'))
                self.assertEqual(len(after['temporal_effect_samples']), 1)
                row = after['temporal_effect_samples'][0]
                self.assertEqual((row['original_start_frame'], row['original_frame_count']), (2, 6))
                self.assertEqual(row['event_id'], 'temporal')
                self.assertEqual(row['type'], kind)
                self.assertEqual(row['mapping_sha256'], digest(mapping))
                self.assertEqual(row['input_sha256'], fingerprint(source)['sha256'])
                self.assertEqual(row['original_event_sha256'], digest(plan['events'][0]))
                ref = row['original_layer']; actual = fingerprint(ref['path'])
                self.assertEqual(actual, {key: ref[key] for key in ('path', 'bytes', 'sha256')})
                info = _probe(ref['path'])
                self.assertEqual((info['codec'], info['pix_fmt'], info['frame_count'], info['fps']),
                                 ('ffv1', 'bgra', 6, Fraction(10)))
                sample = pixels(ref['path'], fmt='rgba')
                self.assertTrue(np.all(sample[..., 3] == 255))
                # The MP4 adds a lossy encode after this actual stage sample.
                expected = pixels(root/'legacy.mp4')[2:8]
                error = np.abs(sample[..., :3].astype(float)-expected.astype(float)).mean()
                self.assertLess(error, 8)

    def test_overlapping_temporal_events_capture_each_original_stage_in_order(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); source = root/'source.mp4'; fixture(source)
            assets = [{**fingerprint(source), 'asset_id': 'secondary', 'kind': 'video'}]
            trail = {'id': 'trail', 'type': 'motion_trail', 'output_start': '1/5',
                     'output_end': '4/5', 'strength': .7, 'reason': 'First stage'}
            compare = {**trail, 'id': 'compare', 'type': 'comparison_wipe',
                       'reason': 'Second stage', 'parameters': {'asset_id': 'secondary', 'source_start': .1}}
            mapping = {'fps': '10', 'duration': '6/5', 'sequence': []}
            def plan(events):
                return resolve_effects({'version': 1, 'mapping_sha256': digest(mapping),
                                        'events': events}, mapping, assets)
            single = render_effects(source, plan([trail]), root/'trail.mp4', assets)
            both = render_effects(source, plan([compare, trail]), root/'both.mp4', assets)
            samples = both['temporal_effect_samples']
            self.assertEqual([row['event_id'] for row in samples], ['trail', 'compare'])
            self.assertEqual([row['stage_ordinal'] for row in samples], [0, 1])
            first = pixels(samples[0]['original_layer']['path'], fmt='rgba')
            old = pixels(single['temporal_effect_samples'][0]['original_layer']['path'], fmt='rgba')
            self.assertTrue(np.array_equal(first, old))
            second = pixels(samples[1]['original_layer']['path'], fmt='rgba')
            self.assertGreater(np.abs(first.astype(float)-second.astype(float)).mean(), 1)
            self.assertEqual(samples[0]['stage_plan_sha256'], samples[1]['stage_plan_sha256'])
            self.assertNotEqual(samples[0]['stage_plan_sha256'],
                                single['temporal_effect_samples'][0]['stage_plan_sha256'])
            # Distinct new output in the same folder gets its own samples.
            repeated = render_effects(source, plan([compare, trail]), root/'another.mp4', assets)
            self.assertNotEqual(samples[0]['original_layer']['path'],
                                repeated['temporal_effect_samples'][0]['original_layer']['path'])
            self.assertEqual(pcm_hash(source), pcm_hash(root/'both.mp4'))

    def test_capture_flag_is_strict_boolean(self):
        with self.assertRaisesRegex(ValueError, 'boolean'):
            render_effects('/missing', {}, '/unused', capture_temporal_samples=1)
