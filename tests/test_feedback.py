import unittest

from video_harness.feedback import map_output
from video_harness.session import CHECKS
from tests.test_session import SessionFixture


def review_report(render, resolved=()):
    return {'render_sha256': render['files']['video']['sha256'],
            'checks': [{'id': check, 'status': 'pass', 'basis': 'synthetic',
                        'note': 'Synthetic fixture observation'} for check in CHECKS],
            'resolved_feedback_ids': list(resolved)}


class FeedbackTests(unittest.TestCase):
    def setUp(self):
        self.fx = SessionFixture()
        self.addCleanup(self.fx.close)

    def test_output_time_uses_sequence_identity_and_rejects_malformed_mapping(self):
        mapping = {'duration': 2., 'keep': [[2., 3.], [0., 1.]],
                   'sequence_ids': ['later', 'first']}
        result = map_output(mapping, .75, 1.25)
        self.assertEqual([span['sequence_id'] for span in result['source_spans']], ['later', 'first'])
        self.assertAlmostEqual(result['source_spans'][0]['source_start'], 2.75)
        self.assertAlmostEqual(result['source_spans'][1]['source_start'], 0.)
        with self.assertRaises(ValueError):
            map_output({**mapping, 'sequence_ids': ['later']}, .2, .3)
        with self.assertRaises(ValueError):
            map_output(mapping, 1.9, 2.1)

    def test_feedback_revision_requires_new_selected_render_and_bound_review(self):
        self.fx.selected()
        first = self.fx.render()
        feedback = self.fx.session.add_feedback(first['id'], .1, .2, 'reorder',
            'Move setup before result', actor='human', render_sha256=first['files']['video']['sha256'])
        self.assertEqual(feedback['source_spans'][0]['sequence_id'], 'later')
        with self.assertRaisesRegex(ValueError, 'different video revision'):
            self.fx.session.add_feedback(first['id'], .1, .2, 'comment', 'Wrong hash', render_sha256='0'*64)
        self.fx.session.revise([{'op': 'reorder', 'ids': ['first', 'later'],
            'reason': 'Explain setup first', 'goal_ids': ['goal-1']}],
            'codex', 'Apply feedback', feedback_id=feedback['id'])
        self.assertEqual(self.fx.session.status()['pending_feedback'][0]['status'], 'addressed')
        self.fx.session.approve('codex', 'Agent selects revised sequence')
        second = self.fx.render()
        with self.assertRaisesRegex(ValueError, 'exact rendered video SHA256'):
            self.fx.session.review(second['id'], {**review_report(second), 'render_sha256': '0'*64}, 'human')
        reviewed = self.fx.session.review(second['id'], review_report(second, [feedback['id']]), 'human')
        self.assertTrue(reviewed['passed'])
        self.assertEqual(self.fx.session.status()['pending_feedback'], [])


if __name__ == '__main__':
    unittest.main()
