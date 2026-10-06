import tempfile
import unittest
from pathlib import Path

from video_harness.patterns import resolve_pattern, resolve_asset_policy, reset_to_natural, save_preference, reuse_preference


class PatternTests(unittest.TestCase):
    def test_natural_defaults_and_independence(self):
        plain = resolve_pattern({'style': 'soft_film', 'use_case': 'indoor_talk'})
        self.assertEqual(plain['id'], 'natural')
        self.assertTrue(all(plain[k] == 'off' for k in ('music', 'sfx', 'visual_assets', 'beat_sync')))
        self.assertEqual(resolve_pattern({'style': 'warm_documentary', 'editing_pattern': {'id': 'gentle_vlog'}})['music'], 'intro_outro')
        self.assertEqual(resolve_pattern({'editing_pattern': {'id': 'gentle_vlog', 'music': 'off'}})['music'], 'off')
        old = {'editing_pattern': {'id': 'gentle_vlog', 'music': 'continuous'},
               '_editing_pattern_snapshot': {'id': 'gentle_vlog', 'music': 'continuous'},
               'style': 'soft_film'}
        reset = reset_to_natural(old)
        self.assertEqual(resolve_pattern(reset)['music'], 'off')
        self.assertNotIn('_editing_pattern_snapshot', reset)
        self.assertIn('_editing_pattern_snapshot', old)
        self.assertEqual(old['editing_pattern']['music'], 'continuous')
        self.assertEqual(reset['style'], 'soft_film')

    def test_six_patterns_and_strict_new_schema(self):
        for name in ('natural', 'gentle_vlog', 'clear_explainer', 'cinematic_story', 'beat_montage', 'playful_short'):
            self.assertEqual(len(resolve_pattern({'editing_pattern': {'id': name}})['definition_sha256']), 64)
        for setting in ({'id': 'natural', 'music': 'continuous'}, {'id': 'natural', 'typo': True}):
            with self.assertRaises(ValueError):
                resolve_pattern({'editing_pattern': setting})
        with self.assertRaises(ValueError):
            resolve_asset_policy({'asset_policy': {'network': 'maybe'}})
        with self.assertRaises(ValueError):
            resolve_asset_policy({'asset_policy': {'destinations': ['youtube'], 'unexpected': 1}})
        base = {'destinations': ['youtube']}
        self.assertEqual(resolve_asset_policy({'asset_policy': base})['content_id_check'], 'required')
        self.assertEqual(resolve_asset_policy({'asset_policy': {**base,
            'content_id_check': 'pending_local_review'}})['content_id_check'], 'pending_local_review')
        for invalid in ('pending', None, []):
            with self.subTest(invalid=invalid):
                with self.assertRaisesRegex(ValueError, 'Content ID check policy'):
                    resolve_asset_policy({'asset_policy': {**base, 'content_id_check': invalid}})

    def test_explicit_preference_records_actual_actor(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'preference.json'
            with self.assertRaises(ValueError):
                save_preference(path, {'id': 'gentle_vlog'}, explicit=False, actor='codex', reason='guess')
            saved = save_preference(path, {'id': 'gentle_vlog'}, explicit=True, actor='codex', reason='User explicitly requested this default')
            self.assertEqual(saved['actor'], 'codex')
            self.assertEqual(reuse_preference(path), saved['pattern'])
            with self.assertRaises(FileExistsError):
                save_preference(path, {'id': 'natural'}, explicit=True, actor='human', reason='different')


if __name__ == '__main__':
    unittest.main()
