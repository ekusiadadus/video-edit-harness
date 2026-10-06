import numpy as np
import unittest
from importlib.util import find_spec

from video_harness.tracking import track_frames


def _frame(x, seed=17):
    rng = np.random.default_rng(seed)
    image = np.zeros((96, 128, 3), dtype=np.uint8)
    image[25:65, x:x+40] = rng.integers(30, 240, size=(40, 40, 3), dtype=np.uint8)
    return image


@unittest.skipUnless(find_spec("cv2"), "optional tracking dependency not installed")
class TrackingArrayTests(unittest.TestCase):
    def test_tracks_translated_textured_roi(self):
        rows = track_frames([_frame(x) for x in (30, 33, 36, 39)],
                            [30/128, 25/96, 70/128, 65/96])
        self.assertEqual([row['state'] for row in rows], ['manual', 'tracked', 'tracked', 'tracked'])
        self.assertAlmostEqual(rows[-1]['box'][0], 39/128, delta=.015)
        self.assertGreaterEqual(rows[-1]['quality']['inlier_fraction'], .6)


    def test_occlusion_loses_track_until_manual_correction(self):
        first = _frame(30)
        rows = track_frames([first, _frame(33), np.zeros_like(first), _frame(39), _frame(42)],
                            [30/128, 25/96, 70/128, 65/96],
                            corrections={4: [42/128, 25/96, 82/128, 65/96]})
        self.assertEqual([row['state'] for row in rows], ['manual', 'tracked', 'lost', 'lost', 'manual'])
        self.assertIsNone(rows[2]['box'])


    def test_invalid_or_featureless_input(self):
        with self.assertRaises(ValueError):
            track_frames([_frame(30)], [float('nan'), 0, .5, .5])
        with self.assertRaises(ValueError):
            track_frames([_frame(30)], [0, 0, 1.1, 1])
        with self.assertRaises(ValueError):
            track_frames([_frame(30)], [.2, .2, .5, .5], {1: [0, 0, 1, 1]})
        rows = track_frames([np.zeros((96, 128), dtype=np.uint8)] * 2, [0, 0, 1, 1])
        self.assertEqual([row['state'] for row in rows], ['lost', 'lost'])
