from importlib.util import find_spec
import unittest
import numpy as np

from video_harness.tracking_csrt import track_frames_csrt
from tests.test_tracking import _frame
from video_harness.tracking import validate_track
from tests.test_tracking_validation import artifact


@unittest.skipUnless(find_spec('cv2'), 'optional tracking dependency absent')
class CSRTTests(unittest.TestCase):
    def setUp(self):
        import cv2
        if not hasattr(cv2, 'TrackerCSRT_create'):
            self.skipTest('OpenCV contrib tracking not installed')

    def test_translation_then_occlusion_requires_correction(self):
        rows=track_frames_csrt([_frame(30),_frame(33),np.zeros((96,128,3),np.uint8),_frame(39),_frame(42)],
                              [30/128,25/96,70/128,65/96],{4:[42/128,25/96,82/128,65/96]})
        self.assertEqual([r['state'] for r in rows],['manual','tracked','lost','lost','manual'])
        self.assertAlmostEqual(rows[1]['box'][0],33/128,delta=.025)
        doc=artifact()
        doc.update(algorithm='csrt-v1',rows=rows,end_frame_exclusive=5)
        self.assertEqual(validate_track(doc)['lost_frames'],[2,3])

    def test_bad_boxes_and_featureless_input(self):
        with self.assertRaises(ValueError):
            track_frames_csrt([_frame(30)],[0,0,2,1])
        rows=track_frames_csrt([np.zeros((96,128),np.uint8)]*2,[.2,.2,.7,.7])
        self.assertEqual([r['state'] for r in rows],['lost','lost'])


if __name__=='__main__':
    unittest.main()
