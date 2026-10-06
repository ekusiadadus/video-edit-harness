"""Retained speech inspection uses synthetic timed annotations, not ASR proof."""
from pathlib import Path
import subprocess
import json
import tempfile
import unittest
import shutil
from importlib.util import find_spec

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
                                                '-map','0:a:0','-ac','2','-ar','48000','-f','s16le','-'])
            self.assertEqual(pcm(basis['source']['path']),pcm(Path(rendered['path'])/'speech-base.wav'))
            operation={'id':'hold','kind':'freeze','source_frame':20,'output_frames':6,'reason':'Synthetic hold'}
            with self.assertRaisesRegex(ValueError,'observed nonspoken'):
                session.propose_retime(rendered['id'],{'operations':[operation]},'automation','Ungated interval')
            with self.assertRaisesRegex(ValueError,'retained word'):
                session.propose_retime(rendered['id'],{'operations':[operation],
                    'nonspoken_intervals':[{'first_frame':6,'end_frame_exclusive':21,'reason':'Incorrect observation'}]},
                    'automation','Reject words inside nonspoken observation')
            proposal=session.propose_retime(rendered['id'],{'operations':[operation],
                'nonspoken_intervals':[{'first_frame':20,'end_frame_exclusive':21,'reason':'Synthetic nonspoken frame'}]},
                'automation','Synthetic fixture timing only')
            candidate=proposal['candidate']
            self.assertFalse(proposal['adopted'])
            full=session.render(preview=False,actor='automation',candidate_id=candidate['id'])
            preview=session.render(preview=True,actor='automation',candidate_id=candidate['id'])
            for item in (full,preview):
                folder=Path(item['path']);mapping=read(folder/'frame-mapping.json')
                self.assertEqual(mapping['frame_count'],66)
                self.assertEqual(mapping['duration'],2.2)
                self.assertEqual(mapping['retime']['frames'][42]['source_frame'],36)
                self.assertIn('00:00:01,400', (folder/'subtitles.srt').read_text())
                original=pcm(folder/'speech-base.wav');changed=pcm(folder/'speech-retimed.wav')
                # Stereo s16 PCM, 1600 samples per frame; both retained words remain exact.
                stride=1600*4
                self.assertEqual(changed[6*stride:15*stride],original[6*stride:15*stride])
                self.assertEqual(changed[42*stride:51*stride],original[36*stride:45*stride])
                self.assertEqual(read(folder/'speech-assembly.json')['source']['sha256'],basis['source']['sha256'])
                self.assertTrue((folder/'original-cut-reference.fcpxml').is_file())
                self.assertTrue((folder/'production-timeline.fcpxml').is_file())
                self.assertEqual(session.retime_source(item['id'])['word_protection']['frame_count'],60)
                from video_harness.feedback import map_output
                point=map_output(mapping,1.4)
                self.assertEqual(point['frame_correspondence'][0]['source_frame'],36)
                self.assertAlmostEqual(point['source_spans'][0]['source_start'],1.2)
            if shutil.which('rubberband') and find_spec('soundfile'):
                ramp={'id':'fast','kind':'ramp','source_first_frame':22,'source_end_frame_exclusive':30,
                      'speed_start':2,'speed_end':2,'reason':'Synthetic nonspoken movement'}
                fast=session.propose_retime(rendered['id'],{'operations':[ramp],
                    'nonspoken_intervals':[{'first_frame':22,'end_frame_exclusive':30,'reason':'Synthetic nonspoken frames'}]},
                    'automation','Synthetic speed candidate')
                result=session.render(preview=False,actor='automation',candidate_id=fast['candidate']['id'])
                folder=Path(result['path']);mapping=read(folder/'frame-mapping.json')
                self.assertEqual(mapping['frame_count'],56)
                self.assertEqual(mapping['retime']['frames'][32]['source_frame'],36)
                self.assertEqual(pcm(folder/'speech-retimed.wav')[32*stride:41*stride],
                                 pcm(folder/'speech-base.wav')[36*stride:45*stride])
                effect=session.propose_effects(result['id'],[{'action':'add','event':{
                    'id':'focus','type':'smooth_zoom','output_start':'0','output_end':'1',
                    'strength':.4,'reason':'Synthetic retime finishing test','parameters':{'anchor_x':.5}}}],
                    'automation','Apply effect after synthetic retime')
                finished=session.render(preview=False,actor='automation',candidate_id=effect['id'])
                finished_folder=Path(finished['path'])
                audio_info=json.loads(subprocess.check_output(['ffprobe','-v','error','-show_streams',
                    '-of','json',str(finished_folder/'video.mp4')]))
                sound=next(s for s in audio_info['streams'] if s['codec_type']=='audio')
                from fractions import Fraction
                self.assertEqual(Fraction(sound['duration_ts'])*Fraction(sound['time_base']),Fraction(56,30))
                self.assertEqual(pcm(folder/'video.mp4'),pcm(finished_folder/'video.mp4'))
                self.assertEqual(len(pcm(finished_folder/'final-mix.wav')),89600*4)
                self.assertEqual(pcm(finished_folder/'final-mix.wav'),pcm(finished_folder/'video.mp4')[:89600*4])
            natural=session.create_candidate({'editing_pattern':{'id':'natural'}},'automation','Synthetic timing baseline')
            baseline=session.render(preview=False,actor='automation',candidate_id=natural['id'])
            compared=session.compare_candidates([baseline['id'],full['id']],mode='timing')
            self.assertEqual(read(compared['evidence']['path'])['mode'],'timing')
            self.assertEqual(session._load()['project'],initial)
            self.assertEqual(session._load()['project'],initial)
            with Path(basis['source']['path']).open('ab') as stream:
                stream.write(b'tampered')
            with self.assertRaisesRegex(ValueError,'Rendered evidence changed'):
                session.retime_source(rendered['id'])


if __name__=='__main__':
    unittest.main()
