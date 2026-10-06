"""Technical temporal-depth CLI and session handoff, without human acceptance."""
from contextlib import redirect_stdout
import importlib.util
import io
import shutil
import unittest

from tests import test_depth_session as session_fixture
from video_harness.common import read
from video_harness.depth_artifact import validate_depth
from video_harness.depth_cli import main as depth_main
from video_harness.delivery import verify_completion


@unittest.skipUnless(importlib.util.find_spec('cv2') and shutil.which('ffmpeg')
                     and shutil.which('ffprobe'), 'OpenCV and FFmpeg required')
class TemporalDepthDeliveryTests(unittest.TestCase):
    def setUp(self):
        session_fixture.DepthSessionTests.setUp(self)

    def stabilize(self):
        output = self.root / 'temporal-cli'
        with redirect_stdout(io.StringIO()):
            depth_main(['stabilize', str(self.manifest), '--output', str(output),
                        '--strength', '.5', '--actor', 'automation',
                        '--note', 'Synthetic source-bound temporal candidate'])
        result = read(output / 'result.json')
        self.assertEqual(result['technical_status'], 'pass')
        manifest = output / 'fields/depth.json'
        doc = validate_depth(manifest)
        self.assertEqual(doc['version'], 4)
        self.assertFalse(doc['adopted'])
        self.assertTrue(doc['review_required'])
        self.assertEqual(doc['temporal']['observations'][0]['reset_reason'], 'interval_start')
        return manifest, doc

    def test_cli_seals_temporal_parent_and_parameters(self):
        manifest, doc = self.stabilize()
        self.assertEqual(doc['temporal']['config']['strength'], .5)
        self.assertEqual(doc['parent']['path'], str(self.manifest.resolve()))
        self.assertEqual(doc['source'], validate_depth(self.manifest)['source'])

    def test_temporal_candidate_and_completed_delivery_keep_provenance(self):
        manifest, doc = self.stabilize()
        proposal = self.session.propose_depth_layer(self.base['id'], manifest, 'layer',
            .5, .1, .5, 'automation', 'Synthetic temporal layer comparison')
        candidate = proposal['candidate']
        self.session.render(preview=False, actor='automation', candidate_id=candidate['id'])
        self.session.adopt_candidate(candidate['id'], 'automation', 'Synthetic candidate selected')
        final = self.session.render(preview=False, actor='automation')
        delivery = self.session.package(final['id'], 'mp4', 'automation')
        checks = ['meaning', 'pacing', 'cut_boundaries', 'color', 'audio_only',
                  'asset_rights', 'depth_contours']
        self.session.review(final['id'], {'render_sha256': final['files']['video']['sha256'],
            'checks': [{'id': key, 'status': 'pass', 'basis': 'synthetic',
                        'note': 'Synthetic local fixture'} for key in checks]}, 'automation')
        completed = self.session.finish(delivery['id'], 'automation')
        from pathlib import Path
        folder = Path(delivery['artifact']['path']).parent
        public = read(folder / 'depth-provenance.json')
        self.assertEqual(public['lineage'][0]['version'], 4)
        self.assertEqual(public['lineage'][0]['temporal'], doc['temporal'])
        self.assertEqual(public['lineage'][1]['manifest_sha256'], doc['parent']['sha256'])
        self.assertNotIn(str(self.root), (folder / 'depth-provenance.json').read_text())
        self.assertEqual(completed['status'], 'synthetic_complete')
        self.assertEqual(verify_completion(folder)['status'], 'synthetic_complete')
