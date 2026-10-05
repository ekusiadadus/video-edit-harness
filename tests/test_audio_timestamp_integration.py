"""Real FFmpeg regression for internal AAC timestamp gaps; no ASR or cloud service."""
import shutil
import tempfile
import unittest
import wave
from pathlib import Path
from video_harness.common import fingerprint, probe, run, read
from video_harness.editorial import make_brief, build_story_plan, approve_story
from video_harness.editing import render_edit


@unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'FFmpeg integration tools unavailable')
class AudioTimestampIntegrationTests(unittest.TestCase):
    def test_internal_audio_gap_preserves_video_timeline(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);source=root/'source.mp4'
            run(['ffmpeg','-v','error','-nostdin','-n','-f','lavfi','-i','testsrc2=s=160x90:r=30:d=4',
                 '-f','lavfi','-i','sine=frequency=440:sample_rate=48000:duration=4',
                 '-af',"aselect='not(between(t,1,1.25))'",'-c:v','libx264','-preset','ultrafast',
                 '-threads','2','-pix_fmt','yuv420p','-color_primaries','bt709','-color_trc','bt709',
                 '-colorspace','bt709','-c:a','aac',str(source)],root/'source.log')
            cfg={'name':'Gap regression','source':str(source),'input_color':'rec709',
                 'use_case':'indoor_talk','style':'natural','audio':{'normalize':False,'target_lufs':-16,'true_peak_db':-1.5,'loudness_range':7},
                 'editorial':{'goal':'Keep source timing'},'render_cache_root':str(root/'cache')}
            transcript={'version':1,'source':fingerprint(source),'duration':4.,
                        'words':[{'id':1,'start':.1,'end':.4,'text':'Start','probability':0},
                                 {'id':2,'start':3.6,'end':3.9,'text':'End','probability':0}],
                        'segments':[{'id':1,'start':.1,'end':3.9,'text':'Start End'}]}
            spec={'chapters':[{'id':'all','title':'Timing','goal_ids':['goal-1'],'spans':[
                  {'id':'all','start_word_id':1,'end_word_id':2,'pad_before':.1,'pad_after':.1,'reason':'Keep full timeline'}]}],'omissions':[]}
            plan=approve_story(build_story_plan(cfg,transcript,make_brief(cfg),spec),'automation','Synthetic timestamp regression only')
            out=root/'render'
            render_edit(cfg,plan,out,preview=False)
            with wave.open(str(out/'segments/0000.wav'),'rb') as audio:
                self.assertAlmostEqual(audio.getnframes()/audio.getframerate(),4.,places=3)
            data=read(out/'verification.json')
            self.assertAlmostEqual(data['audio_range'][1],4.,delta=.03)
            self.assertEqual(read(out/'result.json')['technical_status'],'pass')

if __name__=='__main__':
    unittest.main()
