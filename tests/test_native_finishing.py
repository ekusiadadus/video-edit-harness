import unittest
from pathlib import Path

from tests.test_session import SessionFixture
from video_harness.common import read


class NativeFinishingTests(unittest.TestCase):
    def setUp(self):
        self.fx = SessionFixture()
        self.addCleanup(self.fx.close)
        self.fx.selected()
        self.render = self.fx.render(preview=False)
        self.request = {'platform': 'tiktok', 'usage': 'commercial', 'region': 'JP',
                        'music': {'reference_url': 'https://www.tiktok.com/music/fixture-123',
                                  'start_offset': 0, 'library': 'cml'}, 'effects': []}

    def test_native_proposal_is_bound_to_bytes_and_does_not_post(self):
        before = self.fx.session._load()
        item = self.fx.session.native_finish(self.render['id'], self.request, 'codex', 'Native finishing proposal')
        value = read(item['artifact']['path'])
        self.assertEqual(value['base_video'], self.render['files']['video'])
        self.assertFalse(value['uploaded'])
        self.assertFalse(value['native_music_applied'])
        self.assertFalse(value['cross_platform_rights_verified'])
        self.assertEqual(before['project'], self.fx.session._load()['project'])
        self.assertEqual(before['reviews'], self.fx.session._load()['reviews'])
        Path(item['artifact']['path']).write_text('{}')
        with self.assertRaises(ValueError):
            self.fx.session.resume()

    def test_commercial_library_and_base_bgm_are_separate_gates(self):
        from video_harness.native_finishing import plan_native_finishing
        video = self.render['files']['video']
        mapping = read(self.render['files']['mapping']['path'])
        with self.assertRaisesRegex(ValueError, 'CML'):
            plan_native_finishing(video, mapping, {'cues': []},
                                  {**self.request, 'music': {**self.request['music'], 'library': 'general'}})
        with self.assertRaisesRegex(ValueError, 'baked-in'):
            plan_native_finishing(video, mapping, {'cues': [{'role': 'music'}]}, self.request)
        with self.assertRaisesRegex(ValueError, 'outside'):
            plan_native_finishing(video, mapping, {'cues': []}, {**self.request, 'effects': [
                {'id': 'fixture', 'reference_url': 'https://www.tiktok.com/effect/fixture-123',
                 'start': 0, 'end': 99, 'reason': 'Invalid range fixture'}]})
