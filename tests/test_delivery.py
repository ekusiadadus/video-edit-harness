import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from video_harness.common import read
from video_harness.delivery import bundle
from video_harness.session import FCP_CHECKS
from tests.test_feedback import review_report
from tests.test_session import SessionFixture


class DeliveryTests(unittest.TestCase):
    def setUp(self):
        self.fx = SessionFixture()
        self.addCleanup(self.fx.close)

    def test_full_current_render_and_manual_checks_required(self):
        self.fx.selected()
        preview = self.fx.render(preview=True)
        self.fx.session.review(preview['id'], review_report(preview), 'human')
        preview_package = self.fx.session.package(preview['id'], target='mp4')
        with self.assertRaisesRegex(ValueError, 'full-resolution'):
            self.fx.session.finish(preview_package['id'])
        final = self.fx.render(preview=False)
        package = self.fx.session.package(final['id'], target='fcp')
        manifest = read(package['artifact']['path'])
        self.assertEqual(manifest['status'], 'needs_manual_checks')
        self.assertEqual(set(manifest['manual_checks_required']), set(FCP_CHECKS))
        with self.assertRaisesRegex(ValueError, 'passing review'):
            self.fx.session.finish(package['id'])
        self.fx.session.review(final['id'], review_report(final), 'human')
        with self.assertRaisesRegex(ValueError, 'Delivery checks remain'):
            self.fx.session.finish(package['id'])
        for check in FCP_CHECKS:
            self.fx.session.delivery_check(package['id'], check, 'pass', 'synthetic',
                'human', 'Synthetic test fixture only')
        result = self.fx.session.finish(package['id'], 'human')
        self.assertEqual(result['status'], 'synthetic_complete')
        self.assertEqual(result['render_id'], final['id'])

    def test_delivery_source_tamper_and_stale_project_rejected(self):
        self.fx.selected()
        render = self.fx.render()
        self.fx.session.review(render['id'], review_report(render), 'human')
        with tempfile.TemporaryDirectory() as tmp:
            Path(render['files']['video']['path']).write_bytes(b'changed')
            with self.assertRaises(ValueError):
                bundle(render, self.fx.session.status()['brief'], 'mp4', Path(tmp) / 'bad', accepted=True)

    def test_unsupported_fcp_import_preserves_current_plan(self):
        self.fx.selected()
        before = self.fx.session.status()
        xml = self.fx.root / 'unsupported.fcpxml'
        xml.write_text('<fcpxml version="1.10"/>')
        with patch('video_harness.fcp_import.import_fcpxml', return_value=(None,
                   {'status': 'unverified', 'reasons': ['Retime is unsupported']})):
            with self.assertRaises(ValueError):
                self.fx.session.import_fcp(xml, 'codex', 'Inspect returned timeline')
        after = self.fx.session.status()
        self.assertEqual(after['generation'], before['generation'])
        self.assertEqual(after['plan'], before['plan'])


if __name__ == '__main__':
    unittest.main()
