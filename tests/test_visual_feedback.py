import unittest

from video_harness.feedback import map_output


class VisualFeedbackTests(unittest.TestCase):
    def fixture(self):
        return {'edit_basis': 'visual', 'duration': 2,
                'sequence': [
                    {'id': 'one', 'asset_id': 'camera-a', 'source_path': '/fixture/a.mov',
                     'source_sha256': 'a' * 64, 'source_start': '1/2', 'source_end': '3/2',
                     'output_start': 0, 'output_end': 1},
                    {'id': 'two', 'asset_id': 'camera-b', 'source_path': '/fixture/b.mov',
                     'source_sha256': 'b' * 64, 'source_start': 5, 'source_end': 6,
                     'output_start': 1, 'output_end': 2}]}

    def test_feedback_keeps_multiple_source_identities(self):
        result = map_output(self.fixture(), .75, 1.25)
        self.assertEqual([r['asset_id'] for r in result['source_spans']], ['camera-a', 'camera-b'])
        self.assertEqual(result['source_spans'][0]['source_start'], 1.25)
        self.assertEqual(result['source_spans'][1]['source_end'], 5.25)
        point = map_output(self.fixture(), 1)
        self.assertEqual(point['boundaries'][0]['left_asset_id'], 'camera-a')
        self.assertEqual(point['source_spans'][0]['asset_id'], 'camera-b')

    def test_noncontiguous_output_is_rejected(self):
        bad = self.fixture()
        bad['sequence'][1]['output_start'] = 1.1
        with self.assertRaises(ValueError):
            map_output(bad, .1, .2)
