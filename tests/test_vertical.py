"""Exercise real local portrait exports, captions, audio and source preservation."""
import hashlib
import numpy as np
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from video_harness.common import probe
from video_harness.vertical import export_vertical, load_captions


@unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'FFmpeg required')
class VerticalExport(unittest.TestCase):
    def test_fit_crop_and_captioned_exports_preserve_audio_and_input(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); src=root/'graded.mp4'
            subprocess.run(['ffmpeg','-v','error','-y','-f','lavfi','-i','testsrc2=size=160x90:rate=30:duration=0.6',
                '-f','lavfi','-i','sine=frequency=440:sample_rate=48000:duration=0.6','-c:v','libx264','-pix_fmt','yuv420p',
                '-vf','setparams=color_primaries=bt709:color_trc=bt709:colorspace=bt709','-color_primaries','bt709','-color_trc','bt709','-colorspace','bt709','-c:a','aac',str(src)],check=True)
            digest=hashlib.sha256(src.read_bytes()).hexdigest()
            srt=root/'captions.srt';srt.write_text('1\n00:00:00,000 --> 00:00:00,500\nReal caption\n')
            for mode,captions in [('fit',None),('center_crop',None),('fit',srt)]:
                with self.subTest(mode=mode,captions=bool(captions)):
                    out=root/(mode+('-captions' if captions else ''))
                    result=export_vertical(src,out,mode,captions)
                    self.assertEqual(result['technical_status'],'pass')
                    self.assertEqual(result['subtitles_burned'],bool(captions))
                    streams=probe(out/'video.mp4')['streams'];v=next(s for s in streams if s['codec_type']=='video')
                    self.assertEqual((v['width'],v['height'],v['sample_aspect_ratio']),(1080,1920,'1:1'))
                    self.assertEqual(next(s for s in streams if s['codec_type']=='audio')['codec_name'],'aac')
                    self.assertAlmostEqual(float(v['duration']),.6,delta=.05)
                    # Inspect pixels, not just flags: fit preserves padding, crop fills it.
                    frame=subprocess.check_output(['ffmpeg','-v','error','-i',str(out/'video.mp4'),'-frames:v','1','-f','rawvideo','-pix_fmt','rgb24','-'])
                    if mode=='fit':
                        self.assertTrue(all(abs(a-b)<8 for a,b in zip(frame[:3],(16,19,26))))
                    if captions:
                        plain=subprocess.check_output(['ffmpeg','-v','error','-i',str(root/'fit/video.mp4'),'-frames:v','1','-f','rawvideo','-pix_fmt','rgb24','-'])
                        original_pixels=np.frombuffer(plain,dtype=np.uint8).reshape(1920,1080,3)
                        caption_pixels=np.frombuffer(frame,dtype=np.uint8).reshape(1920,1080,3)
                        self.assertLess(np.abs(original_pixels[720:1200].astype(int)-caption_pixels[720:1200].astype(int)).mean(),4)
                        offset=(1350*1080+100)*3
                        self.assertNotEqual(frame[offset:1480*1080*3],plain[offset:1480*1080*3])
                    with self.assertRaises(FileExistsError):
                        export_vertical(src,out,mode,captions)
            self.assertEqual(hashlib.sha256(src.read_bytes()).hexdigest(),digest)

    def test_subtitle_ranges_and_plain_text_are_checked(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'caption.srt'
            for content in ['1\n00:00:00,000 --> 00:00:02,000\nToo long\n',
                            '1\n00:00:00,000 --> 00:00:00,300\n<style>\n',
                            '1\n00:00:00,000 --> 00:00:00,400\nOne\n\n2\n00:00:00,300 --> 00:00:00,500\nTwo\n']:
                p.write_text(content)
                with self.assertRaises(ValueError): load_captions(p,1)
