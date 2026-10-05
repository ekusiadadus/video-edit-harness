"""Process ownership remains conservative when a sandbox blocks ps."""
import unittest
from unittest.mock import patch

from video_harness.common import read
from tests.test_session import SessionFixture


class SessionProcessTests(unittest.TestCase):
    def setUp(self):
        self.fx = SessionFixture()
        self.addCleanup(self.fx.close)

    def _operation(self, birth='known birth'):
        session = self.fx.session
        with session._lock():
            state = session._load()
            state['operation'] = {'kind': 'render', 'id': 'interrupted',
                                  'path': str(self.fx.root / 'missing-render'),
                                  'pid': 424242, 'process_birth': birth,
                                  'plan': None, 'project': state['project'],
                                  'brief': state['brief'], 'preview': True}
            state['phase'] = 'rendering'
            session._save(state, 'render_started', 'codex')
        return session.status()['generation']

    def test_render_succeeds_when_ps_is_forbidden(self):
        self.fx.selected()
        for failure in (PermissionError('ps blocked'), OSError('ps unavailable')):
            with self.subTest(failure=type(failure).__name__), patch(
                    'video_harness.session.subprocess.check_output', side_effect=failure):
                self.fx.render(preview=True)
            started = [read(path)['state']['operation'] for path in sorted(
                (self.fx.session.root / 'checkpoints').glob('*.json'))
                if read(path)['state']['operation']]
            self.assertIsNone(started[-1]['process_birth'])
            self.assertEqual(started[-1]['process_identity_status'], 'unknown')
        self.assertEqual(self.fx.session.status()['phase'], 'needs_review')

    def test_resume_unknown_owner_does_not_clear_operation(self):
        generation = self._operation()
        with patch('video_harness.session.os.kill'), patch(
                'video_harness.session.subprocess.check_output', side_effect=PermissionError('ps blocked')):
            result = self.fx.session.resume()
        self.assertEqual(result['operation_liveness'], 'unknown')
        self.assertEqual(result['generation'], generation)
        self.assertIsNotNone(result['operation'])
        self.assertIn('unavailable', result['next_action'])

    def test_resume_active_owner_stays_active_and_missing_pid_recovers(self):
        generation = self._operation()
        with patch('video_harness.session.os.kill'), patch(
                'video_harness.session.subprocess.check_output', return_value='known birth'):
            active = self.fx.session.resume()
        self.assertEqual(active['operation_liveness'], 'active')
        self.assertEqual(active['generation'], generation)
        with patch('video_harness.session.os.kill', side_effect=ProcessLookupError):
            stale = self.fx.session.resume()
        self.assertIsNone(stale['operation'])
        self.assertEqual(stale['phase'], 'operation_interrupted')

    def test_resume_unknown_birth_and_ps_oserror_remain_unknown(self):
        self._operation(birth=None)
        with patch('video_harness.session.os.kill'):
            self.assertEqual(self.fx.session.resume()['operation_liveness'], 'unknown')
        # A known birth also remains unknown if ps fails with a non-permission OS error.
        session = self.fx.session
        with session._lock():
            state = session._load()
            state['operation']['process_birth'] = 'known birth'
            session._save(state, 'identity_updated', 'codex')
        with patch('video_harness.session.os.kill'), patch(
                'video_harness.session.subprocess.check_output', side_effect=OSError('ps unavailable')):
            self.assertEqual(session.resume()['operation_liveness'], 'unknown')


if __name__ == '__main__':
    unittest.main()
