"""An exported comparison choice restores an exact render as an unadopted candidate."""

from copy import deepcopy
from pathlib import Path
import shutil
import tempfile
import unittest

from tests import test_visual_editing as visual_helpers
from tests.test_session import SessionFixture
from video_harness.common import read, write
from video_harness.session import Session


@unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'FFmpeg required')
class ComparisonSelectionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        cfg, plan = visual_helpers.VisualEditingTests().fixture(self.root, source_audio=True)
        cfg['edit_basis'] = 'visual'
        project = self.root / 'project.json'
        write(project, cfg)
        self.session = Session.start(project, self.root / 'session')
        self.session.propose_visual(plan, 'automation')
        self.session.approve('automation', 'Synthetic source inspection')
        self.first = self.session.render(preview=False, actor='automation')
        self.session.update_project({'style': 'warm_documentary'}, 'automation',
                                    'Synthetic style comparison')
        later = deepcopy(plan)
        later['sequence'].reverse()
        self.session.propose_visual(later, 'automation')
        self.session.approve('automation', 'Synthetic reordered selection')
        self.second = self.session.render(preview=False, actor='automation')
        self.current = self.session._load()

    def selection(self, render=None):
        render = render or self.first
        return {'version': 1, 'kind': 'comparison_selection_proposal',
                'render_id': render['id'],
                'render_sha256': render['files']['video']['sha256'],
                'output_time': 0.1, 'note': 'Choose the original order and look',
                'adopted': False, 'final_review': False}

    def assert_current_unchanged(self):
        after = self.session._load()
        for key in ('project', 'plan', 'brief', 'transcript', 'packed', 'reviews',
                    'adopted_candidate_id', 'phase'):
            self.assertEqual(after.get(key), self.current.get(key), key)

    def test_first_of_two_reordered_renders_restores_exact_snapshot_only_as_candidate(self):
        self.assertNotEqual(self.first['plan'], self.second['plan'])
        self.assertNotEqual(self.first['project'], self.second['project'])
        proposal = self.session.candidate_from_selection(
            self.selection(), 'codex', 'Restore choice for another render')
        candidate = proposal.get('candidate', proposal)
        self.assertEqual(read(candidate['plan']['path']), read(self.first['plan']['path']))
        self.assertEqual(read(candidate['project']['path']), read(self.first['project']['path']))
        self.assertNotEqual(candidate['plan'], self.current['plan'])
        self.assertNotEqual(candidate['project'], self.current['project'])
        self.assert_current_unchanged()
        with self.assertRaisesRegex(ValueError, 'Render'):
            self.session.adopt_candidate(candidate['id'], 'codex', 'Too early')
        rendered = self.session.render(preview=False, actor='codex', candidate_id=candidate['id'])
        self.assertEqual(rendered['plan'], candidate['plan'])
        self.assertEqual(rendered['project'], candidate['project'])
        self.assertEqual(self.session._load()['reviews'], [])
        self.session.adopt_candidate(candidate['id'], 'codex', 'Use rendered choice')
        adopted = self.session._load()
        self.assertEqual(adopted['plan'], candidate['plan'])
        self.assertEqual(adopted['project'], candidate['project'])
        self.assertEqual(adopted['reviews'], [])
        self.assertEqual(adopted['phase'], 'needs_render')

    def test_invalid_receipts_are_rejected_without_state_change(self):
        base = self.selection()
        invalid = [
            {'render_sha256': '0' * 64},
            {'render_id': 'missing-render'},
            {'version': 2},
            {'kind': 'other'},
            {'output_time': -1},
            {'output_time': '0.1'},
            {'output_time': float('nan')},
            {'output_time': 100},
            {'adopted': True},
            {'final_review': True},
            {'unknown': 'field'},
        ]
        for mutation in invalid:
            with self.subTest(mutation=mutation):
                before = len(self.session._load().get('candidates', []))
                with self.assertRaises(ValueError):
                    self.session.candidate_from_selection(
                        {**base, **mutation}, 'codex', 'Reject invalid receipt')
                self.assertEqual(len(self.session._load().get('candidates', [])), before)
                self.assert_current_unchanged()
        without_note = dict(base)
        del without_note['note']
        with self.assertRaises(ValueError):
            self.session.candidate_from_selection(without_note, 'codex', 'Missing field')
        self.assert_current_unchanged()
        video = Path(self.first['files']['video']['path'])
        original = video.read_bytes()
        try:
            video.write_bytes(b'tampered render')
            with self.assertRaises(ValueError):
                self.session.candidate_from_selection(base, 'codex', 'Reject tampered render')
        finally:
            video.write_bytes(original)
        self.assert_current_unchanged()


class SpeechSelectionTests(unittest.TestCase):
    def test_speech_selection_preserves_snapshot_and_rebuilds_legacy_context(self):
        fixture = SessionFixture()
        self.addCleanup(fixture.close)
        fixture.selected()
        first = fixture.render(preview=True)
        fixture.session.correct_transcript([{'word_id': 'w1', 'text': 'Corrected'}],
                                           'codex', 'Synthetic correction')
        fixture.propose()
        fixture.session.approve('codex', 'Synthetic corrected sequence')
        second = fixture.render(preview=True)
        before = fixture.session._load()
        self.assertNotEqual(first['plan'], second['plan'])
        selection = {'version': 1, 'kind': 'comparison_selection_proposal',
                     'render_id': first['id'],
                     'render_sha256': first['files']['video']['sha256'],
                     'output_time': 0.1, 'note': 'Restore original words',
                     'adopted': False, 'final_review': False}
        candidate = fixture.session.candidate_from_selection(
            selection, 'codex', 'Restore exact old plan')
        self.assertEqual(candidate['plan'], first['plan'])
        self.assertEqual(read(candidate['transcript']['path']),
                         read(first['plan']['path'])['transcript'])
        self.assertEqual(read(candidate['transcript']['path'])['words'][0]['text'], 'First')
        self.assertEqual(candidate['packed'], first['packed'])
        self.assertEqual(read(candidate['packed']['path'])['words'][0]['text'], 'First')
        after = fixture.session._load()
        for key in ('plan', 'project', 'transcript', 'packed', 'reviews', 'phase'):
            self.assertEqual(before[key], after[key], key)

        # Simulate a checkpoint written before renders retained these two refs.
        legacy = fixture.session._load()
        old_render = next(r for r in legacy['renders'] if r['id'] == first['id'])
        old_render.pop('transcript')
        old_render.pop('packed')
        fixture.session._save(legacy, 'legacy_fixture', 'automation')
        restored = fixture.session.candidate_from_selection(
            selection, 'codex', 'Restore legacy render with actual plan words')
        original_words = read(first['plan']['path'])['transcript']['words']
        word_fields = ('id', 'start', 'end', 'text')
        expected_context_words = [{key: word[key] for key in word_fields}
                                  for word in original_words]
        self.assertEqual(read(restored['transcript']['path'])['words'], original_words)
        self.assertEqual(read(restored['packed']['path'])['words'], expected_context_words)
        fixture.render(preview=True, candidate_id=restored['id'])
        fixture.session.adopt_candidate(restored['id'], 'codex', 'Use legacy render after rerender')
        self.assertEqual(fixture.session.context(words=True)['words'], expected_context_words)
        self.assertEqual(fixture.session._load()['reviews'], [])


if __name__ == '__main__':
    unittest.main()
