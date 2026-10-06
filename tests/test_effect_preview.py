"""Completed-picture excerpts retain frame identity at fractional frame rates."""
from fractions import Fraction
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from video_harness.common import fingerprint, read, write
from video_harness.effect_preview import export_effect_preview


@unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'FFmpeg required')
class EffectPreviewTests(unittest.TestCase):
    def test_fractional_rate_slice_preserves_exact_parent_frames_and_full_audio(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            rate = Fraction(30000, 1001)
            video = root / 'source.mp4'
            subprocess.run(['ffmpeg', '-v', 'error', '-nostdin', '-n', '-f', 'lavfi',
                '-i', 'testsrc2=s=64x64:r=30000/1001:d=0.4004', '-f', 'lavfi',
                '-i', 'sine=frequency=440:sample_rate=48000:duration=0.4004',
                '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-c:a', 'aac', str(video)], check=True)
            duration = float(Fraction(12, 1) / rate)
            mapping = {'fps': str(rate), 'frame_count': 12, 'duration': duration,
                       'keep': [[0, duration]], 'sequence_ids': ['sample']}
            write(root / 'mapping.json', mapping)
            render = {'id': 'original', 'preview': False,
                      'files': {'video': fingerprint(video), 'mapping': fingerprint(root / 'mapping.json')}}
            revised = {**render, 'id': 'revised'}
            ref = export_effect_preview(render, revised, root / 'excerpt', 3, 9, {})
            doc = read(ref['path'])
            self.assertEqual(doc['fps'], str(rate))
            self.assertEqual(doc['output_start'], str(Fraction(3, 1) / rate))
            self.assertEqual(doc['parents']['before']['video'], render['files']['video'])
            self.assertEqual(doc['audio_sample_bounds']['first_sample'], 4805)
            self.assertEqual(doc['audio_sample_bounds']['end_sample_exclusive'], 14414)
            def rgb(path):
                return subprocess.check_output(['ffmpeg', '-v', 'error', '-i', str(path),
                    '-an', '-pix_fmt', 'rgb24', '-f', 'rawvideo', '-'])
            parent = rgb(video)
            self.assertEqual(len(parent), 12 * 64 * 64 * 3)
            self.assertEqual(rgb(root / 'excerpt' / 'before.mp4'), parent[3*64*64*3:9*64*64*3])
            self.assertEqual(read(root / 'excerpt' / 'result.json')['technical_status'], 'pass')
            one = export_effect_preview(render, revised, root / 'one-frame', 11, 12, {})
            self.assertEqual(rgb(root / 'one-frame' / 'after.mp4'), parent[11*64*64*3:])
            self.assertEqual(read(one['path'])['end_frame_exclusive'], 12)
            for bounds in ((-1, 3), (9, 3), (0, 13), (True, 3)):
                with self.assertRaises(ValueError):
                    export_effect_preview(render, revised, root / 'invalid', *bounds, {})
                self.assertFalse((root / 'invalid').exists())
            with self.assertRaises(ValueError):
                export_effect_preview({**render, 'preview': True}, revised, root / 'invalid', 3, 9, {})
            with self.assertRaises(ValueError):
                export_effect_preview(render, revised, root / 'invalid', 3, 9, {'invalid': float('nan')})
            wrong_mapping = {**mapping, 'duration': duration * 2}
            write(root / 'wrong-mapping.json', wrong_mapping)
            wrong = {**render, 'files': {**render['files'],
                'mapping': fingerprint(root / 'wrong-mapping.json')}}
            with self.assertRaisesRegex(ValueError, 'mapping duration'):
                export_effect_preview(wrong, revised, root / 'invalid', 3, 9, {})
            from contextlib import contextmanager
            from unittest.mock import patch
            from video_harness.runs import evidence_run
            @contextmanager
            def late_source_change(*args, **kwargs):
                with evidence_run(*args, **kwargs) as manifest:
                    yield manifest
                    video.write_bytes(b'changed during context exit')
            original_bytes = video.read_bytes()
            try:
                with patch('video_harness.effect_preview.evidence_run', late_source_change):
                    with self.assertRaisesRegex(ValueError, 'Source changed'):
                        export_effect_preview(render, revised, root / 'late-failure', 3, 9, {})
                self.assertEqual(read(root / 'late-failure' / 'result.json')['technical_status'], 'failed')
                self.assertFalse((root / 'late-failure' / 'preview.html').exists())
                self.assertFalse((root / 'late-failure' / 'before.mp4').exists())
            finally:
                video.write_bytes(original_bytes)
            retained = (root / 'excerpt' / 'before.mp4').read_bytes()
            with self.assertRaises(FileExistsError):
                export_effect_preview(render, revised, root / 'excerpt', 3, 9, {})
            self.assertEqual((root / 'excerpt' / 'before.mp4').read_bytes(), retained)
            video.write_bytes(b'changed original')
            with self.assertRaises(ValueError):
                export_effect_preview(render, revised, root / 'invalid', 3, 9, {})
