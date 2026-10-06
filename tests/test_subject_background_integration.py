"""Actual GrabCut foreground pixels and finished compositing; not human quality review."""
from fractions import Fraction
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
import numpy as np
from video_harness.common import fingerprint,write
from video_harness.subject_mask import prepare_masks,validate_masks
from video_harness.video_effects import resolve_effects,render_effects,_digest
from tests.test_video_effects import pcm_hash

class SubjectBackgroundIntegrationTests(unittest.TestCase):
    def test_real_masks_preserve_foreground_and_reject_stale_png(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);source=root/'subject.mp4'
            frames=[];boxes=[]
            for index in range(10):
                picture=np.zeros((128,128,3),np.uint8);picture[:]=[100,180,120]
                picture[28:100,40+index*2:65+index*2]=255
                frames.append(picture);boxes.append([(30+index*2)/128,20/128,(75+index*2)/128,108/128])
            subprocess.run(['ffmpeg','-v','error','-n','-f','rawvideo','-pixel_format','rgb24',
                '-video_size','128x128','-framerate','30','-i','pipe:0','-f','lavfi','-i',
                'sine=frequency=440:sample_rate=48000:duration=0.333333333',
                '-c:v','libx264','-crf','0','-pix_fmt','yuv420p','-c:a','aac',str(source)],
                input=b''.join(frame.tobytes() for frame in frames),check=True,capture_output=True)
            identity=fingerprint(source)
            track={'version':1,'algorithm':'lk-affine-v1','engine_version':'synthetic-manual-rows',
                'source':{key:identity[key] for key in ('path','sha256','bytes')},'fps':'30',
                'start_frame':2,'end_frame_exclusive':8,'review_required':True,
                'rows':[{'frame':index,'box':boxes[index],'state':'manual','quality':{'feature_count':10}} for index in range(2,8)]}
            track_path=root/'track.json';write(track_path,track)
            masks=root/'masks';doc=prepare_masks(source,track_path,masks,'automation','Synthetic subject separation')
            self.assertEqual(len(doc['rows']),6)
            self.assertTrue(all(row['stats']['foreground_pixels']>0 for row in doc['rows']))
            mapping={'fps':'30','duration':'1/3','sequence':[{'output_start':'0'}]}
            event={'id':'background','type':'tracked_background','output_start':'1/15','output_end':'4/15',
                   'strength':1,'reason':'Synthetic foreground preservation',
                   'parameters':{'mask_path':str(masks/'manifest.json'),'background_dim':.6,
                                 'background_saturation':.3,'feather_pixels':0}}
            plan=resolve_effects({'version':1,'mapping_sha256':_digest(mapping),'events':[event]},mapping)
            output=root/'edited.mp4'
            try:
                evidence=render_effects(source,plan,output)
            except Exception:
                log=output.with_suffix('.effects.log')
                if log.exists():
                    Path('output/implementation-maya/subject-background-ffmpeg-error.log').write_text(log.read_text())
                raise
            self.assertEqual(evidence['frame_count'],10)
            self.assertEqual(pcm_hash(source),pcm_hash(output))
            raw=subprocess.check_output(['ffmpeg','-v','error','-i',str(output),'-map','0:v',
                                         '-f','rawvideo','-pix_fmt','rgb24','-'])
            pixels=np.frombuffer(raw,np.uint8).reshape(10,128,128,3)
            self.assertGreater(float(pixels[4,60:70,50:60].mean()),245)
            self.assertLess(float(pixels[4,5:15,5:15].mean()),100)
            for index in range(2,8):
                self.assertLess(float(pixels[index,5:15,5:15].mean()),100)
            for index in (1,8):
                self.assertGreater(float(pixels[index,5:15,5:15].mean()),125)
            self.assertGreater(float(pixels[0,5:15,5:15].mean()),125)
            self.assertGreater(float(pixels[9,5:15,5:15].mean()),125)
            self.assertEqual(evidence['subject_masks'][0]['frames'],6)
            subset={**event,'output_start':'2/15','output_end':'1/5'}
            subset_plan=resolve_effects({'version':1,'mapping_sha256':_digest(mapping),'events':[subset]},mapping)
            subset_output=root/'subset.mp4';render_effects(source,subset_plan,subset_output)
            subset_raw=subprocess.check_output(['ffmpeg','-v','error','-i',str(subset_output),'-map','0:v','-f','rawvideo','-pix_fmt','rgb24','-'])
            subset_pixels=np.frombuffer(subset_raw,np.uint8).reshape(10,128,128,3)
            for index in range(10):
                background=float(subset_pixels[index,5:15,5:15].mean())
                self.assertLess(background,100) if index in (4,5) else self.assertGreater(background,125)
            self.assertGreater(float(subset_pixels[4,60:70,50:60].mean()),245)
            overlap={**event,'id':'zoom','type':'smooth_zoom','parameters':{}}
            overlap_plan=resolve_effects({'version':1,'mapping_sha256':_digest(mapping),'events':[event,overlap]},mapping)
            with self.assertRaisesRegex(ValueError,'cannot overlap geometry'):
                render_effects(source,overlap_plan,root/'overlap.mp4')
            # A valid replacement image without a matching recorded hash is stale.
            first=Path(doc['rows'][0]['mask_path']);first.write_bytes(Path(doc['rows'][1]['mask_path']).read_bytes())
            with self.assertRaisesRegex(ValueError,'Mask PNG changed'):
                validate_masks(masks/'manifest.json')
            with self.assertRaisesRegex(ValueError,'Mask PNG changed'):
                render_effects(source,plan,root/'stale.mp4')
