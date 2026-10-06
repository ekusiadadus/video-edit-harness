"""Session candidate path with observed synthetic boxes and actual masks/render."""
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from PIL import Image,ImageDraw
from tests import test_visual_editing as helpers
from video_harness.assets import register_asset
from video_harness.common import read,write,fingerprint
from video_harness.session import Session

class SessionSubjectBackgroundTests(unittest.TestCase):
    def test_candidate_with_manual_mask_and_exact_review_gate(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);cfg,plan=helpers.VisualEditingTests().fixture(root,source_audio=True)
            source=root/'figure.mp4'
            subprocess.run(['ffmpeg','-v','error','-n','-f','lavfi','-i',
                'color=c=green:s=128x128:r=10:d=1,drawbox=x=40:y=28:w=25:h=72:color=white:t=fill',
                '-f','lavfi','-i','sine=frequency=440:sample_rate=48000:duration=1',
                '-c:v','libx264','-pix_fmt','yuv420p','-c:a','aac',str(source)],check=True,capture_output=True)
            old=cfg['assets'][0]
            metadata={key:old[key] for key in ('asset_id','kind','creator','source_url','license_url','acquired_on',
                'verified_on','evidence_path','credit','rights','cost','currency','content_id')}
            cfg.update(source=str(source),edit_basis='visual',fcp_handoff='video_only',
                assets=[register_asset(source,metadata)],
                editing_pattern={'id':'playful_short','music':'off','sfx':'off','beat_sync':'off','visual_assets':'licensed'})
            project=root/'project.json';write(project,cfg)
            session=Session.start(project,root/'session')
            session.propose_visual(plan,'automation');session.approve('automation','Synthetic source cuts')
            base=session.render(preview=False,actor='automation')
            before=session._load()['project']
            # Fully specified manual correction for a known synthetic foreground.
            mask=Image.new('L',(128,128));ImageDraw.Draw(mask).rectangle((40,28,64,99),fill=255)
            correction=root/'manual.png';mask.save(correction)
            def track(source,box,path,**kwargs):
                identity=fingerprint(source)
                write(path,{'version':1,'algorithm':'lk-affine-v1','source':{key:identity[key] for key in ('path','sha256','bytes')},
                    'fps':'10','start_frame':kwargs['start_frame'],'end_frame_exclusive':kwargs['end_frame'],
                    'rows':[{'frame':i,'box':box,'state':'manual','quality':{'feature_count':10}}
                            for i in range(kwargs['start_frame'],kwargs['end_frame'])],'review_required':True})
            with patch('video_harness.tracking.track_video',side_effect=track):
                proposal=session.propose_tracking(base['id'],[.2,.1,.65,.9],0,4,'automation',
                    'Synthetic mask candidate',effect='tracked_background',
                    background_parameters={'feather_pixels':0},mask_corrections={1:str(correction)})
            self.assertFalse(proposal['adopted'])
            doc=read(proposal['subject_mask']['path'])
            self.assertEqual(doc['rows'][1]['origin'],'manual')
            result=session.render(preview=False,actor='automation',candidate_id=proposal['candidate']['id'])
            evidence=read(Path(result['path'])/'effects-evidence.json')
            self.assertEqual(evidence['subject_masks'][0]['frames'],4)
            self.assertEqual(read(result['files']['mapping']['path']),read(base['files']['mapping']['path']))
            self.assertEqual(session._load()['project'],before)
            self.assertEqual(session._load()['reviews'],[])
            with self.assertRaisesRegex(ValueError,'subject_masks'):
                session.review(result['id'],{'render_sha256':result['files']['video']['sha256'],'checks':[]},
                                      'automation')
