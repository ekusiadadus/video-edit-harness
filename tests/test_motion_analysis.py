from fractions import Fraction
from importlib.util import find_spec
import unittest

import numpy as np

from video_harness.motion_analysis import analyze_frames, compare_motion


@unittest.skipUnless(find_spec('cv2'), 'optional OpenCV tracking dependency absent')
class MotionAnalysisTests(unittest.TestCase):
    def setUp(self):
        rng = np.random.default_rng(178)
        self.base = rng.integers(0, 256, (128, 160, 3), dtype=np.uint8)
        self.box = [0.1, 0.1, 0.9, 0.9]

    def moved(self, dx=0, dy=0):
        import cv2
        return cv2.warpAffine(self.base, np.float32([[1, 0, dx], [0, 1, dy]]),
                              (160, 128), borderMode=cv2.BORDER_CONSTANT)

    def analysis(self, dx=0, dy=0):
        return analyze_frames([self.moved(dx * i, dy * i) for i in range(4)],
                              self.box, Fraction(30, 1))

    def test_direction_and_rate(self):
        right = self.analysis(3, 0)
        left = self.analysis(-3, 0)
        up = self.analysis(0, -3)
        self.assertEqual(right['summary']['state'], 'measured')
        self.assertEqual(len(right['pairs']), 3)
        self.assertEqual(right['pairs'][0]['from_frame'], 0)
        self.assertEqual(right['fps'], '30/1')
        self.assertAlmostEqual(right['summary']['dx_per_second'], 90 / 160, delta=.06)
        self.assertAlmostEqual(left['summary']['dx_per_second'], -90 / 160, delta=.06)
        self.assertLess(up['summary']['dy_per_second'], -.6)
        self.assertEqual(compare_motion(right, self.analysis(3, 0))['classification'], 'compatible')
        self.assertEqual(compare_motion(right, left)['classification'], 'incompatible')
        self.assertEqual(compare_motion(right, up)['classification'], 'incompatible')

    def test_static_and_textureless_are_uncertain(self):
        static = self.analysis()
        self.assertEqual(static['summary']['state'], 'uncertain')
        self.assertTrue(all(p['state'] == 'uncertain' for p in static['pairs']))
        flat = analyze_frames([np.zeros((128, 160, 3), np.uint8)] * 4,
                              self.box, (30, 1))
        self.assertEqual(flat['pairs'][0]['reason'], 'insufficient_features')
        self.assertEqual(compare_motion(static, flat)['classification'], 'uncertain')

    def test_opposed_regions_and_discontinuity_are_uncertain(self):
        import cv2
        frames = []
        for i in range(4):
            left = cv2.warpAffine(self.base[:, :80], np.float32([[1, 0, 3*i], [0, 1, 0]]),
                                  (80, 128))
            right = cv2.warpAffine(self.base[:, 80:], np.float32([[1, 0, -3*i], [0, 1, 0]]),
                                   (80, 128))
            frames.append(np.concatenate([left, right], axis=1))
        opposed = analyze_frames(frames, self.box, '30/1')
        self.assertEqual(opposed['summary']['state'], 'uncertain')
        unrelated = np.random.default_rng(999).integers(0, 256, self.base.shape, dtype=np.uint8)
        jump = analyze_frames([self.moved(0), self.moved(3), unrelated,
                               self.moved(9)], self.box, 30)
        self.assertEqual(jump['summary']['state'], 'uncertain')
        self.assertEqual(jump['pairs'][1]['state'], 'uncertain')
        reordered = analyze_frames([self.moved(i) for i in (0, 9, 3, 6)],
                                   self.box, 30)
        self.assertEqual(reordered['summary']['state'], 'uncertain')

    def test_dimensions_speed_and_input_validation(self):
        right = self.analysis(3, 0)
        fast = self.analysis(9, 0)
        self.assertEqual(compare_motion(right, fast)['classification'], 'incompatible')
        smaller = analyze_frames([f[::2, ::2] for f in
                                  [self.moved(i * 3) for i in range(4)]],
                                 self.box, 30)
        self.assertEqual(compare_motion(right, smaller)['reason'], 'different_dimensions')
        bad_cases = [([self.base], self.box, 30),
                     ([self.base, self.base[:, :-1]], self.box, 30),
                     ([self.base, self.base], self.box, 0),
                     ([self.base, self.base], self.box, 'nan'),
                     ([self.base, self.base], self.box, (True, 1)),
                     ([self.base, self.base.astype(np.float32)], self.box, 30),
                     ([self.base, self.base], [float('nan'), 0, .5, .5], 30),
                     ([self.base, self.base[..., 0]], self.box, 30)]
        for frames, box, rate in bad_cases:
            with self.subTest(rate=rate, shape=len(frames)):
                with self.assertRaises(ValueError):
                    analyze_frames(frames, box, rate)
