"""Synthetic identity and timestamp checks; no model or downloaded media needed."""
from fractions import Fraction
from pathlib import Path
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch
import sys
import tempfile
import types

import numpy as np

from video_harness.tracking_pose import _rows_from_detections, track_frames_pose


def pose(cx, cy, width=.16, height=.25, visibility=.99, presence=.99):
    points = [SimpleNamespace(x=0., y=0., visibility=0., presence=0.) for _ in range(33)]
    for index, x, y in ((11, cx-width/2, cy-height/2),
                        (12, cx+width/2, cy-height/2),
                        (23, cx-width/2, cy+height/2),
                        (24, cx+width/2, cy+height/2)):
        points[index] = SimpleNamespace(x=x, y=y, visibility=visibility, presence=presence)
    return points


def rotated_pose(cx, cy, width=.12, height=.30):
    points = pose(cx, cy, width, height)
    for index in (11, 12, 23, 24):
        point = points[index]
        dx, dy = point.x - cx, point.y - cy
        point.x, point.y = cx - dy, cy + dx
    return points


def observed_pose(core):
    """Four torso coordinates from a local 640x360 pose-detection replay."""
    points = pose(.5, .5)
    for index, (x, y) in zip((11, 12, 23, 24), core):
        points[index] = SimpleNamespace(x=x, y=y, visibility=.99, presence=.99)
    return points


