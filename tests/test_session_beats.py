import tempfile
import unittest
from fractions import Fraction
from pathlib import Path

from tests import test_visual_editing as visuals
from tests import test_production as music
from video_harness.common import read, write
from video_harness.beats import analyze_beats
from video_harness.session import Session
from video_harness.workflow_cli import parser


class SessionBeatTests(unittest.TestCase):
    def test_source_bound_proposal_requires_selection_and_replans_cues(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cfg, plan = visuals.VisualEditingTests().fixture(root, source_audio=False)
            cfg['assets'] += music.ProductionTests().fixture(root)['assets']
            cfg.update(edit_basis='visual', editing_pattern={'id': 'beat_montage'})
            project = root / 'project.json'
            write(project, cfg)
            session = Session.start(project, root / 'session')
            session.propose_visual(plan)
            session.approve('codex', 'Synthetic source frames inspected')
            rendered = session.render(preview=False)
            beat_map = analyze_beats(cfg['assets'][1]['path'], manual_beats=[.3, .6])
            spec = {'asset_id': 'original', 'beat_map': beat_map,
                    'max_shift': '.15', 'min_hold': '.2', 'allowed_intervals': [[.1, .7]]}
            before = session._load()
            bad = {**spec, 'beat_map': {**beat_map, 'source_sha256': '0' * 64}}
            with self.assertRaisesRegex(ValueError, 'music SHA'):
                session.propose_beats(rendered['id'], bad, 'codex', 'Invalid source')
            self.assertEqual(session._load(), before)
            result = session.propose_beats(rendered['id'], spec, 'codex', 'Synthetic safe interval')
            state = session._load()
            self.assertEqual(state['phase'], 'needs_selection')
            updated = read(result['plan']['path'])
            self.assertEqual(updated['status'], 'proposed')
            self.assertNotIn('review', updated)
            self.assertEqual(updated['sequence'][0]['source_end_frame_exclusive'], 3)
            self.assertEqual(read(result['report']['path'])['video_sha256'], rendered['files']['video']['sha256'])
            with self.assertRaisesRegex(ValueError, 'select|approved|review', ):
                session.render(preview=False)
            session.approve('codex', 'Generated fixture revision selected, no human review')
            revised = session.render(preview=False)
            mapping = read(revised['files']['mapping']['path'])
            self.assertEqual(mapping['frame_count'], 7)
            production = read(revised['files']['production']['path'])
            self.assertEqual(Fraction(production['cues'][0]['output_end']), Fraction(7, 10))
            with self.assertRaisesRegex(ValueError, 'current'):
                session.propose_beats(rendered['id'], spec, 'codex', 'Stale render')

    def test_cli_exposes_explicit_spec_and_actor(self):
        args = parser().parse_args(['propose-beats', '/tmp/session', 'r1',
                                  '--spec-file', '/tmp/spec.json', '--note', 'local test'])
        self.assertEqual(args.actor, 'codex')
        self.assertEqual(args.render_id, 'r1')
