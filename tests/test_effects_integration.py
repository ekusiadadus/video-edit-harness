"""Effect requests must reach real renders, not only instructions."""
from pathlib import Path
import tempfile
import unittest

from tests.test_visual_editing import VisualEditingTests
from video_harness.common import read
from video_harness.production import resolve_production
from video_harness.visual_editing import render_visual_edit


class EffectIntegrationTests(unittest.TestCase):
    def test_registered_comparison_and_keyword_reach_full_visual_render(self):
        from datetime import date
        import subprocess
        from video_harness.assets import register_asset
        from video_harness.video_effects import _digest
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            cfg,plan=VisualEditingTests().fixture(root,source_audio=False)
            baseline=render_visual_edit(cfg,plan,root/'baseline',preview=False)
            mapping=read(baseline/'frame-mapping.json')
            second=root/'second-red.mp4'
            subprocess.run(['ffmpeg','-v','error','-nostdin','-n','-f','lavfi','-i',
                            'color=red:s=128x128:r=10:d=1','-c:v','libx264','-pix_fmt','yuv420p',str(second)],
                           check=True,capture_output=True)
            evidence=root/'comparison-rights.txt';evidence.write_text('Synthetic comparison footage generated for this test.')
            asset=register_asset(second,{'asset_id':'second','kind':'video','creator':'Test fixture',
                'source_url':'https://example.org/second','license_url':'https://example.org/rights',
                'acquired_on':date.today().isoformat(),'verified_on':date.today().isoformat(),
                'evidence_path':str(evidence),'credit':'Synthetic second footage','cost':0,
                'currency':'JPY','content_id':'none','rights':cfg['assets'][0]['rights']})
            cfg['assets'].append(asset)
            cfg['editing_pattern']={'id':'playful_short','music':'off','sfx':'off','beat_sync':'off'}
            cfg['fcp_handoff']='video_only'
            cfg['video_effects']={'version':1,'mapping_sha256':_digest(mapping),'events':[
                {'id':'distinct','type':'comparison_wipe','output_start':'0','output_end':'4/5',
                 'strength':1,'reason':'Show separately registered red footage','parameters':{'asset_id':'second'}},
                {'id':'word','type':'keyword_title','output_start':'0','output_end':'4/5',
                 'strength':1,'reason':'Label this comparison','parameters':{'text':'比較','y':.9}}]}
            with self.assertRaisesRegex(ValueError, 'user-owned'):
                resolve_production(cfg, mapping)
            cfg['editing_pattern']['visual_assets']='licensed'
            output=render_visual_edit(cfg,plan,root/'comparison',preview=False)
            applied=read(output/'effects-evidence.json')
            self.assertEqual(applied['secondary_inputs'][0]['sha256'],asset['sha256'])
            self.assertEqual(applied['frame_count'],8)
            self.assertEqual(len(applied['text_assets']),1)
            self.assertTrue(applied['text_assets'][0]['font_sha256'])
            self.assertEqual(read(output/'result.json')['technical_status'],'pass')

    def test_requested_preset_is_burned_and_evidenced_in_visual_render(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            cfg, plan = VisualEditingTests().fixture(root, source_audio=False)
            cfg.update(editing_pattern={'id': 'playful_short', 'music': 'off', 'sfx': 'off',
                                        'visual_assets': 'off', 'beat_sync': 'off'},
                       video_effects={'preset': 'pop_dance', 'intensity': 'low'},
                       fcp_handoff='video_only')
            output = render_visual_edit(cfg, plan, root / 'effects', preview=False)
            production = read(output / 'production.json')
            self.assertTrue(production['effects']['events'])
            self.assertTrue((output / 'effects-evidence.json').is_file())
            self.assertEqual(read(output / 'result.json')['technical_status'], 'pass')
            self.assertEqual(read(output / 'frame-mapping.json')['frame_count'], 8)

    def test_natural_conflict_and_editable_handoff_never_silently_drop_effects(self):
        mapping = {'duration': 2, 'fps': '10', 'frame_count': 20,
                   'sequence': [{'id': 'a', 'output_start': '0s', 'output_end': '1s'},
                                {'id': 'b', 'output_start': '1s', 'output_end': '2s'}]}
        cfg = {'editing_pattern': {'id': 'natural'},
               'video_effects': {'preset': 'pop_dance', 'intensity': 'medium'}}
        with self.assertRaisesRegex(ValueError, 'natural/off'):
            resolve_production(cfg, mapping)
        from video_harness.production import prepare_fcp_handoff
        production = {'effects': {'events': [{'id': 'requested'}]}}
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaisesRegex(ValueError, 'editable FCP effects'):
                prepare_fcp_handoff({'fcp_handoff': 'editable'}, production, temp)
