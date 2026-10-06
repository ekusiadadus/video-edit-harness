import hashlib
import subprocess
import tempfile
import unittest
from pathlib import Path

import numpy as np

from PIL import Image

from video_harness.visual import (approve_visual_edl, render_overlays,
                                  render_visual_edl, revise_visual_edl,
                                  validate_visual_edl)


def asset(path, kind, name):
    return {'asset_id': name, 'kind': kind, 'path': str(path),
            'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}


class VisualTests(unittest.TestCase):
    def test_silent_multisource_frame_mapping_and_overlay(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            records = []
            for name, color in [('red', 'red'), ('blue', 'blue')]:
                path = root / f'{name}.mp4'
                cmd = ['ffmpeg', '-v', 'error', '-nostdin', '-y', '-f', 'lavfi',
                       '-i', f'color=c={color}:s=160x90:r=30:d=1']
                if name == 'blue':
                    cmd += ['-f', 'lavfi', '-i', 'sine=frequency=440:sample_rate=48000:duration=1',
                            '-c:a', 'aac']
                else:
                    cmd += ['-an']
                cmd += ['-c:v', 'libx264', '-pix_fmt', 'yuv420p', str(path)]
                subprocess.run(cmd, check=True)
                records.append(asset(path, 'video', name))
            edl = {'version': 4, 'edit_basis': 'visual', 'status': 'proposed',
                   'sequence': [{'id': 'a', 'asset_id': 'red', 'source_start': 0,
                                 'source_end': .5, 'reason': 'Observed red opening'},
                                {'id': 'b', 'asset_id': 'blue', 'source_start': .5,
                                 'source_end': 1, 'reason': 'Observed blue close'}]}
            normalized = validate_visual_edl(edl, records)
            self.assertEqual(validate_visual_edl(normalized, records)['sequence'][0]['source_first_frame'], 0)
            stale = dict(normalized)
            stale['sources'] = {**normalized['sources'], 'extra': normalized['sources']['red']}
            with self.assertRaisesRegex(ValueError, 'source bindings'):
                validate_visual_edl(stale, records)
            stale = dict(normalized)
            stale['sequence'] = [dict(normalized['sequence'][0], source_first_frame=2),
                                 normalized['sequence'][1]]
            with self.assertRaisesRegex(ValueError, 'source_first_frame changed'):
                validate_visual_edl(stale, records)
            reviewed = approve_visual_edl(normalized, actor='codex', reason='Synthetic fixture',
                                          review_basis='source_inspection')
            self.assertEqual(reviewed['review']['actor'], 'codex')
            revised = revise_visual_edl(reviewed, edl['sequence'], actor='codex', reason='Try another cut')
            self.assertEqual(revised['status'], 'proposed')
            result = render_visual_edl(edl, records, root / 'assembled.mp4')
            self.assertEqual(result['frame_count'], 30)
            self.assertEqual(result['frame_mapping'][1]['output_first_frame'], 15)
            self.assertTrue((root / 'assembled.mp4').is_file())
            raw_audio = subprocess.check_output(['ffmpeg', '-v', 'error', '-i',
                str(root / 'assembled.mp4'), '-map', '0:a:0', '-f', 'f32le',
                '-ac', '1', '-ar', '48000', 'pipe:1'])
            samples = np.frombuffer(raw_audio, dtype='<f4')
            self.assertLess(float(np.sqrt(np.mean(samples[3000:15000] ** 2))), .002)
            self.assertGreater(float(np.sqrt(np.mean(samples[30000:40000] ** 2))), .01)
            picture = root / 'overlay.png'
            Image.new('RGBA', (32, 32), 'green').save(picture)
            records.append(asset(picture, 'image', 'picture'))
            cues = [{'id': 'photo', 'asset_id': 'picture', 'role': 'image',
                     'output_start': 0, 'output_end': .5}]
            result = render_overlays(root / 'assembled.mp4', cues, records,
                                     root / 'overlay.mp4', 1)
            self.assertEqual(result['cues'], ['photo'])
            self.assertTrue((root / 'overlay.mp4').is_file())
