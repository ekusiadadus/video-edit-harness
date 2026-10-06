"""A synthetic pose/box fixture is not a human tracking review."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tests import test_visual_editing as fixture_helpers
from video_harness.common import write,read,fingerprint
from video_harness.session import Session


class SessionTrackingTests(unittest.TestCase):
    def test_actual_effect_stage_survives_candidate_render_and_remains_unadopted(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);cfg,plan=fixture_helpers.VisualEditingTests().fixture(root,source_audio=False)
            cfg['edit_basis']='visual';cfg['editing_pattern']={'id':'playful_short','music':'off','sfx':'off','beat_sync':'off','visual_assets':'own_only'}
            project=root/'project.json';write(project,cfg)
            session=Session.start(project,root/'session')
            session.propose_visual(plan,'codex');session.approve('codex','Synthetic frame selection')
            base=session.render(preview=False);initial=session._load()['project']
            observed=session.tracking_source(base['id'])
            self.assertEqual(Path(observed['source']['path']).name,'visual-graded.mp4')
            def synthetic_track(source,box,output,**kwargs):
                ref=fingerprint(source)
                rows=[{'frame':i,'box':box,'state':'manual','quality':{'feature_count':10}} for i in range(kwargs['start_frame'],kwargs['end_frame'])]
                doc={'version':1,'algorithm':'lk-affine-v1','source':ref,'fps':'10','start_frame':kwargs['start_frame'],'end_frame_exclusive':kwargs['end_frame'],'rows':rows,'review_required':True}
                write(output,doc);return doc
            with patch('video_harness.tracking.track_video',side_effect=synthetic_track):
                proposed=session.propose_tracking(base['id'],[.1,.1,.5,.7],0,8,'codex','Synthetic box test',algorithm='lk')
            self.assertFalse(proposed['adopted'])
            self.assertEqual(session._load()['project'],initial)
            rendered=session.render(preview=False,candidate_id=proposed['candidate']['id'])
            evidence=read(Path(rendered['path'])/'effects-evidence.json')
            self.assertEqual(evidence['tracking_inputs'][0]['source_sha256'],observed['source']['sha256'])
            self.assertEqual(evidence['frame_count'],8)
            checks=evidence['composition']['checks']
            self.assertEqual(checks[0]['frames_checked'],8)
            self.assertEqual(checks[0]['status'],'no_detected_conflict')
            self.assertEqual(session._load()['project'],initial)

    def test_tracked_label_candidate_renders_and_remains_unadopted(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);cfg,plan=fixture_helpers.VisualEditingTests().fixture(root,source_audio=False)
            cfg['edit_basis']='visual';cfg['editing_pattern']={'id':'playful_short','music':'off','sfx':'off','beat_sync':'off','visual_assets':'own_only'}
            project=root/'project.json';write(project,cfg)
            session=Session.start(project,root/'session')
            session.propose_visual(plan,'codex');session.approve('codex','Synthetic frame selection')
            base=session.render(preview=False);initial=session._load()['project']
            observed=session.tracking_source(base['id'])
            self.assertEqual(Path(observed['source']['path']).name,'visual-graded.mp4')
            def synthetic_track(source,box,output,**kwargs):
                ref=fingerprint(source)
                rows=[{'frame':i,'box':box,'state':'manual','quality':{'feature_count':10}} for i in range(kwargs['start_frame'],kwargs['end_frame'])]
                doc={'version':1,'algorithm':'lk-affine-v1','source':ref,'fps':'10','start_frame':kwargs['start_frame'],'end_frame_exclusive':kwargs['end_frame'],'rows':rows,'review_required':True}
                write(output,doc);return doc
            with patch('video_harness.tracking.track_video',side_effect=synthetic_track):
                proposed=session.propose_tracking(base['id'],[.3,.6,.6,.8],0,8,'codex','Synthetic label test',algorithm='lk',
                    effect='tracked_title',title_parameters={'text':'A','placement':'above'})
            self.assertFalse(proposed['adopted'])
            self.assertEqual(session._load()['project'],initial)
            rendered=session.render(preview=False,candidate_id=proposed['candidate']['id'])
            evidence=read(Path(rendered['path'])/'effects-evidence.json')
            self.assertEqual(evidence['tracking_inputs'][0]['source_sha256'],observed['source']['sha256'])
            self.assertEqual(evidence['frame_count'],8)
            self.assertEqual(evidence['events'][0]['type'],'tracked_title')
            self.assertEqual(len(evidence['text_assets'][0]['frame_positions']),8)
            checks=evidence['composition']['checks']
            self.assertEqual(checks[0]['frames_checked'],8)
            self.assertEqual(checks[0]['status'],'no_detected_conflict')
            self.assertEqual(session._load()['project'],initial)

    def test_wrapped_tracked_label_preflight_rejects_overflow_before_tracking(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);cfg,plan=fixture_helpers.VisualEditingTests().fixture(root,source_audio=False)
            cfg['edit_basis']='visual';cfg['editing_pattern']={'id':'playful_short','music':'off','sfx':'off','beat_sync':'off','visual_assets':'own_only'}
            project=root/'project.json';write(project,cfg)
            session=Session.start(project,root/'session')
            session.propose_visual(plan,'codex');session.approve('codex','Synthetic frame selection')
            base=session.render(preview=False);initial=session._load()['project']
            observed=session.tracking_source(base['id'])
            self.assertEqual(Path(observed['source']['path']).name,'visual-graded.mp4')
            with patch('video_harness.tracking.track_video') as tracker:
                for params in ({'text':'unbreakableword', 'language':'en', 'max_width_fraction':.2, 'font_size_fraction':.12},
                               {'text':'A', 'language':'en', 'motion':'rise'},
                               {'text':'A', 'language':'en', 'placement':'invalid'}):
                    with self.subTest(params=params), self.assertRaises(ValueError):
                        session.propose_tracking(base['id'],[.3,.6,.6,.8],0,8,'codex','Invalid title preflight',
                            effect='tracked_title',title_version=2,title_parameters=params)
                tracker.assert_not_called()
            self.assertEqual(session._load()['project'],initial)
            def synthetic_track(source,box,output,**kwargs):
                ref=fingerprint(source)
                rows=[{'frame':i,'box':box,'state':'manual','quality':{'feature_count':10}} for i in range(kwargs['start_frame'],kwargs['end_frame'])]
                doc={'version':1,'algorithm':'lk-affine-v1','source':ref,'fps':'10','start_frame':kwargs['start_frame'],'end_frame_exclusive':kwargs['end_frame'],'rows':rows,'review_required':True}
                write(output,doc);return doc
            with patch('video_harness.tracking.track_video',side_effect=synthetic_track):
                proposed=session.propose_tracking(base['id'],[.3,.6,.6,.8],0,8,'codex','Synthetic label test',algorithm='lk',
                    effect='tracked_title',title_version=2,title_parameters={'text':'Beat sync','language':'en',
                        'font_size_fraction':.1,'max_width_fraction':.4,'placement':'above'})
            self.assertEqual(len(proposed['title_preflight']['rendered_lines']),2)
            self.assertFalse(proposed['adopted'])
            self.assertEqual(session._load()['project'],initial)
            rendered=session.render(preview=False,candidate_id=proposed['candidate']['id'])
            evidence=read(Path(rendered['path'])/'effects-evidence.json')
            self.assertEqual(evidence['tracking_inputs'][0]['source_sha256'],observed['source']['sha256'])
            self.assertEqual(evidence['frame_count'],8)
            self.assertEqual(evidence['events'][0]['type'],'tracked_title')
            self.assertEqual(evidence['events'][0]['effect_version'],2)
            self.assertEqual(evidence['text_assets'][0]['rendered_lines'],proposed['title_preflight']['rendered_lines'])
            self.assertEqual(evidence['text_assets'][0]['png_sha256'],proposed['title_preflight']['png_sha256'])
            self.assertEqual(len(evidence['text_assets'][0]['frame_positions']),8)
            checks=evidence['composition']['checks']
            self.assertEqual(checks[0]['frames_checked'],8)
            self.assertEqual(checks[0]['status'],'no_detected_conflict')
            self.assertEqual(session._load()['project'],initial)

    def test_natural_direction_rejects_tracking_before_analysis(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);cfg,plan=fixture_helpers.VisualEditingTests().fixture(root,source_audio=False)
            cfg['edit_basis']='visual';project=root/'project.json';write(project,cfg)
            session=Session.start(project,root/'session')
            session.propose_visual(plan,'codex');session.approve('codex','Synthetic frame selection')
            base=session.render(preview=False)
            with patch('video_harness.tracking.track_video') as track, self.assertRaisesRegex(ValueError,'natural/off'):
                session.propose_tracking(base['id'],[.1,.1,.5,.7],0,8,'codex','Rejected synthetic proposal')
            track.assert_not_called()


if __name__=='__main__':
    unittest.main()
