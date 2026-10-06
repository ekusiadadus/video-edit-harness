"""Actual decoded label placement and source-bound rejection, not just metadata."""
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

import numpy as np

from video_harness.composition import resolve_guides
from video_harness.video_effects import _digest, resolve_effects, render_effects


class TrackedTitleIntegrationTests(unittest.TestCase):
    def fixture(self, root):
        source=root/'source.mp4'
        subprocess.run(['ffmpeg','-v','error','-nostdin','-y','-f','lavfi','-i',
                        'color=c=gray:s=192x320:r=10:d=1.2','-f','lavfi','-i',
                        'sine=frequency=440:sample_rate=48000:duration=1.2',
                        '-c:v','libx264','-pix_fmt','yuv420p','-c:a','aac','-shortest',str(source)],check=True)
        track=root/'track.json'
        doc={'version':1,'algorithm':'lk-affine-v1',
             'source':{'path':str(source),'sha256':hashlib.sha256(source.read_bytes()).hexdigest(),'bytes':source.stat().st_size},
             'fps':'10','start_frame':0,'end_frame_exclusive':12,'review_required':True,
             'rows':[{'frame':i,'box':[.25+i*.02,.5,.35+i*.02,.7],'state':'manual',
                      'quality':{'feature_count':10}} for i in range(12)]}
        track.write_text(json.dumps(doc))
        mapping={'fps':'10','duration':'6/5','sequence':[]}
        event={'id':'label','type':'tracked_title','output_start':'1/5','output_end':'1',
               'strength':1,'reason':'Observed synthetic motion',
               'parameters':{'text':'BEAT','track_path':str(track),'font_size_fraction':.07,'background':'#000000'}}
        return source,track,doc,mapping,event

    def plan(self,mapping,event):
        return resolve_effects({'version':1,'mapping_sha256':_digest(mapping),'events':[event]},mapping)

    def test_real_picture_follows_each_exact_frame_and_preserves_audio(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);source,track,doc,mapping,event=self.fixture(root)
            guide={'id':'torso','kind':'subject','track_path':str(track),'output_start':'1/5','output_end':'1','reason':'Observed box'}
            output=root/'follow.mp4'
            report=render_effects(source,self.plan(mapping,event),output,composition=resolve_guides([guide],mapping))
            frames=np.frombuffer(subprocess.check_output(['ffmpeg','-v','error','-i',str(output),'-f','rawvideo','-pix_fmt','rgb24','-']),np.uint8).reshape(-1,320,192,3)
            self.assertEqual(len(frames),12)
            positions={r['frame']:r for r in report['text_assets'][0]['frame_positions']}
            # Fully visible frames: the decoded black card must agree with the
            # measured integer placement, including each frame's moving x.
            for frame in range(4,9):
                ys,xs=np.where(np.max(frames[frame],axis=2)<50)
                bounds=positions[frame]['bounds']
                self.assertLessEqual(abs(xs.min()-round(bounds[0]*192)),2)
                self.assertLessEqual(abs(ys.min()-round(bounds[1]*320)),2)
                self.assertLessEqual(abs(xs.max()+1-round(bounds[2]*192)),2)
                self.assertLessEqual(abs(ys.max()+1-round(bounds[3]*320)),2)
            self.assertGreater(positions[8]['x_pixels'],positions[4]['x_pixels'])
            def pcm(path):
                return subprocess.check_output(['ffmpeg','-v','error','-i',str(path),'-map','0:a:0','-f','s16le','-'])
            self.assertEqual(pcm(source),pcm(output))
            self.assertEqual(report['composition']['checks'][0]['frames_checked'],8)
            self.assertEqual(report['tracking_inputs'][0]['source_sha256'],doc['source']['sha256'])

    def test_collision_stale_loss_source_mismatch_and_geometry_reject(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);source,track,doc,mapping,event=self.fixture(root)
            plan=self.plan(mapping,event)
            ui={'id':'ui','kind':'ui','rect':[0,.25,1,.5],'output_start':'1/5','output_end':'1','reason':'Declared interface'}
            target=root/'bad.mp4'
            with self.assertRaisesRegex(ValueError,'intersects protected'):
                render_effects(source,plan,target,composition=resolve_guides([ui],mapping))
            self.assertFalse(target.exists())
            from video_harness.production import resolve_production,verify_production
            cfg={'editing_pattern':{'id':'playful_short','music':'off','sfx':'off','visual_assets':'off'},
                 'video_effects':{'version':1,'mapping_sha256':_digest(mapping),'events':[event]},'assets':[]}
            with self.assertRaisesRegex(ValueError,'disabled visual'):
                resolve_production(cfg,mapping)
            production={'mapping_sha256':plan['mapping_sha256'],'effects':plan,'assets':[],'source_assets':[]}
            track.write_text(track.read_text()+'\n')
            with self.assertRaisesRegex(ValueError,'changed'):
                verify_production(production)
            track.write_text(json.dumps(doc))
            zoom={'id':'zoom','type':'smooth_zoom','output_start':'1/5','output_end':'1','strength':.5,'reason':'Fixture'}
            setting={'version':1,'mapping_sha256':_digest(mapping),'events':[event,zoom]}
            with self.assertRaisesRegex(ValueError,'overlapping'):
                render_effects(source,resolve_effects(setting,mapping),target)
            track.write_text(track.read_text()+'\n')
            with self.assertRaisesRegex(ValueError,'changed'):
                render_effects(source,plan,target)
            doc['rows'][5].update(box=None,state='lost',quality={'feature_count':0,'reason':'Synthetic occlusion'})
            track.write_text(json.dumps(doc))
            with self.assertRaisesRegex(ValueError,'lost'):
                self.plan(mapping,event)
            doc['rows'][5].update(box=[.35,.5,.45,.7],state='manual',quality={'feature_count':10})
            doc['source']['sha256']='a'*64
            track.write_text(json.dumps(doc))
            with self.assertRaisesRegex(ValueError,'different effects input'):
                render_effects(source,self.plan(mapping,event),target)
            self.assertFalse(target.exists())


if __name__=='__main__':
    unittest.main()
