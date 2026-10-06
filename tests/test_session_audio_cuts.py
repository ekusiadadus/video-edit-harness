"""Synthetic end-to-end audio handles, not human listening acceptance."""
from pathlib import Path
import subprocess
import tempfile
import unittest
import wave

from tests import test_visual_editing as helpers
from video_harness.assets import register_asset
from video_harness.common import fingerprint, read, write
from video_harness.session import Session
from video_harness.transcript import save_transcript


def pcm(path):
    with wave.open(str(path), 'rb') as stream:
        return stream.getnframes(), stream.getnchannels(), stream.readframes(stream.getnframes())


class SessionAudioCutTests(unittest.TestCase):
    def test_spoken_handle_adds_actual_word_captions_and_inspection_provenance(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);source=root/'annotated.mov'
            subprocess.run(['ffmpeg','-v','error','-n','-f','lavfi','-i','color=c=blue:s=128x128:r=30:d=2',
                '-f','lavfi','-i','aevalsrc=0.1*sin(2*PI*(200+400*t)*t):s=48000:d=2',
                '-c:v','libx264','-pix_fmt','yuv420p','-c:a','pcm_s16le',str(source)],check=True)
            cfg={'name':'Synthetic voiced handle annotations','source':str(source),'input_color':'rec709',
                 'editorial':{'goal':'Synthetic annotated sequence'},
                 'evidence_kind':'synthetic','audio':{'normalize':False,'target_lufs':-16,'true_peak_db':-1.5,'loudness_range':7}}
            project=root/'project.json';write(project,cfg)
            data={'version':1,'source':fingerprint(source),'duration':2.,'language':'en',
                'backend':{'name':'openai','sdk_version':'synthetic_fixture','settings':{}},
                'words':[{'id':'w1','start':.1,'end':.3,'text':'First','probability':1.},
                         {'id':'w2','start':.7,'end':.8,'text':'Lead','probability':1.},
                         {'id':'w3','start':1.1,'end':1.3,'text':'Last','probability':1.}],
                'segments':[],'semantic_text':'First Lead Last','warnings':[]}
            transcript=save_transcript(root/'transcript',data)
            session=Session.start(project,root/'session');session.attach_transcript(transcript,'automation')
            spec={'chapters':[{'id':'story','title':'Synthetic story','goal_ids':['goal-1'],'spans':[
                {'id':'first','start_word_id':'w1','end_word_id':'w1','pad_before':.1,
                 'pad_after':.3,'reason':'Synthetic first interval'},
                {'id':'last','start_word_id':'w3','end_word_id':'w3','pad_before':.1,
                 'pad_after':.3,'reason':'Synthetic last interval'}]}],
                'omissions':[{'word_ids':['w2'],'reason':'Excluded from picture cut','goal_ids':['goal-1']}]}
            session.propose(spec=spec,actor='automation');session.approve('automation','Synthetic picture sequence')
            base=session.render(preview=False,actor='automation')
            event={'id':'voice-lead','kind':'j_cut','before_sequence_id':'last','duration_frames':9,
                   'reason':'Explicitly add known synthetic handle annotation',
                   'handle_observation':'Synthetic annotated source interval contains complete w2',
                   'replacement_observation':'Synthetic replaced interval contains no annotated words',
                   'handle_audio_kind':'speech', 'handle_word_ids':['w2'],'repeat_word_ids':[]}
            proposal=session.propose_audio_cuts(base['id'],{'events':[event]},'automation','Synthetic spoken-handle mapping')
            result=session.render(preview=False,actor='automation',candidate_id=proposal['candidate']['id'])
            compiled=read(result['files']['audio_cuts']['path'])['compiled']
            added=next(word for word in compiled['word_occurrences'] if word['id']=='w2')
            self.assertEqual((added['output_first_sample'],added['output_end_sample']),(14400,19200))
            self.assertEqual(compiled['omitted_word_ids'],[])
            self.assertIn('Lead',Path(result['files']['subtitles']['path']).read_text())
            inspection=read(session.inspect(result['id'],.3,.3)['path'])
            self.assertIn('w2',[word['id'] for word in inspection['words']])
            self.assertEqual(read(result['files']['mapping']['path']),read(base['files']['mapping']['path']))

    def test_j_and_l_cut_use_real_handles_and_keep_picture_mapping(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);cfg,plan=helpers.VisualEditingTests().fixture(root,source_audio=True)
            source=root/'chirp.mov'
            subprocess.run(['ffmpeg','-v','error','-n','-f','lavfi','-i','color=c=blue:s=128x128:r=10:d=2',
                '-f','lavfi','-i','aevalsrc=0.1*sin(2*PI*(200+400*t)*t):s=48000:d=2',
                '-c:v','libx264','-pix_fmt','yuv420p','-c:a','pcm_s16le',str(source)],check=True)
            asset=cfg['assets'][0]
            metadata={key:asset[key] for key in ('asset_id','kind','creator','source_url','license_url',
                'acquired_on','verified_on','evidence_path','credit','rights','cost','currency','content_id')}
            metadata['rights']={**metadata['rights'],'mixed_audio_handoff':True}
            cfg.update(source=str(source),edit_basis='visual',fcp_handoff='mix',assets=[register_asset(source,metadata)])
            plan['sequence'][1].update(source_start=1.,source_end=1.4)
            project=root/'project.json';write(project,cfg)
            session=Session.start(project,root/'session')
            session.propose_visual(plan,'automation');session.approve('automation','Synthetic chirp intervals')
            base=session.render(preview=False,actor='automation')
            original_state=session._load()
            for kind,first,end,source_start,source_end in (
                    ('j_cut',9600,19200,38400,48000),('l_cut',19200,28800,19200,28800)):
                event={'id':kind,'kind':kind,'before_sequence_id':'second','duration_frames':2,
                    'reason':'Synthetic chirp cut validation',
                    'handle_observation':'Synthetic generated chirp source handle, no speech',
                    'replacement_observation':'Synthetic generated chirp replacement interval, no speech',
                    'handle_audio_kind':'nonspoken', 'handle_word_ids':[],'repeat_word_ids':[]}
                proposal=session.propose_audio_cuts(base['id'],{'events':[event]},'automation','Synthetic J/L candidate')
                result=session.render(preview=False,actor='automation',candidate_id=proposal['candidate']['id'])
                folder=Path(result['path'])
                count,channels,after=pcm(folder/'environment.wav')
                original_count,original_channels,before=pcm(folder/'environment-original.wav')
                self.assertEqual((count,channels),(38400,2))
                self.assertEqual((original_count,original_channels),(count,channels))
                stride=channels*2
                self.assertEqual(before[:first*stride],after[:first*stride])
                self.assertEqual(before[end*stride:],after[end*stride:])
                expected=subprocess.check_output(['ffmpeg','-v','error','-i',str(source),'-vn',
                    '-af',f'aresample=48000:async=1:first_pts=0,atrim=start_sample={source_start}:end_sample={source_end},asetpts=N/SR/TB',
                    '-ar','48000','-ac','2','-f','s16le','-'])
                self.assertEqual(after[first*stride:end*stride],expected)
                self.assertNotEqual(after[first*stride:end*stride],before[first*stride:end*stride])
                self.assertEqual(read(result['files']['mapping']['path']),read(base['files']['mapping']['path']))
                self.assertEqual(read(folder/'fcp-production.json')['mode'],'mix')
                self.assertEqual(pcm(folder/'final-mix.wav')[0],38400)
                self.assertIn('audio_cuts',result['files'])
                self.assertEqual(session._load()['project'],original_state['project'])
                self.assertEqual(session._load()['reviews'],[])
                inspected=session.inspect(result['id'],.2,.3)
                evidence=read(inspected['path'])
                self.assertIn('audio_source_spans',evidence)
                with self.assertRaisesRegex(ValueError,'joint audio-word mapping'):
                    session.retime_source(result['id'])
                with self.assertRaisesRegex(ValueError,'base audio'):
                    session.compare_candidates([base['id'],result['id']])
                compared=session.compare_candidates([base['id'],result['id']],mode='structure')
                self.assertEqual(read(compared['evidence']['path'])['candidates'][1]['production_changes']['audio_cuts'],[event])
                with self.assertRaisesRegex(ValueError,'audio_cuts'):
                    session.review(result['id'],{'render_sha256':result['files']['video']['sha256'],'checks':[]},'automation')
