"""Session retime is a candidate, not human approval or editable FCP timing."""
from pathlib import Path
import tempfile
import unittest

from tests import test_visual_editing as helpers
from video_harness.common import write,read
from video_harness.session import Session


class SessionRetimeTests(unittest.TestCase):
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
            self.assertEqual(Path(session.tracking_source(rendered['id'])['source']['path']).name,'visual-retimed.mp4')
            self.assertEqual(session._load()['project'],before)
            self.assertTrue((Path(rendered['path'])/'original-cut-reference.fcpxml').is_file())

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
