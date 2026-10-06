"""Actual static-overlay alpha samples survive holds and frame omissions."""
from fractions import Fraction
from pathlib import Path
import hashlib
import subprocess
import tempfile
import unittest

import numpy as np
from PIL import Image

from video_harness.visual import render_overlays
from video_harness.cues import validate_cues


def decoded(path, width, height):
    raw = subprocess.check_output(['ffmpeg', '-v', 'error', '-i', str(path),
        '-map', '0:v:0', '-fps_mode', 'passthrough', '-f', 'rawvideo', '-pix_fmt', 'rgba', 'pipe:1'])
    return np.frombuffer(raw, np.uint8).reshape(-1, height, width, 4)


class StaticCuePhaseTests(unittest.TestCase):
    def test_actual_alpha_samples_and_audio_survive_frame_selection(self):
        for rate in (Fraction(30), Fraction(30000, 1001)):
            for role in ('image', 'title'):
                with self.subTest(rate=rate, role=role), tempfile.TemporaryDirectory() as tmp:
                    root = Path(tmp); base = root/'base.mp4'
                    subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i',
                        f'testsrc2=s=160x90:r={rate}:d=1', '-f', 'lavfi', '-i',
                        'sine=frequency=440:sample_rate=48000:duration=1',
                        '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-c:a', 'aac',
                        '-t', '1', str(base)], check=True, capture_output=True)
                    asset = root/'image.png'; Image.new('RGBA', (100, 40), (240, 60, 40, 160)).save(asset)
                    records = [{'asset_id': 'image', 'kind': 'image', 'path': str(asset),
                                'sha256': hashlib.sha256(asset.read_bytes()).hexdigest()}]
                    common = {'id': 'static', 'role': role, 'position': 'top', 'opacity': .7,
                        'fade_in': str(3/rate), 'fade_out': str(3/rate), 'reason': 'Synthetic alpha test'}
                    common.update({'asset_id': 'image'} if role == 'image' else {'text': 'GO'})
                    old = {**common, 'output_start': str(3/rate), 'output_end': str(11/rate)}
                    original = render_overlays(base, [old], records, root/'old.mp4', 1)
                    clock = original['video_cue_clocks'][0]
                    old_layer = decoded(clock['original_layer']['path'], 160, 90)
                    self.assertGreater(int(old_layer[3,:,:,3].sum()), int(old_layer[1,:,:,3].sum()))
                    for selection in ([0, 1, 1, 1, 3, 5, 7], [2], [1, 3, 5]):
                        phase = {key: clock[key] for key in ('original_start_frame',
                            'original_frame_count', 'original_layer', 'original_cue_sha256')}
                        phase.update(version=2, frames=selection)
                        moved = {**common, 'output_start': str(5/rate),
                            'output_end': str((5+len(selection))/rate), 'phase_map': phase}
                        target = root/f'new-{len(selection)}.mp4'
                        result = render_overlays(base, [moved], records, target, 1)
                        from video_harness.overlay_layers import remap_overlay_layer
                        selected_layer = root/f'selected-{len(selection)}.mkv'
                        remap_overlay_layer(clock['original_layer'], selection, rate, (160, 90), selected_layer)
                        mapped = decoded(selected_layer, 160, 90)
                        np.testing.assert_array_equal(mapped, old_layer[selection])
                        picture = decoded(target, 160, 90).astype(float)
                        primary = decoded(base, 160, 90).astype(float)
                        for j, old_index in enumerate(selection):
                            layer = old_layer[old_index].astype(float)
                            alpha = layer[:,:,3:4]/255
                            expected = layer[:,:,:3]*alpha + primary[5+j,:,:,:3]*(1-alpha)
                            self.assertLess(np.abs(picture[5+j,:,:,:3]-expected).mean(), 8)
                        self.assertLess(np.abs(picture[:5,:,:,:3]-primary[:5,:,:,:3]).mean(), 4)
                        self.assertEqual(len(picture), len(primary))
                        self.assertLess(np.abs(picture[5+len(selection):,:,:,:3]-primary[5+len(selection):,:,:,:3]).mean(), 4)
                        def pcm(path):
                            return subprocess.check_output(['ffmpeg', '-v', 'error', '-i', str(path),
                                '-map', '0:a:0', '-f', 's16le', 'pipe:1'])
                        self.assertEqual(pcm(base), pcm(target))
                    for change in ({'opacity': .2}, {'fade_in': '0'},
                                   {'position': 'center'}, {'text': 'NO'} if role == 'title' else {}):
                        if not change: continue
                        with self.assertRaisesRegex(ValueError, 'changed|digest|SHA'):
                            render_overlays(base, [{**moved, **change}], records, root/'invalid.mp4', 1)
                    with self.assertRaises(ValueError):
                        validate_cues([{**moved, 'phase_map': {**phase, 'version': 1}}], records, 1, rate)

