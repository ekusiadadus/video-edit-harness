"""Synthetic source-frame temporal depth derivation and tamper rejection."""
from pathlib import Path
import json
import shutil
import subprocess
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np

from video_harness.common import read
from video_harness.depth_artifact import (correct_depth, prepare_manual_depth,
                                          stabilize_depth, validate_depth)
from video_harness.depth_temporal import stabilize_one, temporal_config


class FlowRejectionTests(unittest.TestCase):
    def test_nonfinite_flow_does_not_blend_history(self):
        try:
            import cv2
        except ImportError:
            self.skipTest('OpenCV tracking extra required')
        rgb = np.tile(np.arange(32, dtype=np.uint8)[None, :, None], (32, 1, 3)) * 4
        prior = np.full((32, 32), .2, np.float32)
        current = np.full((32, 32), .8, np.float32)
        fake = SimpleNamespace(COLOR_RGB2GRAY=cv2.COLOR_RGB2GRAY, INTER_LINEAR=cv2.INTER_LINEAR,
            INTER_NEAREST=cv2.INTER_NEAREST, BORDER_CONSTANT=cv2.BORDER_CONSTANT,
            cvtColor=cv2.cvtColor, remap=cv2.remap, boxFilter=cv2.boxFilter,
            calcOpticalFlowFarneback=lambda *args, **kwargs: np.full((32,32,2), np.nan, np.float32))
        config = temporal_config(.5, 1., .08, .5, (), 0, 2)
        result, coverage, reset = stabilize_one(rgb, rgb, prior, current, config, fake)
        self.assertEqual(coverage, 0)
        self.assertEqual(reset, 'low_valid_coverage')
        self.assertTrue(np.array_equal(result, current))


@unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'FFmpeg required')
class TemporalDepthTests(unittest.TestCase):
    def setUp(self):
        try:
            import cv2  # noqa: F401 - optional tracking extra gate
        except ImportError:
            self.skipTest('OpenCV tracking extra required')
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root/'source.mp4'
        rng = np.random.default_rng(11)
        background = rng.integers(35, 160, (64, 64, 3), dtype=np.uint8)
        pictures = []
        for frame in range(4):
            image = background.copy()
            image[20:38, 10 + frame*7:27 + frame*7] = 235
            pictures.append(image)
        payload = b''.join(picture.tobytes() for picture in pictures)
        subprocess.run(['ffmpeg', '-v', 'error', '-nostdin', '-n', '-f', 'rawvideo',
            '-pix_fmt', 'rgb24', '-s', '64x64', '-r', '4', '-i', 'pipe:0',
            '-c:v', 'libx264', '-crf', '0', '-pix_fmt', 'yuv444p', str(self.source)],
            input=payload, check=True, capture_output=True)
        fields = {}
        for frame in range(4):
            field = np.full((64, 64), .44 if frame % 2 == 0 else .56, np.float32)
            field[20:38, 10 + frame*7:27 + frame*7] = .92
            path = self.root/f'input-{frame}.npy'
            np.save(path, field, allow_pickle=False)
            fields[frame] = path
        self.parent = prepare_manual_depth(self.source, fields, self.root/'parent',
                                           'automation', 'Synthetic textured moving subject')

    def stabilize(self, name='stabilized', **changes):
        options = {'strength': .5, 'fb_tolerance': 1., 'photometric_tolerance': .08,
                   'min_coverage': .35, 'cut_frames': ()}
        options.update(changes)
        return stabilize_depth(self.parent, self.root/name, 'codex',
                               'Synthetic temporal comparison', **options)

    def test_moving_subject_and_cut_are_source_bound_and_review_required(self):
        manifest = self.stabilize()
        doc = validate_depth(manifest)
        self.assertEqual(doc['version'], 4)
        self.assertEqual(doc['source'], read(self.parent)['source'])
        self.assertEqual(doc['normalization'], read(self.parent)['normalization'])
        self.assertTrue(doc['review_required'])
        self.assertFalse(doc['adopted'])
        observations = doc['temporal']['observations']
        self.assertEqual(observations[0]['reset_reason'], 'interval_start')
        self.assertTrue(all(0 <= row['valid_coverage'] <= 1 for row in observations))
        self.assertEqual(observations[1]['reset_reason'], 'low_valid_coverage')
        self.assertIsNone(observations[2]['reset_reason'])
        original = read(self.parent)
        self.assertTrue(np.array_equal(np.load(doc['rows'][1]['field']['path']),
                                       np.load(original['rows'][1]['field']['path'])))
        # The next row has measured valid coverage: its stable background
        # should move toward row 1, with the moving rectangle kept distinct.
        output = np.load(doc['rows'][2]['field']['path'])
        input_field = np.load(original['rows'][2]['field']['path'])
        background = np.ones((64, 64), dtype=bool)
        background[20:38, 17:41] = False  # union of old and new subject bounds
        closer = np.abs(output[background]-.56) < np.abs(input_field[background]-.56)
        self.assertGreater(int(np.count_nonzero(closer)), 0)
        self.assertAlmostEqual(float(output[28, 38]), float(input_field[28, 38]), places=5)
        cut = self.stabilize('cut', cut_frames=(2,))
        cut_doc = validate_depth(cut)
        self.assertEqual(cut_doc['temporal']['observations'][2]['reset_reason'], 'declared_cut')
        self.assertTrue(np.array_equal(np.load(cut_doc['rows'][2]['field']['path']),
                                       np.load(original['rows'][2]['field']['path'])))
        corrected_input = self.root/'manual-correction.npy'
        np.save(corrected_input, np.full((64,64), .7, np.float32), allow_pickle=False)
        corrected = correct_depth(manifest, {3: corrected_input}, self.root/'after-v4',
                                  'human', 'Synthetic contour correction')
        self.assertEqual(validate_depth(corrected)['version'], 3)
        from_corrected = stabilize_depth(corrected, self.root/'after-v3', 'codex',
                                         'Recheck temporal candidate', strength=.5,
                                         fb_tolerance=1., photometric_tolerance=.08,
                                         min_coverage=.35, cut_frames=())
        self.assertEqual(validate_depth(from_corrected)['version'], 4)

    def test_low_texture_resets_and_invalid_requests_fail_before_output(self):
        flat = self.root/'flat.mp4'
        subprocess.run(['ffmpeg','-v','error','-nostdin','-n','-f','lavfi','-i',
                        'color=black:s=64x64:r=4:d=1','-c:v','libx264',str(flat)],
                       check=True,capture_output=True)
        fields = {}
        for frame in range(4):
            path = self.root/f'flat-{frame}.npy'
            np.save(path, np.full((64,64), .2 + .1*(frame%2), np.float32), allow_pickle=False)
            fields[frame] = path
        parent = prepare_manual_depth(flat, fields, self.root/'flat-parent',
                                      'automation', 'Synthetic flat source')
        result = stabilize_depth(parent, self.root/'flat-out', 'codex', 'Reset low texture',
            strength=.5, fb_tolerance=1., photometric_tolerance=.08,
            min_coverage=.35, cut_frames=())
        self.assertTrue(all(row['reset_reason'] == 'low_valid_coverage'
                            for row in read(result)['temporal']['observations'][1:]))
        for changed in ({'strength': 0}, {'fb_tolerance': 9},
                        {'photometric_tolerance': float('nan')}, {'cut_frames': (0,)},
                        {'cut_frames': (2, 2)}):
            destination = self.root / ('invalid-' + str(len(list(self.root.glob('invalid-*')))))
            with self.subTest(changed=changed), self.assertRaises(ValueError):
                self.stabilize(destination.name, **changed)
            self.assertFalse(destination.exists())

    def test_declared_cut_survives_v4_and_v3_descendants_without_repeating_request(self):
        repeated_source = self.root/'repeated.mp4'
        rng = np.random.default_rng(5)
        image = rng.integers(30, 200, (64,64,3), dtype=np.uint8)
        subprocess.run(['ffmpeg','-v','error','-nostdin','-n','-f','rawvideo',
            '-pix_fmt','rgb24','-s','64x64','-r','4','-i','pipe:0',
            '-c:v','libx264','-crf','0','-pix_fmt','yuv444p',str(repeated_source)],
            input=image.tobytes()*4,check=True,capture_output=True)
        fields = {}
        for frame, value in enumerate((.2,.2,.8,.8)):
            path = self.root/f'cut-field-{frame}.npy'
            np.save(path,np.full((64,64),value,np.float32),allow_pickle=False)
            fields[frame] = path
        parent = prepare_manual_depth(repeated_source,fields,self.root/'cut-parent',
                                      'automation','Synthetic discontinuity')
        first = stabilize_depth(parent,self.root/'cut-first','codex','Explicit scene cut',
            strength=.5,fb_tolerance=1.,photometric_tolerance=.08,min_coverage=.35,
            cut_frames=(2,))
        second = stabilize_depth(first,self.root/'cut-second','codex','Inherited scene cut',
            strength=.5,fb_tolerance=1.,photometric_tolerance=.08,min_coverage=.35)
        self.assertEqual(read(second)['temporal']['config']['cut_frames'],[2])
        self.assertEqual(read(second)['temporal']['observations'][2]['reset_reason'],'declared_cut')
        corrected_input = self.root/'cut-correction.npy'
        np.save(corrected_input,np.full((64,64),.85,np.float32),allow_pickle=False)
        corrected = correct_depth(first,{3:corrected_input},self.root/'cut-corrected',
                                  'human','Synthetic manual correction')
        after_correction = stabilize_depth(corrected,self.root/'cut-after-correction','codex',
            'Inherited cut through correction',strength=.5,fb_tolerance=1.,
            photometric_tolerance=.08,min_coverage=.35)
        doc = validate_depth(after_correction)
        self.assertEqual(doc['temporal']['config']['cut_frames'],[2])
        self.assertEqual(doc['temporal']['observations'][2]['reset_reason'],'declared_cut')
        self.assertTrue(np.array_equal(np.load(doc['rows'][2]['field']['path']),
                                       np.load(read(corrected)['rows'][2]['field']['path'])))

    def test_replay_detects_config_observation_field_parent_and_source_tamper(self):
        manifest = self.stabilize()
        original = read(manifest)
        for key, changed in (
            ('temporal', {**original['temporal'], 'config': {**original['temporal']['config'], 'strength': .8}}),
            ('temporal', {**original['temporal'], 'observations': [
                {**original['temporal']['observations'][0], 'valid_coverage': .5},
                *original['temporal']['observations'][1:]]}),
            ('parent', {**original['parent'], 'sha256': '0'*64}),
        ):
            with self.subTest(key=key), self.assertRaises(ValueError):
                manifest.write_text(json.dumps({**original, key: changed}))
                validate_depth(manifest)
            manifest.write_text(json.dumps(original))
        field = Path(original['rows'][1]['field']['path'])
        original_bytes = field.read_bytes()
        field.write_bytes(b'altered')
        with self.assertRaises(ValueError):
            validate_depth(manifest)
        field.write_bytes(original_bytes)
        source_bytes = self.source.read_bytes()
        self.source.write_bytes(source_bytes + b'altered')
        with self.assertRaises(ValueError):
            validate_depth(manifest)
        self.source.write_bytes(source_bytes)

    def test_replay_rechecks_source_and_parent_field_after_decode(self):
        from video_harness.depth_temporal import replay_temporal
        manifest = self.stabilize()
        parent_row = read(self.parent)['rows'][1]['field']
        for target in (self.source, Path(parent_row['path'])):
            original = target.read_bytes()
            def mutate_after_replay(*args, **kwargs):
                yield from replay_temporal(*args, **kwargs)
                target.write_bytes(original + b'after-decode-tamper')
            try:
                with self.subTest(target=target.name), patch(
                        'video_harness.depth_temporal.replay_temporal', mutate_after_replay):
                    with self.assertRaisesRegex(ValueError, 'changed during replay'):
                        validate_depth(manifest)
            finally:
                target.write_bytes(original)
