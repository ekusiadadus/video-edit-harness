"""Real portrait layout export preserves the reviewed SRT and source audio."""
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from video_harness.common import fingerprint, read
from video_harness.vertical import export_vertical


@unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe')
                     and importlib.util.find_spec('regex'), 'FFmpeg and text-layout required')
class CaptionLayoutExportTests(unittest.TestCase):
    def test_language_layout_keeps_cue_times_and_audio_and_records_lines(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / 'source.mp4'
            subprocess.run(['ffmpeg', '-v', 'error', '-nostdin', '-n', '-f', 'lavfi',
                '-i', 'testsrc2=size=160x90:rate=30:duration=0.4', '-f', 'lavfi',
                '-i', 'sine=frequency=440:sample_rate=48000:duration=0.4',
                '-vf', 'setparams=color_primaries=bt709:color_trc=bt709:colorspace=bt709',
                '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-c:a', 'aac',
                '-color_primaries', 'bt709', '-color_trc', 'bt709', '-colorspace', 'bt709',
                str(source)], check=True, capture_output=True)
            caption = root / 'caption.srt'
            original_text = 'Compare the effects with Final Cut Pro and keep natural motion.'
            caption.write_text('1\n00:00:00,000 --> 00:00:00,350\n'+original_text+'\n')
            before_source, before_caption = fingerprint(source), fingerprint(caption)
            layout = {'version': 1, 'language': 'en', 'protected_phrases': ['Final Cut Pro']}
            result = export_vertical(source, root / 'portrait', subtitles=caption,
                                     caption_layout=layout)
            self.assertEqual(result['caption_layout']['language'], 'en')
            lines = result['caption_lines'][0]
            self.assertEqual((lines['start'], lines['end']), (0, .35))
            self.assertEqual(lines['text'], original_text)
            self.assertGreater(len(lines['lines']), 1)
            self.assertIn('Final Cut Pro', ' | '.join(lines['lines']))
            self.assertEqual((root / 'portrait/subtitles.srt').read_bytes(), caption.read_bytes())
            def pcm(path):
                return subprocess.check_output(['ffmpeg', '-v', 'error', '-i', str(path),
                    '-map', '0:a:0', '-f', 's16le', '-'])
            self.assertEqual(pcm(source), pcm(root / 'portrait/video.mp4'))
            self.assertEqual(before_source, fingerprint(source))
            self.assertEqual(before_caption, fingerprint(caption))
            self.assertEqual(result['perceptual_status'], 'not_reviewed')
            self.assertEqual(read(root / 'portrait/result.json')['caption_lines'], result['caption_lines'])

    def test_public_cli_passes_explicit_layout_and_legacy_help_is_available(self):
        from unittest.mock import patch
        from contextlib import redirect_stdout
        import io
        from video_harness import cli
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'layout.json'
            layout = {'version': 1, 'language': 'ja', 'protected_phrases': []}
            path.write_text(json.dumps(layout))
            argv = ['video-harness', 'tiktok-export', 'source.mp4', '--output', 'new',
                    '--caption-layout', str(path)]
            with patch('sys.argv', argv), patch('video_harness.vertical.export_vertical', return_value={}) as export, redirect_stdout(io.StringIO()):
                cli.main()
            self.assertEqual(export.call_args.kwargs['caption_layout'], layout)
