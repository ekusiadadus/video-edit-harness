"""Session retime is a candidate, not human approval or editable FCP timing."""
from pathlib import Path
import tempfile
import unittest

from tests import test_visual_editing as helpers
from video_harness.common import write,read
from video_harness.session import Session


class SessionRetimeTests(unittest.TestCase):
    def test_structure_comparison_accepts_sealed_reordered_plans_without_adoption(self):
        from copy import deepcopy
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);cfg,plan=helpers.VisualEditingTests().fixture(root,source_audio=True)
            cfg['edit_basis']='visual'
            project=root/'project.json';write(project,cfg)
            session=Session.start(project,root/'session')
            session.propose_visual(plan,'automation');session.approve('automation','Synthetic original sequence')
            first=session.render(preview=False,actor='automation')
            reordered=deepcopy(plan);reordered['sequence'].reverse()
            session.propose_visual(reordered,'automation');session.approve('automation','Synthetic result-first sequence')
            second=session.render(preview=False,actor='automation')
            before=session._load()
            self.assertNotEqual(first['plan']['sha256'],second['plan']['sha256'])
            for mode in ('effects','timing'):
                with self.assertRaisesRegex(ValueError,'same edit plan'):
                    session.compare_candidates([first['id'],second['id']],mode=mode)
            comparison=session.compare_candidates([first['id'],second['id']],mode='structure')
            evidence=read(comparison['evidence']['path'])
            self.assertEqual(evidence['mode'],'structure')
            self.assertEqual([s['id'] for s in evidence['candidates'][1]['structure']],['second','first'])
            self.assertTrue(evidence['candidates'][1]['source_span_changes']['same_range_multiplicity'])
            self.assertEqual([r['video_sha256'] for r in evidence['candidates']],
                [first['files']['video']['sha256'],second['files']['video']['sha256']])
            page=Path(comparison['artifact']['path']).read_text()
            self.assertIn('構成・順序・間の比較',page)
            self.assertEqual(page.count('<video controls'),2)
            after=session._load()
            for key in ('plan','project','reviews','adopted_candidate_id'):
                self.assertEqual(before.get(key),after.get(key))

    def test_visual_retime_effects_keep_pcm_and_fractional_endpoint_through_fcp_mix(self):
        from fractions import Fraction
        import json
        import subprocess
        import wave
        from video_harness.assets import register_asset
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);cfg,plan=helpers.VisualEditingTests().fixture(root,source_audio=True)
            source=root/'fractional.mp4'
            subprocess.run(['ffmpeg','-v','error','-n','-f','lavfi','-i',
                'color=c=blue:s=128x128:r=30:d=2','-f','lavfi','-i',
                'sine=frequency=440:sample_rate=48000:duration=2','-c:v','libx264',
                '-pix_fmt','yuv420p','-c:a','aac',str(source)],check=True)
            original=cfg['assets'][0]
            metadata={key:original[key] for key in ('asset_id','kind','creator','source_url',
                'license_url','acquired_on','verified_on','evidence_path','credit','rights','cost','currency','content_id')}
            metadata['rights']={**metadata['rights'],'mixed_audio_handoff':True}
            cfg.update({'source':str(source),'edit_basis':'visual','fcp_handoff':'mix',
                'assets':[register_asset(source,metadata)],'editing_pattern':{'id':'playful_short',
                'music':'off','sfx':'off','beat_sync':'off','visual_assets':'off'}})
            plan['sequence']=[{'id':'whole','asset_id':'video1','source_start':0,'source_end':2,
                              'reason':'Synthetic full source interval'}]
            project=root/'project.json';write(project,cfg)
            session=Session.start(project,root/'session');session.propose_visual(plan,'automation')
            session.approve('automation','Synthetic fixture selection')
            base=session.render(preview=False,actor='automation')
            proposal=session.propose_retime(base['id'],{'operations':[{'id':'hold','kind':'freeze',
                'source_frame':4,'output_frames':2,'reason':'Synthetic fractional hold'}]},
                'automation','Synthetic finishing acceptance')
            retimed=session.render(preview=False,actor='automation',candidate_id=proposal['candidate']['id'])
            effect=session.propose_effects(retimed['id'],[{'action':'add','event':{'id':'focus',
                'type':'smooth_zoom','output_start':'0','output_end':'1','strength':.3,
                'reason':'Synthetic finishing effect','parameters':{'anchor_x':.5}}}],
                'automation','Finish the retimed picture')
            result=session.render(preview=False,actor='automation',candidate_id=effect['id'])
            folder=Path(result['path'])
            def raw(path):
                return subprocess.check_output(['ffmpeg','-v','error','-i',str(path),'-map','0:a:0',
                    '-ar','48000','-ac','2','-f','s16le','-'])
            self.assertEqual(raw(folder/'visual-retimed.wav'),raw(folder/'environment.wav'))
            for name in ('visual-retimed.mp4','visual-graded.mp4','visual-effects.mp4','video.mp4'):
                streams=json.loads(subprocess.check_output(['ffprobe','-v','error','-show_streams',
                    '-of','json',str(folder/name)]))['streams']
                audio=next(s for s in streams if s['codec_type']=='audio')
                self.assertEqual(Fraction(audio['duration_ts'])*Fraction(audio['time_base']),Fraction(62,30))
            with wave.open(str(folder/'final-mix.wav'),'rb') as stream:
                self.assertEqual(stream.getnframes(),99200)
            self.assertEqual(read(folder/'fcp-production.json')['mode'],'mix')
            self.assertTrue((folder/'production-timeline.fcpxml').is_file())

    def test_candidate_render_keeps_original_state_and_tracks_original_frames(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);cfg,plan=helpers.VisualEditingTests().fixture(root,source_audio=True)
            cfg['edit_basis']='visual';cfg['editing_pattern']={'id':'playful_short','music':'off','sfx':'off','beat_sync':'off','visual_assets':'own_only'}
            project=root/'project.json';write(project,cfg)
            session=Session.start(project,root/'session');session.propose_visual(plan,'codex');session.approve('codex','Synthetic selection')
            base=session.render(preview=False);before=session._load()['project']
            proposal=session.propose_retime(base['id'],{'operations':[{'id':'hold','kind':'freeze','source_frame':4,'output_frames':2,'reason':'Read the pose'}]},'codex','Synthetic hold')
            self.assertFalse(proposal['adopted']);self.assertEqual(session._load()['project'],before)
            rendered=session.render(preview=False,candidate_id=proposal['candidate']['id'])
            mapping=read(rendered['files']['mapping']['path'])
            self.assertEqual(mapping['frame_count'],10)
            self.assertEqual(mapping['retime']['frames'][4]['base_output_frame'],4)
            self.assertEqual(mapping['retime']['frames'][4]['source_frame'],6)
            self.assertEqual(mapping['retime']['frames'][5]['source_frame'],6)
            self.assertEqual(mapping['retime']['frames'][6]['source_frame'],6)
            self.assertEqual(Path(session.tracking_source(rendered['id'])['source']['path']).name,'visual-graded.mp4')
            self.assertEqual(session._load()['project'],before)
            self.assertTrue((Path(rendered['path'])/'original-cut-reference.fcpxml').is_file())
            natural=session.create_candidate({'editing_pattern':{'id':'natural'}},'codex','Unchanged timing baseline')
            baseline=session.render(preview=False,candidate_id=natural['id'])
            with self.assertRaisesRegex(ValueError,'source frames'):
                session.compare_candidates([baseline['id'],rendered['id']])
            comparison=session.compare_candidates([baseline['id'],rendered['id']],mode='timing')
            self.assertEqual(comparison['mode'],'timing')
            self.assertEqual(read(comparison['evidence']['path'])['mode'],'timing')
            self.assertEqual(session._load()['project'],before)
            with self.assertRaisesRegex(ValueError,'mode'):
                session.compare_candidates([baseline['id'],rendered['id']],mode='unknown')

    def test_natural_rejects_proposal_and_editable_handoff_rejects_retime(self):
        from video_harness.production import prepare_fcp_handoff
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);cfg,plan=helpers.VisualEditingTests().fixture(root,source_audio=False)
            cfg['edit_basis']='visual';project=root/'project.json';write(project,cfg)
            session=Session.start(project,root/'session');session.propose_visual(plan,'codex');session.approve('codex','Synthetic selection')
            base=session.render(preview=False)
            with self.assertRaisesRegex(ValueError,'natural/off'):
                session.propose_retime(base['id'],{'operations':[]},'codex','No implicit direction change')
            with self.assertRaisesRegex(ValueError,'natural/off'):
                session.create_candidate({'editing_pattern':{'id':'natural'},'retime':{'version':1}},
                                         'codex','Reject conflicting explicit instructions')
            with self.assertRaisesRegex(ValueError,'editable FCP time'):
                prepare_fcp_handoff({'retime':{'version':1},'fcp_handoff':'editable'},{},root)
