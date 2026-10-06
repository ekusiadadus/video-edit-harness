"""Actual causal trail pixels and audio preservation, not aesthetic acceptance."""
from fractions import Fraction
import copy
from pathlib import Path
import subprocess
import tempfile
import unittest
import numpy as np
from video_harness.video_effects import resolve_effects,render_effects
from video_harness.effect_catalog import validate_parameters
from tests.test_video_effects import digest,pcm_hash

class MotionTrailIntegrationTests(unittest.TestCase):
    def test_schema_cut_and_overlap_guards(self):
        mapping={'fps':'30','duration':'1','sequence':[{'output_start':'0'},{'output_start':'1/2'}]}
        event={'id':'trail','type':'motion_trail','output_start':'1/5','output_end':'4/5',
               'strength':.6,'reason':'Observed movement accent','parameters':{}}
        def resolve(events):
            return resolve_effects({'version':1,'mapping_sha256':digest(mapping),'events':events},mapping)
        with self.assertRaisesRegex(ValueError,'cross a mapped cut'):
            resolve([event])
        event['output_end']='2/5'
        self.assertEqual(resolve([event])['events'][0]['parameters'],{'history_frames':3,'decay':.3})
        with self.assertRaisesRegex(ValueError,'cannot overlap'):
            resolve([event,{**event,'id':'second'}])
        for value in (True,1,5,2.0):
            with self.assertRaisesRegex(ValueError,'integer'):
                validate_parameters('motion_trail',{'history_frames':value})
        two={**event,'output_end':'4/15','parameters':{'history_frames':2}}
        self.assertEqual(resolve([two])['events'][0]['parameters']['history_frames'],2)
        tiny={**event,'output_end':'7/30','parameters':{'history_frames':4}}
        with self.assertRaises(ValueError):
            resolve([tiny])

    def test_decoded_trail_uses_only_past_event_frames_and_copies_audio(self):
        for rate in (Fraction(30),Fraction(30000,1001)):
            with tempfile.TemporaryDirectory() as temp:
                root=Path(temp);source=root/'bars.mp4';target=root/'trail.mp4'
                pictures=[]
                for index in range(12):
                    picture=np.zeros((64,128,3),dtype=np.uint8)
                    picture[:,index*8:index*8+8,:]=255
                    pictures.append(picture)
                subprocess.run(['ffmpeg','-v','error','-n','-f','rawvideo','-pixel_format','rgb24',
                    '-video_size','128x64','-framerate',str(rate),'-i','pipe:0','-f','lavfi','-i',
                    f'sine=frequency=440:sample_rate=48000:duration={float(Fraction(12,1)/rate)}','-c:v','libx264','-crf','0',
                    '-pix_fmt','yuv420p','-c:a','aac',str(source)],
                    input=b''.join(p.tobytes() for p in pictures),check=True,capture_output=True)
                mapping={'fps':str(rate),'duration':str(Fraction(12,1)/rate),'sequence':[{'output_start':'0'}]}
                event={'id':'accent','type':'motion_trail','output_start':str(Fraction(3,1)/rate),'output_end':str(Fraction(9,1)/rate),
                       'strength':1,'reason':'Synthetic moving bar','parameters':{'history_frames':3,'decay':.4}}
                plan=resolve_effects({'version':1,'mapping_sha256':digest(mapping),'events':[event]},mapping)
                overlapping=copy.deepcopy(plan)
                overlapping['events'].append({**overlapping['events'][0],'id':'duplicate-window'})
                with self.assertRaisesRegex(ValueError,'cannot overlap'):
                    render_effects(source,overlapping,root/'invalid.mp4')
                report=render_effects(source,plan,target)
                self.assertEqual(report['frame_count'],12)
                self.assertEqual(pcm_hash(source),pcm_hash(target))
                raw=subprocess.check_output(['ffmpeg','-v','error','-i',str(target),'-map','0:v',
                                             '-f','rawvideo','-pix_fmt','rgb24','-'])
                frames=np.frombuffer(raw,dtype=np.uint8).reshape(12,64,128,3)
                # At frame5 actual current bar40..47, older bars32..39 and24..31; no future bar48.
                self.assertGreater(float(frames[5,:,40:48].mean()),float(frames[5,:,32:40].mean()))
                self.assertGreater(float(frames[5,:,32:40].mean()),20)
                self.assertGreater(float(frames[5,:,24:32].mean()),5)
                self.assertLess(float(frames[5,:,48:56].mean()),3)
                # Window starts at3: preceding event-external bar16 is never retained.
                self.assertLess(float(frames[3,:,16:24].mean()),3)
                self.assertGreater(float(frames[3,:,24:32].mean()),240)
                # Frame9 is beyond trail window and shows no old bar64.
                self.assertLess(float(frames[9,:,64:72].mean()),3)
                self.assertGreater(float(frames[9,:,72:80].mean()),240)
                self.assertEqual(len(report['temporal_inputs']),1)

    def test_session_request_reaches_actual_render_without_adoption(self):
        from tests.test_visual_editing import VisualEditingTests
        from video_harness.common import write,read
        from video_harness.session import Session
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);cfg,plan=VisualEditingTests().fixture(root,source_audio=True)
            cfg.update(edit_basis='visual',fcp_handoff='video_only',
                       editing_pattern={'id':'playful_short','music':'off','sfx':'off','beat_sync':'off','visual_assets':'licensed'})
            project=root/'project.json';write(project,cfg)
            session=Session.start(project,root/'session')
            session.propose_visual(plan,'automation');session.approve('automation','Synthetic source intervals')
            base=session.render(preview=False,actor='automation')
            previous=session._load()['project']
            event={'id':'trail','type':'motion_trail','output_start':'0','output_end':'3/10',
                   'strength':.5,'reason':'Synthetic isolated window','parameters':{}}
            candidate=session.propose_effects(base['id'],[{'action':'add','event':event}],
                                             'automation','Synthetic effect request')
            result=session.render(preview=False,actor='automation',candidate_id=candidate['id'])
            evidence=read(Path(result['path'])/'effects-evidence.json')
            self.assertEqual(evidence['temporal_inputs'][0]['event_id'],'trail')
            self.assertEqual(evidence['temporal_inputs'][0]['window_end_frame_exclusive'],3)
            self.assertEqual(read(result['files']['mapping']['path']),read(base['files']['mapping']['path']))
            self.assertEqual(session._load()['project'],previous)
            self.assertEqual(session._load()['reviews'],[])
