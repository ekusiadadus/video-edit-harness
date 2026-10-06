"""Real encoded picture/caption checks, distinct from human listening review."""
import json
from pathlib import Path
import subprocess
import shutil
from importlib.util import find_spec
import tempfile
import unittest

import numpy as np

from video_harness.retime import prepare_retime,render_retime,captions_srt,remap_captions
from video_harness.time_mapping import compile_retime


class RetimeRenderTests(unittest.TestCase):
    def test_fractional_frame_duration_retains_sample_exact_mp4_audio_end(self):
        from fractions import Fraction
        import wave
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);source=root/'source.mkv'
            subprocess.run(['ffmpeg','-v','error','-n','-f','lavfi','-i',
                'color=c=gray:s=64x48:r=30:d=1.8666666666666667','-f','lavfi','-i',
                'sine=frequency=440:sample_rate=48000:duration=1.8666666666666667',
                '-c:v','ffv1','-c:a','pcm_s16le',str(source)],check=True,capture_output=True)
            proposal=prepare_retime(source,{'operations':[]},'automation','Synthetic fractional-frame endpoint')
            output=root/'result.mp4';pcm=root/'retimed.wav'
            report=render_retime(source,proposal,output,pcm_output=pcm)
            info=json.loads(subprocess.check_output(['ffprobe','-v','error','-show_streams','-of','json',str(output)]))
            audio=next(s for s in info['streams'] if s['codec_type']=='audio')
            duration=Fraction(audio['duration_ts'])*Fraction(audio['time_base'])
            self.assertEqual(duration,Fraction(56,30))
            with wave.open(str(pcm),'rb') as stream:
                self.assertEqual(stream.getnframes(),89600)
            self.assertEqual(report['audio']['output_samples'],89600)

    def fixture(self,root):
        source=root/'source.mkv'
        pixels=np.stack([np.full((48,64,3),15+i*16,dtype=np.uint8) for i in range(12)])
        subprocess.run(['ffmpeg','-v','error','-n','-f','rawvideo','-pix_fmt','rgb24','-s','64x48',
                        '-r','10','-i','pipe:0','-f','lavfi','-i','sine=frequency=440:sample_rate=48000:duration=1.2',
                        '-c:v','ffv1','-c:a','pcm_s16le','-shortest',str(source)],input=pixels.tobytes(),check=True,capture_output=True)
        return source

    @unittest.skipUnless(shutil.which('rubberband') and find_spec('soundfile'),'Optional Rubber Band audio backend unavailable')
    def test_actual_frame_selection_freeze_and_caption_shift(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);source=self.fixture(root)
            request={'operations':[{'id':'hold','kind':'freeze','source_frame':2,'output_frames':2,'reason':'Read the result'},
                                    {'id':'fast','kind':'ramp','source_first_frame':6,'source_end_frame_exclusive':10,
                                     'speed_start':2,'speed_end':2,'reason':'Shorten the movement'}],
                     'captions':[{'id':'read','text':'結果','source_first_frame':2,'source_end_frame_exclusive':4}]}
            proposal=prepare_retime(source,request,'codex','Synthetic timing acceptance')
            report=render_retime(source,proposal,root/'retimed.mp4')
            expected=proposal['mapping']['frame_map']
            raw=subprocess.check_output(['ffmpeg','-v','error','-i',str(root/'retimed.mp4'),'-map','0:v:0','-f','rawvideo','-pix_fmt','rgb24','-'])
            frames=np.frombuffer(raw,dtype=np.uint8).reshape(-1,48,64,3)
            self.assertEqual(len(frames),len(expected))
            for actual,source_frame in zip(frames,expected):
                self.assertLess(abs(float(actual.mean())-(15+source_frame*16)),4)
            self.assertEqual(report['captions'][0]['output_start'],'1/5')
            self.assertEqual(report['captions'][0]['output_end'],'3/5')
            self.assertIn('00:00:00,200 --> 00:00:00,600',captions_srt(report['captions']))
            self.assertFalse(proposal['adopted'])

    def test_skipped_caption_is_recorded_instead_of_invented(self):
        mapping=compile_retime(8,'10',[{'id':'fast','kind':'ramp','source_first_frame':0,
            'source_end_frame_exclusive':4,'speed_start':4,'speed_end':4,'reason':'Skip motion'}])
        captions=remap_captions([{'id':'skipped','text':'未表示','source_first_frame':1,
                                 'source_end_frame_exclusive':2}],mapping)
        self.assertEqual(captions[0]['status'],'omitted_by_retime')
        self.assertEqual(captions_srt(captions),'')

    def test_protected_speech_stale_source_and_tampered_mapping_refused(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);source=self.fixture(root)
            ramp={'id':'fast','kind':'ramp','source_first_frame':2,'source_end_frame_exclusive':8,
                  'speed_start':1,'speed_end':2,'reason':'Speed up'}
            with self.assertRaisesRegex(ValueError,'protected'):
                prepare_retime(source,{'operations':[ramp],'protected_intervals':[[4,6]]},'codex','Protect speech')
            proposal=prepare_retime(source,{'operations':[ramp]},'codex','Synthetic timing acceptance')
            altered=json.loads(json.dumps(proposal));altered['mapping']['frame_map'][0]=1
            with self.assertRaisesRegex(ValueError,'mapping or captions changed'):
                render_retime(source,altered,root/'bad.mp4')
            source.write_bytes(b'changed')
            with self.assertRaisesRegex(ValueError,'source changed'):
                render_retime(source,proposal,root/'stale.mp4')
            self.assertFalse((root/'bad.mp4').exists())
