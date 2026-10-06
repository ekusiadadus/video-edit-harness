"""Actual ROI motion and source-bound proposed frame changes; no human review."""
from copy import deepcopy
from pathlib import Path
from unittest import TestCase
import tempfile, subprocess
import numpy as np
from tests import test_visual_editing as helpers
from video_harness.assets import register_asset
from video_harness.common import write,read
from video_harness.session import Session
from video_harness.visual import revise_visual_edl
from video_harness.motion_cuts import prepare_motion_cut
from video_harness.workflow_cli import parser

class MotionCutTests(TestCase):
    def fixture(self,root):
        cfg,_=helpers.VisualEditingTests().fixture(root,source_audio=False)
        rng=np.random.default_rng(4);texture=rng.integers(0,256,(44,36,3),dtype=np.uint8)
        source=root/'moving.mp4';pictures=[]
        for i in range(20):
            picture=np.zeros((128,128,3),np.uint8)
            # Early frames move left; after frame six the same object moves right.
            x=35-i*2 if i<6 else 24+(i-6)*2
            picture[40:84,x:x+36]=texture;pictures.append(picture)
        subprocess.run(['ffmpeg','-v','error','-f','rawvideo','-pix_fmt','rgb24','-s','128x128',
                        '-r','10','-i','pipe:0','-c:v','libx264','-crf','0','-pix_fmt','yuv420p',str(source)],
                        input=b''.join(f.tobytes() for f in pictures),check=True,capture_output=True)
        old=cfg['assets'][0];metadata={k:old[k] for k in ('asset_id','kind','creator','source_url','license_url',
            'acquired_on','verified_on','evidence_path','credit','rights','cost','currency','content_id')}
        cfg.update(source=str(source),edit_basis='visual',fcp_handoff='video_only',
                   assets=[register_asset(source,metadata)],editing_pattern={'id':'natural'})
        plan={'version':4,'edit_basis':'visual','status':'proposed','sequence':[
            {'id':'left','asset_id':old['asset_id'],'source_start':'0','source_end':'1','reason':'Synthetic first action'},
            {'id':'right','asset_id':old['asset_id'],'source_start':'1','source_end':'2','reason':'Synthetic next action'}]}
        request={'version':1,'left_segment_id':'left','window_frames':4,'left_box':[.1,.25,.9,.8],
                 'right_box':[.1,.25,.9,.8],
                 'choices':[{'left_end_frame':5,'right_start_frame':10,'reason':'Compare opposite movement'},
                            {'left_end_frame':11,'right_start_frame':11,'reason':'Compare rightward motion'}],
                 'nonspoken_intervals':[{'asset_id':old['asset_id'],'first_frame':0,'end_frame_exclusive':20,
                                        'reason':'Synthetic silent source'}]}
        return cfg,plan,request

    def test_actual_motion_changes_source_frames_only_after_selection(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);cfg,plan,request=self.fixture(root)
            project=root/'project.json';write(project,cfg)
            session=Session.start(project,root/'session');session.propose_visual(plan,'automation')
            session.approve('automation','Synthetic source frames selected')
            base=session.render(preview=False,actor='automation');before=session._load()
            result=session.propose_motion_cut(base['id'],request,'automation','Compare actual rightward motion')
            doc=read(result['report']['path']);self.assertFalse(doc['adopted']);self.assertFalse(doc['transition_rendered'])
            self.assertEqual(doc['candidates'][0]['match']['classification'],'incompatible')
            self.assertEqual(doc['selected']['choice']['left_end_frame'],11)
            proposed=read(result['plan']['path']);self.assertEqual(proposed['status'],'proposed')
            self.assertNotIn('review',proposed);self.assertEqual(session._load()['reviews'],before['reviews'])
            self.assertEqual(proposed['sequence'][0]['source_end_frame_exclusive'],11)
            self.assertEqual(proposed['sequence'][1]['source_first_frame'],11)
            revised_sequence=deepcopy(proposed['sequence']);revised_sequence[0]['source_end']='1'
            for key in ('source_fps','source_first_frame','source_end_frame_exclusive'):
                revised_sequence[0].pop(key,None)
            manual=revise_visual_edl(proposed,revised_sequence,actor='automation',reason='Change synthetic endpoint')
            self.assertNotIn('motion_proposal',manual)
            stale={**manual,'motion_proposal':proposed['motion_proposal']}
            with self.assertRaisesRegex(ValueError,'current source frames'):
                Session._validate_edit_plan(stale,cfg)
            with self.assertRaises(ValueError):session.render(preview=False,actor='automation')
            session.approve('automation','Synthetic direction choice selected; not human acceptance')
            revised=session.render(preview=False,actor='automation')
            mapping=read(revised['files']['mapping']['path'])
            self.assertEqual(mapping['sequence'][0]['source_frame_map'][-1],10)
            self.assertEqual(mapping['sequence'][1]['source_frame_map'][0],11)
            with self.assertRaisesRegex(ValueError,'current'):
                session.propose_motion_cut(base['id'],request,'automation','Stale render')
            Path(result['report']['path']).write_text('{}')
            with self.assertRaisesRegex(ValueError,'artifact changed'):session._verify(session._load())

    def test_permissions_handles_and_cli(self):
        with tempfile.TemporaryDirectory() as folder:
            cfg,plan,request=self.fixture(Path(folder))
            for le,rs in ((5,10),(11,10),(10,9),(10,11)):
                missing={**request,'nonspoken_intervals':[],
                         'choices':[{'left_end_frame':le,'right_start_frame':rs,'reason':'Permission guard'}]}
                with self.subTest(endpoints=(le,rs)), self.assertRaisesRegex(ValueError,'nonspoken'):
                    prepare_motion_cut(plan,cfg,missing,'automation','Reject undeclared changes')
            bad={**request,'choices':[{'left_end_frame':30,'right_start_frame':11,'reason':'Outside source'}]}
            with self.assertRaisesRegex(ValueError,'handles'):
                prepare_motion_cut(plan,cfg,bad,'automation','Reject unavailable frames')
            with self.assertRaisesRegex(ValueError,'without retime'):
                prepare_motion_cut(plan,{**cfg,'retime':{} or {'version':1}},request,'automation','No retime reuse')
            unchanged={**request,'choices':[{'left_end_frame':10,'right_start_frame':10,'reason':'Same source boundary'}]}
            selected,report=prepare_motion_cut(plan,cfg,unchanged,'automation','Keep same boundary')
            self.assertIsNone(selected);self.assertFalse(report['adopted'])
            source=Path(cfg['source']);data=source.read_bytes();source.write_bytes(data[:-1]+bytes([data[-1]^1]))
            with self.assertRaises(ValueError):
                prepare_motion_cut(plan,cfg,request,'automation','Reject replaced source bytes')
        args=parser().parse_args(['motion-cuts','/tmp/session','r1','--request-file','/tmp/request.json','--note','Observed'])
        self.assertEqual(args.actor,'codex')
