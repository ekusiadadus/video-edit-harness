import tempfile
import unittest
import shutil
import json
from pathlib import Path
from unittest.mock import patch

from video_harness.common import read, write, fingerprint
from video_harness.delivery import bundle, verify_completion
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
        with tempfile.TemporaryDirectory() as tmp:
            moved = Path(tmp) / 'delivered'
            shutil.copytree(Path(package['artifact']['path']).parent, moved)
            portable = verify_completion(moved)
            self.assertEqual(portable['status'], 'synthetic_complete')
            self.assertEqual(set(portable['checks']), set(FCP_CHECKS))
            self.assertFalse(portable['manual_checks_remaining'])
            nested = moved / 'extra' / 'completion.json'
            nested.parent.mkdir()
            nested.write_text('{}')
            with self.assertRaisesRegex(ValueError, 'inventory changed'):
                verify_completion(moved)
            nested.unlink()
            completion_path = moved / 'completion.json'
            forged = {**portable, 'status': 'complete', 'checks': {key: 'fail' for key in FCP_CHECKS}}
            completion_path.write_text(json.dumps(forged))
            with self.assertRaisesRegex(ValueError, 'status contradicts'):
                verify_completion(moved)
            completion_path.write_text(json.dumps(portable))
            (moved / portable['evidence']['creative_review']).write_text('changed')
            with self.assertRaisesRegex(ValueError, 'changed'):
                verify_completion(moved)

    def test_portrait_is_bound_reviewed_and_copied_only_when_selected(self):
        self.fx.selected()
        render = self.fx.render(preview=False)
        self.fx.session.review(render['id'], review_report(render), 'human')
        portrait = self.fx.root / 'portrait.mp4'
        portrait.write_bytes(b'synthetic portrait video')
        evidence = self.fx.root / 'portrait-result.json'
        write(evidence, {'technical_status': 'pass', 'source': render['files']['video'],
                         'video': fingerprint(portrait), 'framing': 'fit',
                         'subtitles_source': None, 'font_source': None})
        derivative = self.fx.session.register_derivative(render['id'], evidence)
        with self.assertRaisesRegex(ValueError, 'passing exact-video review'):
            self.fx.session.package(render['id'], target='mp4', derivative_id=derivative['id'])
        report = {'video_sha256': derivative['video']['sha256'],
                  'checks': [{'id': key, 'status': 'pass', 'basis': 'synthetic', 'note': 'Synthetic fixture'}
                             for key in ('framing', 'captions', 'audio', 'playback')]}
        self.fx.session.review_derivative(derivative['id'], report, 'human')
        delivery = self.fx.session.package(render['id'], target='mp4', derivative_id=derivative['id'])
        folder = Path(delivery['artifact']['path']).parent
        self.assertEqual((folder / 'portrait-video.mp4').read_bytes(), portrait.read_bytes())
        self.assertEqual(read(delivery['artifact']['path'])['portrait']['video_sha256'], derivative['video']['sha256'])
        result = self.fx.session.finish(delivery['id'], 'human')
        self.assertEqual(verify_completion(folder)['portrait_video_sha256'], derivative['video']['sha256'])
        self.assertEqual(result['status'], 'synthetic_complete')
        portrait.write_bytes(b'modified')
        with self.assertRaisesRegex(ValueError, 'changed'):
            self.fx.session.status(deep=True)

    def test_mp4_completion_preserves_optional_fcp_observation(self):
        self.fx.selected()
        render = self.fx.render(preview=False)
        self.fx.session.review(render['id'], review_report(render), 'human')
        delivery = self.fx.session.package(render['id'], target='mp4')
        self.fx.session.delivery_check(delivery['id'], 'fcp_import', 'pending', 'synthetic',
                                       'human', 'FCP was not part of this MP4 delivery')
        self.fx.session.finish(delivery['id'], 'human')
        folder = Path(delivery['artifact']['path']).parent
        completion = verify_completion(folder)
        self.assertEqual(completion['checks']['fcp_import'], 'pending')
        self.assertEqual(read(folder / 'delivery.json')['manual_checks_required'], [])
        (folder / 'completion.json').write_text(json.dumps({**completion, 'checks': {'fcp_import': 'pass'}}))
        with self.assertRaisesRegex(ValueError, 'proof contradicts'):
            verify_completion(folder)

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
