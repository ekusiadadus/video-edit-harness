"""Retained speech inspection uses synthetic timed annotations, not ASR proof."""
from pathlib import Path
import subprocess
import json
import tempfile
import unittest

from video_harness.common import fingerprint, read, write
from video_harness.edl import build_plan
from video_harness.session import Session
from video_harness.transcript import save_transcript


class SpeechRetimeSourceTests(unittest.TestCase):
    def test_session_retains_preproduction_audio_and_observed_word_protection(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);source=root/'source.mp4'
            subprocess.run(['ffmpeg','-v','error','-nostdin','-n','-f','lavfi','-i',
                            'color=c=gray:s=128x128:r=30:d=2','-f','lavfi','-i',
                            'sine=frequency=440:sample_rate=48000:duration=2',
                            '-c:v','libx264','-pix_fmt','yuv420p','-c:a','aac',str(source)],check=True)
            cfg={'name':'Synthetic timed annotations','source':str(source),'input_color':'rec709',
                 'evidence_kind':'synthetic','audio':{'target_lufs':-16,'true_peak_db':-1.5,'loudness_range':11},'editing_pattern':{'id':'playful_short','music':'off',
                 'sfx':'off','visual_assets':'off','beat_sync':'off'}}
            project=root/'project.json';write(project,cfg)
            transcript={'version':1,'source':fingerprint(source),'duration':2.,'language':'en',
                        'backend':{'name':'openai','sdk_version':'synthetic_fixture','settings':{'evidence_kind':'synthetic'}},
                        'words':[{'id':'w1','start':.2,'end':.5,'text':'First','probability':1.},
                                 {'id':'w2','start':1.2,'end':1.5,'text':'Last','probability':1.}],
                        'segments':[],'semantic_text':'First Last','warnings':[]}
            transcript_path=save_transcript(root/'transcript',transcript)
            session=Session.start(project,root/'session');session.attach_transcript(transcript_path,actor='automation')
            plan=build_plan(cfg,read(transcript_path),[]);plan_path=root/'plan.json';write(plan_path,plan)
            session.propose(plan_path=plan_path,actor='automation');session.approve('automation','Synthetic selection only')
            rendered=session.render(preview=False,actor='automation');initial=session._load()['project']
            basis=session.retime_source(rendered['id'])
            self.assertEqual(basis['stage'],'pre_production_speech_assembly')
            self.assertEqual(basis['word_protection']['protected_intervals'],[[6,15],[36,45]])
            self.assertEqual([w['word_id'] for w in basis['word_protection']['word_occurrences']],['w1','w2'])
            self.assertEqual(basis['word_protection']['frame_count'],60)
            self.assertEqual(session._load()['project'],initial)
            info=read(Path(rendered['path'])/'speech-assembly.json')
            self.assertEqual(info['source'],basis['source'])
            stream=json.loads(subprocess.check_output(['ffprobe','-v','error','-show_streams','-of','json',basis['source']['path']]))
            audio=next(s for s in stream['streams'] if s['codec_type']=='audio')
            self.assertEqual(audio['codec_name'],'pcm_s16le')
            self.assertEqual(audio['sample_rate'],'48000')
            def pcm(path):
                return subprocess.check_output(['ffmpeg','-v','error','-i',str(path),
                                                '-map','0:a:0','-f','s16le','-'])
            self.assertEqual(pcm(basis['source']['path']),pcm(Path(rendered['path'])/'speech-base.wav'))
            with self.assertRaisesRegex(ValueError,'not integrated'):
                session.propose_retime(rendered['id'],{'operations':[]},'automation','No unsupported candidate')
            self.assertEqual(session._load()['project'],initial)
            with Path(basis['source']['path']).open('ab') as stream:
                stream.write(b'tampered')
            with self.assertRaisesRegex(ValueError,'Rendered evidence changed'):
                session.retime_source(rendered['id'])


if __name__=='__main__':
    unittest.main()
