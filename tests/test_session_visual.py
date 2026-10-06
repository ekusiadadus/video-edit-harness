import tempfile
import unittest
from pathlib import Path

from tests import test_visual_editing as fixture_helpers
from video_harness.common import read, write
from video_harness.delivery import verify_completion
from video_harness.session import Session


class VisualSessionTests(unittest.TestCase):
    def test_environment_audio_obeys_separate_audio_handoff_rights(self):
        from video_harness.production import resolve_production, verify_production
        with tempfile.TemporaryDirectory() as tmp:
            cfg, _ = fixture_helpers.VisualEditingTests().fixture(Path(tmp), source_audio=True)
            production = resolve_production(cfg, {'edit_basis': 'visual', 'duration': 1,
                                                 'sequence': [{'asset_id': 'video1'}]})
            self.assertEqual(production['source_assets'][0]['asset_id'], 'video1')
            verify_production(production)
            with self.assertRaisesRegex(ValueError, 'mixed_audio_handoff'):
                verify_production(production, 'mixed_audio_handoff')

    def test_silent_session_finishes_without_a_transcript_or_listening_claim(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cfg, plan = fixture_helpers.VisualEditingTests().fixture(root, source_audio=False)
            cfg['edit_basis'] = 'visual'
            project = root / 'project.json'
            write(project, cfg)
            session = Session.start(project, root / 'session')
            self.assertEqual(session._load()['phase'], 'needs_visual_plan')
            self.assertIsNone(session.context()['transcript'])
            with self.assertRaisesRegex(ValueError, 'word IDs'):
                session.context(words=True)
            session.propose_visual(plan, 'codex')
            session.approve('codex', 'Synthetic frame selection for integration testing')
            rendered = session.render(preview=False)
            self.assertIsNone(session._load()['transcript'])
            feedback = session.add_feedback(rendered['id'], .1, .2, 'comment',
                                            'Synthetic mapping observation', 'codex')
            self.assertEqual(feedback['source_spans'][0]['asset_id'], 'video1')
            session.dismiss_feedback(feedback['id'], 'codex', 'No change required for synthetic test')
            report = {'render_sha256': rendered['files']['video']['sha256'],
                      'checks': [{'id': name, 'status': 'pass', 'basis': 'synthetic',
                                  'note': 'Generated fixture check, no human approval'}
                                 for name in ('meaning', 'pacing', 'cut_boundaries', 'color', 'asset_rights')]}
            reviewed = session.review(rendered['id'], report, 'codex')
            self.assertTrue(reviewed['passed'])
            delivery = session.package(rendered['id'], target='mp4')
            completion = session.finish(delivery['id'])
            self.assertEqual(completion['status'], 'synthetic_complete')
            self.assertEqual(verify_completion(Path(delivery['artifact']['path']).parent)['status'], 'synthetic_complete')
