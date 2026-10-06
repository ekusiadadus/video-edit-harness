"""Synthetic MediaPipe contract and identity tests; no model download or media."""
from fractions import Fraction
from pathlib import Path
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch
import sys
import tempfile

import numpy as np

from video_harness.semantic_mask import segment_frames_pose


def pose(cx, visibility=.99, presence=.99):
    points = [SimpleNamespace(x=0., y=0., visibility=0., presence=0.) for _ in range(33)]
    for index, x, y in ((11, cx-.08, .375), (12, cx+.08, .375),
                        (23, cx-.08, .625), (24, cx+.08, .625)):
        points[index] = SimpleNamespace(x=x, y=y, visibility=visibility, presence=presence)
    return points


class Mask:
    def __init__(self, value, shape=(8, 8)):
        self.value = np.full(shape, value, dtype=np.float32) if np.isscalar(value) else value

    def numpy_view(self):
        return self.value


class FakeMP:
    def __init__(self, results):
        self.results = iter(results)
        self.timestamps = []
        self.options = None

        owner = self

        class Options:
            class Delegate:
                CPU = 'cpu'

            def __init__(self, **kwargs):
                self.values = kwargs

        class Landmarker:
            def __enter__(self):
                return self

            def __exit__(self, *_):
                pass

            def detect_for_video(self, image, timestamp):
                owner.timestamps.append(timestamp)
                return next(owner.results)

        def create(options):
            owner.options = options.values
            return Landmarker()

        vision = SimpleNamespace(PoseLandmarkerOptions=Options,
                                 RunningMode=SimpleNamespace(VIDEO='video'),
                                 PoseLandmarker=SimpleNamespace(create_from_options=create))
        self.tasks = SimpleNamespace(BaseOptions=Options, vision=vision)
        self.Image = lambda **kwargs: kwargs
        self.ImageFormat = SimpleNamespace(SRGB='srgb')


def result(poses, masks):
    return SimpleNamespace(pose_landmarks=poses, segmentation_masks=masks)