class PoseSelectionTests(TestCase):
    def test_observed_turns_continue_but_large_junction_displacement_loses(self):
        # Core points from output/implementation-maya/pose-detections.json,
        # frames 36-37, 78-79, and 120-121; other 29 landmarks are unused.
        observed = {
            36: ((.8115548, .3164855), (.7655283, .3039601), (.8425019, .5569301), (.8060919, .5648764)),
            37: ((.7915214, .3227878), (.7717338, .2806349), (.8269624, .5510617), (.8132517, .5456282)),
            78: ((.8268174, .3471262), (.7665343, .3554125), (.8290830, .6224769), (.7992278, .6315283)),
            79: ((.8062463, .3418187), (.8008683, .3397582), (.8286201, .6179848), (.8261878, .6257643)),
            120: ((.7748059, .4758822), (.7489411, .4888123), (.8082778, .7443246), (.7825723, .7382871)),
            121: ((.8969402, .5312117), (.8556056, .5245017), (.8893578, .7452297), (.8634433, .7342457)),
        }
        for first, seed, expected in ((36, [.78, .35, .82, .50], 'tracked'),
                                      (78, [.78, .43, .82, .55], 'tracked'),
                                      (120, [.76, .54, .80, .65], 'lost')):
            with self.subTest(first=first):
                rows = _rows_from_detections([[observed_pose(observed[first])],
                                              [observed_pose(observed[first + 1])]], seed)
                self.assertEqual(rows[1]['state'], expected)

    def test_in_plane_rotation_preserves_torso_association(self):
        rows = _rows_from_detections([[pose(.3, .5, .12, .30)],
                                      [rotated_pose(.32, .5)]],
                                     [.27, .44, .33, .56])
        self.assertEqual([r['state'] for r in rows], ['manual', 'tracked'])
        self.assertGreater(rows[1]['box'][2] - rows[1]['box'][0],
                           2 * (rows[0]['box'][2] - rows[0]['box'][0]))

    def test_shoulder_foreshortening_with_stable_torso_center_and_length(self):
        # A body turning in depth can halve its projected width over one frame.
        rows = _rows_from_detections([[pose(.805, .489, .0625, .2844)],
                                      [pose(.815, .481, .02775, .2860)]],
                                     [.80, .44, .81, .54])
        self.assertEqual([r['state'] for r in rows], ['manual', 'tracked'])
        self.assertLess(rows[1]['box'][2] - rows[1]['box'][0],
                        .5 * (rows[0]['box'][2] - rows[0]['box'][0]))

    def test_manual_clothing_roi_selects_intersecting_torso_across_reordered_poses(self):
        a = pose(.25, .5)
        b = pose(.75, .5)
        rows = _rows_from_detections([[b, a], [pose(.72, .5), pose(.28, .5)]],
                                     [.22, .45, .29, .55])
        self.assertEqual([r['state'] for r in rows], ['manual', 'tracked'])
        self.assertAlmostEqual(rows[1]['box'][0], .20)
        self.assertEqual(rows[1]['quality']['association_kind'], 'torso_distance')

    def test_ambiguous_crossing_is_sticky_until_manual_correction(self):
        rows = _rows_from_detections([
            [pose(.25, .5), pose(.75, .5)],
            [pose(.23, .5), pose(.27, .5)],
            [pose(.3, .5)],
            [pose(.32, .5)]],
            [.21, .44, .29, .56], corrections={3: [.3, .44, .35, .56]})
        self.assertEqual([r['state'] for r in rows], ['manual', 'lost', 'lost', 'manual'])
        self.assertEqual(rows[1]['quality']['reason'], 'ambiguous_pose')
        self.assertEqual(rows[2]['quality']['reason'], 'awaiting_manual_correction')

    def test_ambiguous_seed_and_unreliable_or_missing_landmarks(self):
        rows = _rows_from_detections([[pose(.46, .5), pose(.54, .5)], [pose(.46, .5)]],
                                     [.45, .44, .55, .56])
        self.assertEqual([r['state'] for r in rows], ['lost', 'lost'])
        self.assertEqual(rows[0]['quality']['reason'], 'ambiguous_manual_box')
        rows = _rows_from_detections([[pose(.25, .5, visibility=.1)], [pose(.25, .5)]],
                                     [.22, .45, .29, .55])
        self.assertEqual([r['state'] for r in rows], ['lost', 'lost'])

    def test_missing_or_invalid_landmark_confidence_is_not_inferred(self):
        for bad in (SimpleNamespace(x=.2, y=.4, visibility=.9),
                    SimpleNamespace(x=.2, y=.4, visibility=1.1, presence=.9),
                    SimpleNamespace(x=.2, y=.4, visibility=True, presence=.9)):
            landmarks = pose(.25, .5)
            landmarks[11] = bad
            with self.subTest(bad=bad):
                rows = _rows_from_detections([[landmarks]], [.22, .45, .29, .55])
                self.assertEqual(rows[0]['state'], 'lost')
                self.assertEqual(rows[0]['quality']['reason'], 'no_pose_in_manual_box')

    def test_large_jump_and_invalid_correction(self):
        rows = _rows_from_detections([[pose(.25, .5)], [pose(.75, .5)], [pose(.26, .5)]],
                                     [.22, .45, .29, .55])
        self.assertEqual([r['state'] for r in rows], ['manual', 'lost', 'lost'])
        with self.assertRaises(ValueError):
            _rows_from_detections([[pose(.25, .5)]], [.2, .4, .3, .6], {1: [.2, .4, .3, .6]})

    def test_video_api_uses_monotonic_rational_timestamps_and_cpu(self):
        seen = []

        class FakeLandmarker:
            def __enter__(self):
                return self

            def __exit__(self, *_):
                pass

            def detect_for_video(self, image, timestamp):
                seen.append(timestamp)
                return SimpleNamespace(pose_landmarks=[pose(.25, .5)])

        class FakeOptions:
            class Delegate:
                CPU = 'cpu'

            def __init__(self, **kwargs):
                self.values = kwargs

        fake_landmarker = SimpleNamespace(create_from_options=lambda options: FakeLandmarker())
        fake_mp = types.SimpleNamespace(
            tasks=SimpleNamespace(BaseOptions=FakeOptions, vision=SimpleNamespace(
                PoseLandmarkerOptions=FakeOptions, RunningMode=SimpleNamespace(VIDEO='video'),
                PoseLandmarker=fake_landmarker)),
            Image=lambda **kwargs: kwargs, ImageFormat=SimpleNamespace(SRGB='srgb'))
        with tempfile.TemporaryDirectory() as directory:
            model = Path(directory) / 'pose.task'
            model.write_bytes(b'local model placeholder')
            frames = [np.zeros((8, 8, 3), dtype=np.uint8) for _ in range(3)]
            with patch.dict(sys.modules, {'mediapipe': fake_mp}):
                rows = track_frames_pose(frames, [.22, .45, .29, .55], model, Fraction(30000, 1001))
        self.assertEqual(seen, [0, 33, 67])
        self.assertEqual([r['state'] for r in rows], ['manual', 'tracked', 'tracked'])

    def test_bad_rate_rejected_before_import(self):
        with self.assertRaisesRegex(ValueError, 'fps'):
            track_frames_pose([], [.2, .4, .3, .6], '/missing', Fraction(1001, 1))
