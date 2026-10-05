"""Session cloud policy follows the source into the router."""
import unittest
from unittest.mock import patch

from video_harness.common import fingerprint
from tests.test_session import SessionFixture


class SessionCloudPolicyTests(unittest.TestCase):
    def setUp(self):
        self.fx = SessionFixture()
        self.addCleanup(self.fx.close)

    def test_policy_is_source_bound_and_injected(self):
        source = fingerprint(self.fx.source)
        policy = self.fx.session.set_cloud_policy('deny', 'human', 'Keep this fixture local')
        self.assertEqual(policy['source_sha256'], source['sha256'])
        self.assertEqual(self.fx.session.status()['cloud_permission']['policy'], 'deny')
        with patch('video_harness.transcription_router.transcribe', side_effect=ValueError('blocked')) as route:
            with self.assertRaisesRegex(ValueError, 'blocked'):
                self.fx.session.transcribe()
        self.assertEqual(route.call_args.args[0]['cloud_permission'], policy)


if __name__ == '__main__':
    unittest.main()
