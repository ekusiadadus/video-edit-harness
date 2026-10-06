import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location('release_audit',
    Path(__file__).resolve().parents[1] / 'scripts/verify_release_artifacts.py')
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)


class ReleaseAuditTests(unittest.TestCase):
    def test_rejects_private_members_traversal_and_credentials_without_leaking(self):
        for name in ('../private.mp4', '/abs.txt', 'pkg/media/a.png',
                     'pkg/output/a.json', 'pkg/.env', 'pkg/music.wav'):
            with self.assertRaises(ValueError):
                audit.audit_member(name, b'fixture')
        with self.assertRaises(ValueError) as caught:
            audit.audit_member('pkg/example.json', b'{"key":"fixture-credential"}',
                               [b'fixture-credential'])
        self.assertNotIn('fixture-credential', str(caught.exception))
        result = audit.audit_member('pkg/video_harness/production.py', b'code')
        self.assertEqual(result['bytes'], 4)
        self.assertEqual(len(result['sha256']), 64)


if __name__ == '__main__':
    unittest.main()
