"""Public demos must bind their presentation language to the actual speech."""
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1]/'scripts'
sys.path.insert(0, str(SCRIPTS))
spec = importlib.util.spec_from_file_location('build_platform_demos', SCRIPTS/'build_platform_demos.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class DemoLanguages(unittest.TestCase):
    def test_mismatched_voice_and_transcript_fail(self):
        for voice, timing in [('ja', 'en'), ('en', 'ja'), ('fr', 'fr')]:
            with self.assertRaises(ValueError):
                module.fixture_language({'voice': {'language': voice}}, {'language': timing})
        for language in ('ja', 'en'):
            self.assertEqual(module.fixture_language({'voice': {'language': language}}, {'language': language}), language)

    def test_requested_translation_does_not_relabel_existing_audio(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); sample = root/'sample'; sample.mkdir()
            (sample/'provenance.json').write_text(json.dumps({'voice': {'language': 'ja'}}))
            (sample/'timing.json').write_text(json.dumps({'language': 'ja'}))
            with patch.object(module, 'render_sample') as render:
                with self.assertRaisesRegex(ValueError, 'actual voice'):
                    module.build(sample, root/'out', root/'docs', language='en')
                render.assert_not_called()
            self.assertFalse((root/'out').exists())
            self.assertFalse((root/'docs').exists())

    def test_same_language_foreign_timing_fails_before_render(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); sample = root/'sample'; sample.mkdir()
            (sample/'provenance.json').write_text(json.dumps({'voice': {'language': 'en'}, 'source_kind': 'synthetic', 'source_sha256': 'a'*64}))
            (sample/'timing.json').write_text(json.dumps({'language': 'en', 'source_sha256': 'b'*64}))
            with patch.object(module, 'fingerprint', return_value={'sha256': 'a'*64}), patch.object(module, 'render_sample') as render:
                with self.assertRaisesRegex(ValueError, 'different source'):
                    module.build(sample, root/'out', root/'docs', language='en')
                render.assert_not_called()
            self.assertFalse((root/'out').exists())

    def test_english_presentation_contains_no_japanese_labels(self):
        labels = json.dumps(module.language_content('en'), ensure_ascii=False)
        self.assertFalse(any('\u3040' <= char <= '\u30ff' or '\u4e00' <= char <= '\u9fff' for char in labels))
        self.assertIn('編集前', module.language_content('ja')['before'])


class OverviewTimeline(unittest.TestCase):
    def test_independent_segments_join_on_one_zero_based_frame_grid(self):
        import shutil
        import subprocess
        if not shutil.which('ffmpeg') or not shutil.which('ffprobe'):
            self.skipTest('FFmpeg is required for the media regression')
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);clips=[]
            for index,(color,frames) in enumerate([('red',10),('blue',14)]):
                clip=root/f'{index}.mp4'
                subprocess.run(['ffmpeg','-v','error','-nostdin','-y','-f','lavfi','-i',f'color={color}:s=128x72:r=30',
                                '-f','lavfi','-i','anullsrc=r=48000:cl=stereo','-t',str(frames/30),
                                '-c:v','libx264','-pix_fmt','yuv420p','-c:a','aac',str(clip)],check=True)
                clips.append(clip)
            target=root/'overview.mp4'
            expected=module.join_segments(clips,target,root/'join.log')
            info=module.probe(target)
            video=next(s for s in info['streams'] if s['codec_type']=='video')
            self.assertEqual(expected,24)
            self.assertEqual(int(video['nb_frames']),24)
            self.assertEqual(float(video['start_time']),0)
            self.assertAlmostEqual(float(video['duration']),.8,places=4)
            self.assertNotIn('Non-monotonic', (root/'join.log').read_text())
            packets=json.loads(subprocess.check_output(['ffprobe','-v','error','-show_packets','-show_entries','packet=stream_index,dts_time','-of','json',str(target)]))['packets']
            for stream in (0,1):
                times=[float(p['dts_time']) for p in packets if p['stream_index']==stream]
                self.assertTrue(all(a<b for a,b in zip(times,times[1:])))
            raw=subprocess.check_output(['ffmpeg','-v','error','-i',str(target),'-f','rawvideo','-pix_fmt','rgb24','-'])
            stride=128*72*3
            self.assertEqual(len(raw),stride*24)
            self.assertGreater(raw[5*stride],200)  # Red before the join.
            self.assertGreater(raw[15*stride+2],200)  # Blue after the join.


class SpeechBoundaryPreservation(unittest.TestCase):
    def test_exact_recording_extents_override_late_asr_onset(self):
        from render_demo_sample import sentence_padding
        first=[{'start':0,'end':4.64}];last=[{'start':6.90,'end':11.52}]
        padding=sentence_padding(first,last,[[0,4.65],[6.65,12.15]],12.166667)
        self.assertLessEqual(last[0]['start']-padding[1][0],6.65)
        self.assertGreaterEqual(last[-1]['end']+padding[1][1],12.15)
        self.assertGreater(padding[1][0],.25)
        with self.assertRaises(ValueError):sentence_padding(first,last,[[0,4.65],[4.0,12.15]],12.166667)
        with self.assertRaises(ValueError):sentence_padding(first,last,None,12.166667)
