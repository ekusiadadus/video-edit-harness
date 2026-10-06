"""Manual relative-depth revisions retain exact parent and input evidence."""

import io
import json
from contextlib import redirect_stdout
from pathlib import Path
import subprocess
import tempfile
from unittest import TestCase
from unittest.mock import patch

import numpy as np

from video_harness.common import read
from video_harness.depth_artifact import correct_depth, prepare_manual_depth, validate_depth
from video_harness.depth_cli import main as depth_main


class DepthCorrectionTests(TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.source = self.root/'source.mp4'
        subprocess.run(['ffmpeg', '-v', 'error', '-n', '-f', 'lavfi', '-i',
                        'color=blue:s=16x16:r=4:d=1', '-c:v', 'libx264',
                        '-pix_fmt', 'yuv420p', str(self.source)], check=True, capture_output=True)
        self.fields = {}
        for frame in (1, 2):
            path = self.root/f'manual-{frame}.npy'
            np.save(path, np.full((16, 16), frame/4, dtype=np.float32), allow_pickle=False)
            self.fields[frame] = path
        self.manual = prepare_manual_depth(self.source, self.fields, self.root/'original',
                                           'codex', 'Synthetic manual fields')
        self.correction = self.root/'corrected-input.npy'
        np.save(self.correction, np.full((16, 16), .75, dtype=np.float32), allow_pickle=False)

    def test_manual_revision_retains_parent_field_and_requires_review(self):
        output = self.root/'revision'
        manifest = correct_depth(self.manual, {1: self.correction}, output,
                                 'human', 'Observed foreground correction')
        parent = validate_depth(self.manual)
        doc = validate_depth(manifest)
        self.assertEqual(doc['version'], 3)
        self.assertEqual(doc['normalization'], parent['normalization'])
        self.assertEqual(doc['source'], parent['source'])
        self.assertEqual(doc['corrected_frames'], [1])
        self.assertEqual([row['origin'] for row in doc['rows']],
                         ['manual_correction', 'retained_depth'])
        self.assertEqual(doc['rows'][1]['input'], parent['rows'][1]['field'])
        self.assertTrue(np.array_equal(np.load(doc['rows'][0]['field']['path']),
                                       np.load(self.correction)))
        self.assertFalse(doc['adopted'])
        self.assertTrue(doc['review_required'])
        self.assertEqual(np.load(parent['rows'][0]['field']['path'])[0, 0], .25)

    def test_invalid_inputs_fail_before_output_and_tampering_is_detected(self):
        invalid = [({True: self.correction}, 'bool'), ({0: self.correction}, 'outside'),
                   ({3: self.correction}, 'end'), ({}, 'empty')]
        for corrections, label in invalid:
            destination = self.root/label
            with self.subTest(label=label), self.assertRaises(ValueError):
                correct_depth(self.manual, corrections, destination, 'codex', 'Invalid trial')
            self.assertFalse(destination.exists())
        malformed = self.root/'malformed.npy'
        np.save(malformed, np.ones((8, 8), np.float32), allow_pickle=False)
        with self.assertRaises(ValueError):
            correct_depth(self.manual, {1: malformed}, self.root/'bad-field',
                          'codex', 'Wrong canvas')
        self.assertFalse((self.root/'bad-field').exists())
        with self.assertRaises(ValueError):
            correct_depth(self.manual, {1: self.correction}, self.root/'bad-actor',
                          'agent', 'Wrong actor')
        with self.assertRaises(ValueError):
            correct_depth(self.manual, {1: self.correction}, self.root/'bad-reason',
                          'human', ' ')
        manifest = correct_depth(self.manual, {1: self.correction}, self.root/'valid',
                                 'codex', 'Explicit synthetic correction')
        original = read(manifest)
        for key, value in (('source', None), ('normalization', 'per_frame'),
                           ('adopted', True), ('corrected_frames', [2])):
            manifest.write_text(json.dumps({**original, key: value}))
            with self.subTest(key=key), self.assertRaises(ValueError):
                validate_depth(manifest)
        manifest.write_text(json.dumps(original))
        self.correction.write_bytes(b'tampered')
        with self.assertRaises(ValueError):
            validate_depth(manifest)

    def test_second_revision_retains_first_edit_and_parent_tamper_fails(self):
        manifest = correct_depth(self.manual, {1: self.correction}, self.root/'revision',
                                 'codex', 'First explicit correction')
        next_input = self.root/'second-input.npy'
        np.save(next_input, np.full((16, 16), .9, np.float32), allow_pickle=False)
        second = correct_depth(manifest, {2: next_input}, self.root/'second-revision',
                               'human', 'Second explicit correction')
        first_doc, second_doc = validate_depth(manifest), validate_depth(second)
        self.assertEqual(second_doc['parent']['path'], str(manifest.resolve()))
        self.assertEqual(second_doc['corrected_frames'], [2])
        self.assertEqual(second_doc['rows'][0]['origin'], 'retained_depth')
        self.assertEqual(second_doc['rows'][0]['input'], first_doc['rows'][0]['field'])
        self.assertTrue(np.array_equal(np.load(second_doc['rows'][0]['field']['path']),
                                       np.load(self.correction)))
        self.assertFalse(second_doc['adopted'])
        self.assertTrue(second_doc['review_required'])
        self.manual.write_text(self.manual.read_text()+' ')
        with self.assertRaises(ValueError):
            validate_depth(second)

    def test_cli_correct_accepts_relative_field_path_and_seals_result(self):
        request = self.root/'correction-request.json'
        request.write_text(json.dumps({'version': 1, 'fields': [
            {'frame': 1, 'path': self.correction.name}]}))
        output = self.root/'cli-correction'
        with redirect_stdout(io.StringIO()):
            depth_main(['correct', str(self.manual), str(request), '--output', str(output),
                        '--actor', 'human', '--note', 'Observed relative path correction'])
        result = read(output/'result.json')
        doc = validate_depth(output/'fields/depth.json')
        self.assertEqual(result['technical_status'], 'pass')
        self.assertEqual(doc['version'], 3)
        self.assertEqual(doc['rows'][0]['input']['path'], str(self.correction.resolve()))
        self.assertFalse(doc['adopted'])

    def test_lineage_cycle_and_limit_fail_before_parent_recursion(self):
        with self.assertRaisesRegex(ValueError, 'cycle'):
            validate_depth(self.manual, _parents=(self.manual.resolve(),))
        with self.assertRaisesRegex(ValueError, 'exceeds 32'):
            validate_depth(self.manual, _parents=tuple(self.root/f'ancestor-{i}' for i in range(32)))

    def test_inferred_parent_keeps_raw_model_and_shared_scale(self):
        # The existing fake predictor produces a fully validated v2 artifact,
        # including its model binding, execution record, and raw fields.
        from tests.test_depth_inference import DepthInferenceTests
        fixture = DepthInferenceTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        inferred_run = fixture.root/'inferred-for-correction'
        with patch('video_harness.depth_model.LocalDepthModel', fixture.fake()), redirect_stdout(io.StringIO()):
            depth_main(['infer', str(fixture.source), '--model', str(fixture.model_dir),
                        '--first-frame', '1', '--end-frame-exclusive', '3',
                        '--output', str(inferred_run), '--actor', 'automation',
                        '--note', 'Synthetic predictor fixture'])
        parent_manifest = inferred_run/'depth/fields/depth.json'
        parent = validate_depth(parent_manifest)
        correction = fixture.root/'inference-correction.npy'
        np.save(correction, np.full((16, 16), .6, np.float32), allow_pickle=False)
        manifest = correct_depth(parent_manifest, {2: correction}, fixture.root/'revision',
                                 'human', 'Observed synthetic near/far reversal')
        doc = validate_depth(manifest)
        self.assertEqual(doc['normalization'], 'interval_shared_minmax')
        self.assertEqual(doc['parent']['path'], str(parent_manifest.resolve()))
        self.assertEqual(doc['rows'][0]['input'], parent['rows'][0]['field'])
        self.assertEqual(doc['rows'][1]['origin'], 'manual_correction')
        self.assertIn('model', parent['inference'])
        self.assertIn('raw_fields', parent['inference'])
        raw = Path(parent['inference']['raw_fields'][0]['field']['path'])
        raw.write_bytes(raw.read_bytes()+b'changed')
        with self.assertRaises(ValueError):
            validate_depth(manifest)