class SemanticMaskTests(TestCase):
    def run_masks(self, results, **kwargs):
        fake = FakeMP(results)
        with tempfile.TemporaryDirectory() as directory:
            model = Path(directory) / 'pose.task'
            model.write_bytes(b'local model placeholder')
            with patch.dict(sys.modules, {'mediapipe': fake}):
                rows = segment_frames_pose(
                    [np.zeros((8, 8, 3), dtype=np.uint8) for _ in results],
                    [.22, .44, .29, .56], model, Fraction(30000, 1001), **kwargs)
        return rows, fake

    def test_reordered_people_retain_original_mask_index(self):
        rows, fake = self.run_masks([
            result([pose(.75), pose(.25)], [Mask(.1), Mask(.9)]),
            result([pose(.27), pose(.73)], [Mask(.8), Mask(.2)])])
        self.assertEqual([row['state'] for row in rows], ['manual', 'tracked'])
        self.assertEqual([row['quality']['pose_index'] for row in rows], [1, 0])
        self.assertTrue(all(np.all(row['mask'] == 1) for row in rows))
        self.assertEqual(fake.timestamps, [0, 33])
        self.assertTrue(fake.options['output_segmentation_masks'])
        self.assertEqual(fake.options['num_poses'], 6)
        self.assertEqual(fake.options['base_options'].values['delegate'], 'cpu')

    def test_unreliable_pose_does_not_shift_mask_index(self):
        rows, _ = self.run_masks([
            result([pose(.25, visibility=.1), pose(.25)], [Mask(.1), Mask(.9)])])
        self.assertEqual(rows[0]['quality']['pose_index'], 1)
        self.assertTrue(np.all(rows[0]['mask'] == 1))

    def test_ambiguous_loss_sticks_until_manual_correction(self):
        rows, _ = self.run_masks([
            result([pose(.25)], [Mask(.9)]),
            result([pose(.23), pose(.27)], [Mask(.9), Mask(.9)]),
            result([pose(.25)], [Mask(.9)]),
            result([pose(.32)], [Mask(.9)])],
            corrections={3: [.29, .44, .35, .56]})
        self.assertEqual([row['state'] for row in rows], ['manual', 'lost', 'lost', 'manual'])
        self.assertEqual([row['quality'].get('reason') for row in rows[1:3]],
                         ['ambiguous_pose', 'awaiting_manual_correction'])
        self.assertIsNone(rows[1]['mask'])
        self.assertIsNone(rows[2]['mask'])

    def test_invalid_and_mismatched_probability_tensors_lose_identity(self):
        invalid = [Mask(np.full((8, 8), np.nan, dtype=np.float32)),
                   Mask(np.full((8, 8), 1.2, dtype=np.float32)),
                   Mask(np.full((8, 8), -.1, dtype=np.float32)),
                   Mask(.9, (7, 8)), Mask(.9, (8, 8, 2)),
                   Mask(np.full((8, 8), 1, dtype=np.uint8))]
        for mask in invalid:
            with self.subTest(shape=mask.value.shape, dtype=mask.value.dtype):
                rows, _ = self.run_masks([result([pose(.25)], [mask]),
                                          result([pose(.25)], [Mask(.9)])])
                self.assertEqual([row['state'] for row in rows], ['lost', 'lost'])
                self.assertEqual(rows[0]['quality']['reason'], 'invalid_segmentation_mask')
        rows, _ = self.run_masks([result([pose(.25)], [])])
        self.assertEqual(rows[0]['quality']['reason'], 'missing_or_mismatched_segmentation_masks')
        self.assertIsNone(rows[0]['mask'])
        rows, _ = self.run_masks([result([pose(.25)], None)])
        self.assertEqual(rows[0]['quality']['reason'], 'missing_or_mismatched_segmentation_masks')

    def test_singleton_channel_and_threshold(self):
        rows, _ = self.run_masks([result([pose(.25)], [Mask(.6, (8, 8, 1))])], threshold=.7)
        self.assertEqual(rows[0]['mask'].shape, (8, 8))
        self.assertEqual(rows[0]['mask'].dtype, np.uint8)
        self.assertFalse(rows[0]['mask'].any())

    def test_input_guards(self):
        for threshold in (0, 1, float('nan'), True, '0.5'):
            with self.subTest(threshold=threshold), self.assertRaisesRegex(ValueError, 'threshold'):
                segment_frames_pose([], [.2, .4, .3, .6], '/missing', 30, threshold=threshold)
        for fps in (0, 1001, float('inf')):
            with self.subTest(fps=fps), self.assertRaisesRegex(ValueError, 'fps'):
                segment_frames_pose([], [.2, .4, .3, .6], '/missing', fps)
        with self.assertRaisesRegex(ValueError, 'num_poses'):
            segment_frames_pose([], [.2, .4, .3, .6], '/missing', 30, num_poses=0)
        with self.assertRaisesRegex(ValueError, 'corrections'):
            segment_frames_pose([], [.2, .4, .3, .6], '/missing', 30,
                                corrections={-1: [.2, .4, .3, .6]})
        with self.assertRaisesRegex(ValueError, 'model_path'):
            segment_frames_pose([], [.2, .4, .3, .6], '/missing', 30)
        with self.assertRaisesRegex(ValueError, 'dimensions'):
            fake = FakeMP([result([pose(.25)], [Mask(.9)])])
            with tempfile.TemporaryDirectory() as directory:
                model = Path(directory) / 'pose.task'
                model.write_bytes(b'model')
                with patch.dict(sys.modules, {'mediapipe': fake}):
                    segment_frames_pose([np.zeros((8, 8, 3), np.uint8),
                                         np.zeros((9, 8, 3), np.uint8)],
                                        [.22, .44, .29, .56], model, 30)
