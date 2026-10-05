import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from video_harness.common import fingerprint
from video_harness.privacy import permitted_providers, require_cloud_permission
from video_harness.transcription_router import transcribe
from video_harness.cloud_transcript import transcribe_cloud


class CloudPermissionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.source = self.root / 'source.mov'
        self.source.write_bytes(b'synthetic fixture')
        self.cfg = {'source': str(self.source)}

    def allow(self, providers=('openai', 'azure')):
        self.cfg['cloud_permission'] = {
            'source_sha256': fingerprint(self.source)['sha256'], 'policy': 'allow',
            'providers': list(providers), 'basis': 'synthetic fixture consent',
            'actor': 'human', 'at': '2026-10-05T00:00:00Z'}

    def test_unknown_and_denied_reject_before_cloud_client_or_output(self):
        for permission, message in ((None, 'unknown'), ({'policy': 'deny'}, 'denied')):
            self.cfg['cloud_permission'] = permission
            with patch('video_harness.cloud_transcript._client') as client:
                with self.assertRaisesRegex(ValueError, message):
                    transcribe_cloud(self.cfg, 'openai', self.root / 'cache')
                client.assert_not_called()
            output = self.root / 'routing'
            with self.assertRaisesRegex(ValueError, message):
                transcribe(self.cfg, output, provider='openai')
            self.assertFalse(output.exists())

    def test_matching_source_reuses_permission_and_provider_scope(self):
        self.allow(('azure',))
        self.assertEqual(permitted_providers(self.cfg, 'auto'), ['azure'])
        self.assertIs(require_cloud_permission(self.cfg, 'azure'), self.cfg['cloud_permission'])
        self.assertIs(require_cloud_permission(self.cfg, 'azure'), self.cfg['cloud_permission'])
        with self.assertRaisesRegex(ValueError, 'does not include openai'):
            require_cloud_permission(self.cfg, 'openai')
        with patch('video_harness.cloud_transcript.transcribe_cloud') as cloud:
            with self.assertRaisesRegex(ValueError, 'does not include openai'):
                transcribe(self.cfg, self.root / 'wrong-provider', provider='openai')
            cloud.assert_not_called()
        self.assertFalse((self.root / 'wrong-provider').exists())

    def test_source_hash_drift_rejects_before_upload(self):
        self.allow()
        self.source.write_bytes(b'different fixture')
        with patch('video_harness.cloud_transcript._client') as client:
            with self.assertRaisesRegex(ValueError, 'does not match'):
                transcribe_cloud(self.cfg, 'openai', self.root / 'cache')
            client.assert_not_called()


if __name__ == '__main__':
    unittest.main()
