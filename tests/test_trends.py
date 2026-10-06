import unittest
import tempfile
from pathlib import Path

from video_harness.trends import load_trend_profile, import_trend_profile


class TrendTests(unittest.TestCase):
    def test_snapshot_is_dated_and_not_refreshed(self):
        early = load_trend_profile('process_story_2026', as_of='2026-10-06')
        late = load_trend_profile('process_story_2026', as_of='2027-02-01')
        self.assertFalse(early['stale'])
        self.assertTrue(late['stale'])
        self.assertEqual(early['definition_sha256'], late['definition_sha256'])

    def test_current_youtube_source_is_bounded(self):
        item = load_trend_profile('youtube_communities_2026', as_of='2026-10-06')
        self.assertFalse(item['stale'])
        self.assertIn('2026', item['id'])
        self.assertIn('not establish', item['interpretation'])

    def test_import_is_immutable_and_readable(self):
        sample = {'version': 1, 'id': 'synthetic_2026', 'source_url': 'https://example.org/research',
                  'observed_on': '2026-01-01', 'region': 'unknown', 'audience': 'synthetic',
                  'purpose': 'test', 'interpretation': 'No performance claim.', 'review_after': '2026-12-31'}
        with tempfile.TemporaryDirectory() as temp:
            saved = import_trend_profile(temp, sample)
            self.assertEqual(saved['definition_sha256'], load_trend_profile('synthetic_2026', root=temp)['definition_sha256'])
            with self.assertRaises(FileExistsError):
                import_trend_profile(temp, sample)
            with self.assertRaises(ValueError):
                import_trend_profile(temp, {**sample, 'id': 'new_bad', 'source_url': 'http://example.org'})


if __name__ == '__main__':
    unittest.main()
