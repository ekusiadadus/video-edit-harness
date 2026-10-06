import unittest

from tests.test_session import SessionFixture
from video_harness.common import read


class SessionCandidateTests(unittest.TestCase):
    def test_effect_revision_uses_rendered_candidate_and_does_not_adopt(self):
        from unittest.mock import patch
        original = self.session._load()['project']
        base = self.session.create_candidate({'audio': {'target_lufs': -18},
                'video_effects': {'preset': 'subtle', 'intensity': 'low'}}, 'codex', 'Base direction')
        render = self.fixture.render(candidate_id=base['id'])
        revised = {'version': 1, 'mapping_sha256': 'a'*64, 'events': []}
        with patch('video_harness.video_effects.revise_effects', return_value=revised) as revise:
            candidate = self.session.propose_effects(render['id'], [{'action': 'remove', 'id': 'one'}],
                                                     'codex', 'Remove local accent')
        self.assertEqual(revise.call_args.args[0], {'preset': 'subtle', 'intensity': 'low'})
        cfg = read(candidate['project']['path'])
        self.assertEqual(cfg['audio'], {'target_lufs': -18})
        self.assertEqual(cfg['video_effects'], revised)
        self.assertEqual(self.session._load()['project'], original)
        self.assertEqual(self.session._load()['reviews'], [])

    def setUp(self):
        self.fixture = SessionFixture()
        self.addCleanup(self.fixture.close)
        self.session = self.fixture.session
        self.fixture.selected()

    def test_compare_does_not_change_current_inputs_and_adopt_is_exact(self):
        initial = self.session._load()
        natural = self.session.create_candidate({'editing_pattern': {'id': 'natural'}}, 'codex', 'Compare without additions')
        gentle = self.session.create_candidate({'editing_pattern': {'id': 'gentle_vlog'}}, 'codex', 'Compare low-density music')
        after_creation = self.session._load()
        self.assertEqual(initial['project'], after_creation['project'])
        self.assertEqual(initial['plan'], after_creation['plan'])
        first = self.fixture.render(preview=True, candidate_id=natural['id'])
        second = self.fixture.render(preview=True, candidate_id=gentle['id'])
        comparison = self.session.compare_candidates([first['id'], second['id']])
        evidence = read(comparison['evidence']['path'])
        self.assertEqual(evidence['conditions']['source_sha256'], initial['source']['sha256'])
        self.assertEqual([row['video_sha256'] for row in evidence['candidates']],
                         [first['files']['video']['sha256'], second['files']['video']['sha256']])
        from pathlib import Path
        self.assertIn('比較', Path(comparison['artifact']['path']).read_text())
        self.assertEqual(initial['project'], self.session._load()['project'])
        self.session.adopt_candidate(gentle['id'], 'codex', 'Selected for next full render; no human approval claimed')
        adopted = self.session._load()
        self.assertEqual(adopted['project'], gentle['project'])
        self.assertEqual(adopted['plan'], gentle['plan'])
        self.assertEqual(adopted['reviews'], [])
        self.assertEqual(adopted['phase'], 'needs_render')
        self.session.adopt_candidate(natural['id'], 'codex', 'Restore natural comparison')
        self.assertEqual(self.session._load()['project'], natural['project'])
        self.assertEqual(read(gentle['project']['path'])['editing_pattern']['id'], 'gentle_vlog')

    def test_adoption_requires_render_and_candidate_cannot_change_source(self):
        candidate = self.session.create_candidate({}, 'codex', 'Keep old project snapshot')
        with self.assertRaisesRegex(ValueError, 'Render'):
            self.session.adopt_candidate(candidate['id'], 'codex', 'Premature')
        with self.assertRaisesRegex(ValueError, 'settings'):
            self.session.create_candidate({'source': '/another.mov'}, 'codex', 'Disallowed')

    def test_candidate_references_remain_sealed(self):
        candidate = self.session.create_candidate({}, 'codex', 'Snapshot')
        from pathlib import Path
        Path(candidate['project']['path']).write_text('{}')
        with self.assertRaises(ValueError):
            self.session.render(candidate_id=candidate['id'])

    def test_natural_reset_clears_previous_effect_request(self):
        self.session.update_project({'editing_pattern': {'id': 'playful_short'},
                                     'video_effects': {'preset': 'pop_dance', 'intensity': 'medium'}},
                                    'codex', 'Compare requested effects without claiming human approval')
        effect_snapshot = self.session._load()['project']
        natural = self.session.create_candidate({'editing_pattern': {'id': 'natural'}},
                                                'codex', 'Compare original without added effects')
        self.assertNotIn('video_effects', read(natural['project']['path']))
        self.assertIn('video_effects', read(effect_snapshot['path']))
        self.session.update_project({'editing_pattern': {'id': 'natural'}},
                                    'codex', 'Restore no-addition editing direction')
        self.assertNotIn('video_effects', read(self.session._load()['project']['path']))

    def test_comparison_requires_same_base_audio_and_natural_baseline(self):
        natural = self.session.create_candidate({'editing_pattern': {'id': 'natural'}}, 'codex', 'Baseline')
        loud = self.session.create_candidate({'editing_pattern': {'id': 'gentle_vlog'},
                                             'audio': {'target_lufs': -10}}, 'codex', 'Different base gain')
        first = self.fixture.render(preview=True, candidate_id=natural['id'])
        second = self.fixture.render(preview=True, candidate_id=loud['id'])
        with self.assertRaisesRegex(ValueError, 'base audio'):
            self.session.compare_candidates([first['id'], second['id']])
        gentle = self.session.create_candidate({'editing_pattern': {'id': 'gentle_vlog'}}, 'codex', 'Gentle')
        clear = self.session.create_candidate({'editing_pattern': {'id': 'clear_explainer'}}, 'codex', 'Clear')
        third = self.fixture.render(preview=True, candidate_id=gentle['id'])
        fourth = self.fixture.render(preview=True, candidate_id=clear['id'])
        with self.assertRaisesRegex(ValueError, 'natural'):
            self.session.compare_candidates([third['id'], fourth['id']])

    def test_direction_candidates_preserve_saved_snapshot_without_adoption(self):
        from pathlib import Path
        from unittest.mock import patch
        from video_harness.patterns import save_preference
        initial = self.session._load()['project']
        pref = self.fixture.root / 'preference.json'
        saved = save_preference(pref, {'id': 'gentle_vlog', 'music': 'continuous'},
                                explicit=True, actor='codex', reason='Explicit fixture preference')
        # Session integration must preserve the old definition rather than
        # refresh it during candidate creation.
        with patch('video_harness.patterns._ROOT', Path('/missing-fixture-catalog')):
            result = self.session.propose_direction({}, 'codex', 'Use saved fixture preference', preference=pref)
        candidate = result['candidates'][0]
        self.assertEqual(read(candidate['project']['path'])['_editing_pattern_snapshot'], saved['pattern'])
        self.assertTrue(result['requires_adoption'])
        self.assertEqual(self.session._load()['project'], initial)
        self.assertEqual(read(candidate['direction']['path'])['provenance']['id'], 'saved_preference')
