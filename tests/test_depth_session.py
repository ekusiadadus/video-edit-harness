"""Synthetic session lifecycle for a source-bound local depth layer."""
from datetime import date
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

import numpy as np
from PIL import Image

from tests import test_visual_editing as visual_fixture
from video_harness.assets import register_asset
from video_harness.common import probe, read, write
from video_harness.depth_artifact import prepare_manual_depth
from video_harness.session import Session
from video_harness.delivery import bundle
from video_harness.visual_editing import validate_depth_setting


class DepthSettingContractTests(unittest.TestCase):
    def test_malformed_setting_rejected_before_media_access(self):
        binding = {'path': '/missing/file', 'sha256': 'a' * 64, 'bytes': 1}
        valid = {'version': 1, 'backend': 'local_baked', 'base_render_id': 'render',
            'graded_picture': binding, 'manifest': binding, 'asset_id': 'layer',
            'asset_record_sha256': 'b' * 64,
            'parameters': {'threshold': .5, 'softness': .1, 'strength': 1},
            'actor': 'codex', 'reason': 'Synthetic contract', 'review_required': True,
            'adopted': False}
        for changed in ({'version': True}, {'version': 1.0},
                        {'manifest': {'path': '/missing/file'}},
                        {'graded_picture': {'path': '/missing/file'}},
                        {'asset_id': ''}, {'base_render_id': ''}):
            with self.subTest(changed=changed), self.assertRaises(ValueError):
                validate_depth_setting({**valid, **changed}, {}, Path('/missing/file'))


@unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'FFmpeg required')
class DepthSessionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        cfg, plan = visual_fixture.VisualEditingTests().fixture(self.root, source_audio=True)
        image = self.root / 'layer.png'
        Image.new('RGBA', (128, 128), (255, 50, 20, 255)).save(image)
        rights = self.root / 'layer-rights.txt'
        rights.write_text('Synthetic image rights for local test.')
        cfg['assets'].append(register_asset(image, {
            'asset_id': 'layer', 'kind': 'image', 'creator': 'Synthetic fixture',
            'source_url': 'https://example.org/layer', 'license_url': 'https://example.org/layer-rights',
            'acquired_on': date.today().isoformat(), 'verified_on': date.today().isoformat(),
            'evidence_path': str(rights), 'credit': 'Synthetic layer', 'cost': 0, 'currency': 'JPY',
            'content_id': 'none', 'rights': {'status': 'verified', 'commercial': True,
                'advertising': False, 'modification': True, 'destinations': ['youtube'],
                'regions': [], 'attribution_required': False, 'embedded_use': True,
                'mixed_audio_handoff': False, 'raw_asset_handoff': False}}))
        cfg.update(edit_basis='visual', fcp_handoff='video_only')
        write(self.root / 'project.json', cfg)
        self.session = Session.start(self.root / 'project.json', self.root / 'session')
        self.session.propose_visual(plan, 'automation')
        self.session.approve('automation', 'Synthetic selected visual spans')
        self.enabled = self.session.create_candidate({'editing_pattern': {'id': 'playful_short',
            'music': 'off', 'sfx': 'off', 'beat_sync': 'off', 'visual_assets': 'licensed',
            'selection': 'manual'}},
            'automation', 'Synthetic depth direction')
        self.base = self.session.render(preview=False, actor='automation', candidate_id=self.enabled['id'])
        graded_stream = next(s for s in probe(Path(self.base['path']) / 'visual-graded.mp4')['streams']
                             if s['codec_type'] == 'video')
        self.assertEqual(tuple(graded_stream.get(key) for key in
                         ('color_primaries', 'color_transfer', 'color_space')),
                         ('bt709', 'bt709', 'bt709'))
        self.fields = {}
        for frame in (1, 2):
            field = np.zeros((128, 128), dtype=np.float32)
            field[:, 64:] = 1
            path = self.root / f'{frame}.npy'
            np.save(path, field, allow_pickle=False)
            self.fields[frame] = path
        self.manifest = prepare_manual_depth(Path(self.base['path']) / 'visual-graded.mp4',
            self.fields, self.root / 'depth', 'automation', 'Synthetic near-high ordering')

    def test_candidate_comparison_selection_adoption_and_delivery(self):
        proposed = self.session.propose_depth_layer(self.base['id'], self.manifest, 'layer',
            .5, .1, .8, 'codex', 'Compare behind nearer picture')
        candidate = proposed['candidate']
        self.assertNotIn('depth_layer', read(self.session._load()['project']['path']))
        depth = self.session.render(preview=False, actor='automation', candidate_id=candidate['id'])
        evidence = read(depth['files']['depth_evidence']['path'])
        self.assertEqual(evidence['base']['sha256'], proposed['depth_layer']['graded_picture']['sha256'])
        self.assertEqual(evidence['image_asset']['asset_id'], 'layer')
        natural = self.session.create_candidate({'editing_pattern': {'id': 'natural'}},
            'automation', 'Same source and audio natural comparison', base_render_id=self.base['id'])
        natural_render = self.session.render(preview=False, actor='automation', candidate_id=natural['id'])
        comparison = self.session.compare_candidates([natural_render['id'], depth['id']])
        self.assertTrue(comparison['artifact'])
        def pcm(render):
            return subprocess.check_output(['ffmpeg', '-v', 'error', '-i',
                render['files']['video']['path'], '-map', '0:a:0', '-f', 's16le', '-'])
        self.assertEqual(pcm(natural_render), pcm(depth))
        selection = {'version': 1, 'kind': 'comparison_selection_proposal',
            'render_id': depth['id'], 'render_sha256': depth['files']['video']['sha256'],
            'output_time': .2, 'note': 'Synthetic selection', 'adopted': False, 'final_review': False}
        selected = self.session.candidate_from_selection(selection, 'automation', 'Select exact depth setting')
        self.assertEqual(read(selected['project']['path'])['depth_layer'], proposed['depth_layer'])
        self.session.render(preview=False, actor='automation', candidate_id=selected['id'])
        self.session.adopt_candidate(selected['id'], 'automation', 'Synthetic adoption')
        final = self.session.render(preview=False, actor='automation')
        self.assertIn('depth_evidence', final['files'])
        with self.assertRaisesRegex(ValueError, 'depth_contours'):
            self.session.review(final['id'], {'render_sha256': final['files']['video']['sha256'],
                'checks': []}, 'automation')
        packaged = read(bundle(final, final['brief'], 'mp4', self.root / 'delivery', accepted=False))
        self.assertIn('depth_evidence', packaged['files'])
        self.assertIn('depth_provenance', packaged['files'])
        for name in ('depth-evidence.json', 'depth-provenance.json'):
            self.assertNotIn(str(self.root), (self.root / 'delivery' / name).read_text())
        public = read(self.root / 'delivery' / 'depth-provenance.json')
        original = read(self.manifest)
        self.assertEqual(public['lineage'][0]['fps'], original['fps'])
        self.assertEqual(public['lineage'][0]['rows'], [
            {'frame': row['frame'], 'field_sha256': row['field']['sha256'],
             'input_sha256': row['input']['sha256'], 'origin': row['origin'],
             'minimum': row['minimum'], 'maximum': row['maximum']} for row in original['rows']])
        self.assertFalse((self.root / 'delivery' / 'layer.png').exists())
        self.assertIn('layer', [row['asset_id'] for row in read(self.root / 'delivery' / 'credits.json')['assets']])
        pending = self.session.package(final['id'], 'mp4', 'automation')
        with self.assertRaisesRegex(ValueError, 'passing review'):
            self.session.finish(pending['id'], 'automation')
        checks = ['meaning', 'pacing', 'cut_boundaries', 'color', 'audio_only',
                  'asset_rights', 'depth_contours']
        report = {'render_sha256': final['files']['video']['sha256'], 'checks': [
            {'id': key, 'status': 'pass', 'basis': 'synthetic', 'note': 'Synthetic local fixture'}
            for key in checks]}
        accepted = self.session.review(final['id'], report, 'automation')
        self.assertTrue(accepted['passed'])
        complete = self.session.finish(pending['id'], 'automation')
        self.assertEqual(complete['status'], 'synthetic_complete')
        from video_harness.delivery import verify_completion
        finished_folder = Path(pending['artifact']['path']).parent
        project_proof = read(finished_folder / 'evidence' / 'project.json')
        self.assertEqual(project_proof['_depth_project_original_sha256'], final['project']['sha256'])
        for key in ('manifest', 'graded_picture'):
            self.assertEqual(set(project_proof['depth_layer'][key]), {'sha256', 'bytes'})
            self.assertEqual(project_proof['depth_layer'][key]['sha256'],
                             proposed['depth_layer'][key]['sha256'])
        self.assertNotIn(str(self.root), str(project_proof['depth_layer']))
        self.assertEqual(verify_completion(finished_folder)['status'], 'synthetic_complete')
        self.assertEqual(self.session.finish(pending['id'], 'automation')['portable_completion'],
                         complete['portable_completion'])
        self.session.update_project({'audio': {**read(final['project']['path'])['audio'],
            'target_lufs': -18}}, 'automation', 'Revise output audio only')
        self.assertEqual(read(self.session._load()['project']['path'])['depth_layer'],
                         proposed['depth_layer'])
        revised = self.session.create_candidate({'audio': {**read(final['project']['path'])['audio'],
            'target_lufs': -19}}, 'automation', 'Candidate audio change')
        self.assertEqual(read(revised['project']['path'])['depth_layer'], proposed['depth_layer'])
        downstream = self.session.create_candidate({'video_effects': None}, 'automation',
            'Revise downstream effects without touching grade', base_render_id=final['id'])
        self.assertEqual(read(downstream['project']['path'])['depth_layer'], proposed['depth_layer'])

    def test_natural_off_and_stale_bindings_rejected(self):
        with self.assertRaisesRegex(ValueError, 'natural/off'):
            natural = self.session.render(preview=False, actor='automation')
            self.session.propose_depth_layer(natural['id'], self.manifest, 'layer',
                .5, .1, 1, 'codex', 'Conflict')
        proposed = self.session.propose_depth_layer(self.base['id'], self.manifest, 'layer',
            .5, .1, .8, 'codex', 'Test stale source')
        natural = self.session.create_candidate({'editing_pattern': {'id': 'natural'}},
            'automation', 'Remove additions', base_render_id=self.base['id'])
        self.assertNotIn('depth_layer', read(natural['project']['path']))
        project = read(proposed['candidate']['project']['path'])
        from video_harness.visual_editing import validate_depth_setting
        project['depth_layer']['graded_picture']['sha256'] = '0' * 64
        with self.assertRaisesRegex(ValueError, 'graded source changed'):
            validate_depth_setting(project['depth_layer'], project,
                Path(self.base['path']) / 'visual-graded.mp4')
        project = read(proposed['candidate']['project']['path'])
        project['depth_layer']['asset_record_sha256'] = '0' * 64
        with self.assertRaisesRegex(ValueError, 'registration changed'):
            validate_depth_setting(project['depth_layer'], project,
                Path(self.base['path']) / 'visual-graded.mp4')
        project = read(proposed['candidate']['project']['path'])
        project['depth_layer']['manifest']['sha256'] = '0' * 64
        with self.assertRaisesRegex(ValueError, 'manifest changed'):
            validate_depth_setting(project['depth_layer'], project,
                Path(self.base['path']) / 'visual-graded.mp4')
        project = read(proposed['candidate']['project']['path'])
        project['editing_pattern']['visual_assets'] = 'off'
        project.pop('_editing_pattern_snapshot', None)
        with self.assertRaisesRegex(ValueError, 'disabled visual assets'):
            validate_depth_setting(project['depth_layer'], project,
                Path(self.base['path']) / 'visual-graded.mp4')
        from video_harness.production import resolve_production
        mapping = read(self.base['files']['mapping']['path'])
        with self.assertRaisesRegex(ValueError, 'disabled visual assets'):
            resolve_production(project, mapping)
        project['editing_pattern']['visual_assets'] = 'own_only'
        with self.assertRaisesRegex(ValueError, 'user-owned'):
            validate_depth_setting(project['depth_layer'], project,
                Path(self.base['path']) / 'visual-graded.mp4')
        with self.assertRaisesRegex(ValueError, 'user-owned'):
            resolve_production(project, mapping)
