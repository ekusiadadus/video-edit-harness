import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from video_harness.direction import resolve_direction
from video_harness.patterns import save_preference
from video_harness.render_cache import digest


class DirectionTests(unittest.TestCase):
    def test_precedence_and_natural_reset(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'preference.json'
            save_preference(path, {'id': 'gentle_vlog', 'music': 'continuous'},
                            explicit=True, actor='codex', reason='Explicit user preference')
            project = {'editing_pattern': {'id': 'gentle_vlog', 'music': 'chapter', 'sfx': 'off'}}
            result = resolve_direction(project, request={'editing_pattern': {'music': 'off'}}, preference=path)
            self.assertEqual(result['pattern_snapshot']['music'], 'off')
            self.assertEqual(result['provenance']['music'], 'current_request')
            self.assertEqual(result['provenance']['sfx'], 'project_setting')
            self.assertEqual(result['provenance']['id'], 'project_setting')
            self.assertEqual(project['editing_pattern']['music'], 'chapter')
            reset = resolve_direction(project, request={'editing_pattern': {'id': 'natural'}}, preference=path)
            self.assertEqual(reset['pattern_snapshot']['music'], 'off')
            self.assertEqual(reset['pattern_snapshot']['sfx'], 'off')
            self.assertEqual(reset['project_changes']['editing_pattern']['id'], 'natural')

    def test_saved_definition_is_not_refreshed(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'preference.json'
            saved = save_preference(path, {'id': 'gentle_vlog'}, explicit=True,
                                    actor='human', reason='Keep this direction')
            with patch('video_harness.patterns._ROOT', Path(temp) / 'catalog_no_longer_present'):
                result = resolve_direction({}, preference=path)
            self.assertEqual(result['pattern_snapshot'], saved['pattern'])
            self.assertEqual(result['provenance']['music'], 'saved_preference')
            self.assertTrue(result['requires_review'])

    def test_missing_explicit_preference_and_conflict(self):
        self.assertEqual(resolve_direction({})['pattern_snapshot']['id'], 'natural')
        with self.assertRaises(ValueError):
            resolve_direction({}, preference={'id': 'gentle_vlog'})
        with self.assertRaises(ValueError):
            resolve_direction({'editing_pattern': {'id': 'natural', 'music': 'continuous'}})
        with self.assertRaises(ValueError):
            resolve_direction({}, request={'editing_pattern': {'typo': 'on'}})
        with self.assertRaises(ValueError):
            resolve_direction({}, request={'editing_pattern': {'id': 'natural', 'sfx': 'accent'}})

    def test_trend_scope_and_expiry(self):
        source = {'version': 1, 'id': 'example_2026', 'source_url': 'https://example.org/observation',
                  'observed_on': '2026-01-01', 'review_after': '2026-12-31',
                  'platform': 'youtube', 'region': 'JP', 'audience': 'adults',
                  'purpose': 'editorial inspiration', 'interpretation': 'Show the process when relevant.'}
        trend = {**source, 'definition_sha256': digest(source)}
        request = {'trend_requested': True, 'platform': 'youtube', 'purpose': 'editorial inspiration'}
        result = resolve_direction({}, request=request, trend=trend, as_of='2026-10-06')
        self.assertEqual([candidate['kind'] for candidate in result['candidates']], ['natural', 'moderated'])
        self.assertEqual(result['project_changes']['editing_pattern']['id'], 'natural')
        self.assertTrue(all(candidate['requires_adoption'] for candidate in result['candidates']))
        for bad_request, bad_trend, as_of in (
            ({**request, 'platform': 'tiktok'}, trend, '2026-10-06'),
            (request, trend, '2027-01-01'),
            (request, {**trend, 'definition_sha256': '0' * 64}, '2026-10-06'),
            (request, {k: v for k, v in source.items() if k != 'platform'}, '2026-10-06'),
        ):
            with self.assertRaises(ValueError):
                resolve_direction({}, request=bad_request, trend=bad_trend, as_of=as_of)
        with self.assertRaises(ValueError):
            resolve_direction({}, trend=trend)


if __name__ == '__main__':
    unittest.main()
