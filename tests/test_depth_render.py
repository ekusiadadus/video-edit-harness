"""Synthetic local depth render: source frames, rights and audio stay bound."""

from copy import deepcopy
from contextlib import redirect_stdout
from datetime import date
from io import StringIO
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
from PIL import Image

from video_harness.assets import register_asset
from video_harness.common import read, write
from video_harness.depth_artifact import prepare_manual_depth
from video_harness.depth_cli import main as depth_cli_main
from video_harness.depth_render import render_depth_layer
from video_harness.transitions import _pcm_hash
from video_harness.video_effects import _probe as probe_video


@unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'FFmpeg required')
class DepthRenderTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.base = self.root/'base.mp4'
        subprocess.run(['ffmpeg', '-v', 'error', '-nostdin', '-n', '-f', 'lavfi', '-i',
                        'color=c=blue:s=16x16:r=4:d=1', '-f', 'lavfi', '-i',
                        'sine=frequency=440:sample_rate=48000:duration=1',
                        '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-c:a', 'aac',
                        str(self.base)], check=True, capture_output=True)
        fields = {}
        for frame in (1, 2):
            array = np.zeros((16, 16), dtype=np.float32)
            array[:, 8:] = 1  # right side is nearer, hides the red layer
            field = self.root/f'{frame}.npy'
            np.save(field, array, allow_pickle=False)
            fields[frame] = field
        self.manifest = prepare_manual_depth(self.base, fields, self.root/'depth',
                                             'automation', 'Synthetic near-high split')
        self.image = self.root/'red.png'
        Image.new('RGBA', (16, 16), (255, 0, 0, 255)).save(self.image)
        self.policy = {'destinations': ['youtube'], 'usage': 'monetized'}
        self.asset = self.register_image()

    def register_image(self, *, right=True, path=None):
        evidence = self.root/'rights.txt'
        evidence.write_text('Synthetic image rights for local test.')
        day = date.today().isoformat()
        return register_asset(path or self.image, {
            'asset_id': 'red-layer', 'kind': 'image', 'creator': 'Test fixture',
            'source_url': 'https://example.org/red', 'license_url': 'https://example.org/red-rights',
            'acquired_on': day, 'verified_on': day, 'evidence_path': str(evidence),
            'credit': 'Synthetic red image', 'cost': 0, 'currency': 'JPY', 'content_id': 'none',
            'rights': {'status': 'verified', 'commercial': True, 'advertising': False,
                       'modification': True, 'destinations': ['youtube'], 'regions': [],
                       'attribution_required': False, 'embedded_use': right,
                       'mixed_audio_handoff': False, 'raw_asset_handoff': False}})

    def decoded(self, path):
        raw = subprocess.check_output(['ffmpeg', '-v', 'error', '-i', str(path), '-an',
                                       '-pix_fmt', 'rgb24', '-f', 'rawvideo', '-'])
        return np.frombuffer(raw, dtype=np.uint8).reshape(4, 16, 16, 3)

    def test_far_layer_near_occlusion_unchanged_outer_frames_and_pcm(self):
        output = self.root/'result.mp4'
        report = render_depth_layer(self.base, self.manifest, self.asset, self.policy,
                                    output, input_color='rec709', actor='automation',
                                    reason='Synthetic depth composite')
        self.assertTrue(report['full_decode'])
        self.assertTrue(report['review_required'])
        self.assertFalse(report['adopted'])
        self.assertFalse(report['metric_distance'])
        self.assertEqual(report['depth_interval'],
                         {'start_frame': 1, 'end_frame_exclusive': 3})
        self.assertEqual(report['decoded_pcm_sha256'], _pcm_hash(self.base))
        self.assertEqual(report['image_asset']['record_sha256'], self.asset['record_sha256'])
        self.assertEqual(report['image_asset_record']['rights'], self.asset['rights'])
        self.assertEqual(report['asset_policy']['usage'], 'monetized')
        self.assertEqual(_pcm_hash(output), _pcm_hash(self.base))
        original, rendered = self.decoded(self.base), self.decoded(output)
        for frame in (0, 3):
            self.assertLess(np.abs(original[frame].astype(int)-rendered[frame].astype(int)).max(), 25)
            self.assertGreater(rendered[frame, 8, 4, 2], rendered[frame, 8, 4, 0])
        for frame in (1, 2):
            self.assertGreater(rendered[frame, 8, 3, 0], rendered[frame, 8, 3, 2])
            self.assertGreater(rendered[frame, 8, 12, 2], rendered[frame, 8, 12, 0])
        with self.assertRaises(ValueError):
            render_depth_layer(self.base, self.manifest, self.asset, self.policy,
                               output, input_color='rec709', actor='automation',
                               reason='No overwrite')

    def test_tampering_rights_geometry_and_color_are_rejected(self):
        denied = self.register_image(right=False)
        with self.assertRaisesRegex(ValueError, 'embedded_use'):
            render_depth_layer(self.base, self.manifest, denied, self.policy,
                               self.root/'denied.mp4', input_color='rec709',
                               actor='automation', reason='Rights denied')
        wrong = self.root/'wrong.png'
        Image.new('RGBA', (8, 16), (255, 0, 0, 255)).save(wrong)
        wrong_asset = self.register_image(path=wrong)
        with self.assertRaisesRegex(ValueError, 'full-canvas'):
            render_depth_layer(self.base, self.manifest, wrong_asset, self.policy,
                               self.root/'wrong.mp4', input_color='rec709',
                               actor='automation', reason='Wrong canvas')
        with self.assertRaisesRegex(ValueError, 'Rec.709'):
            render_depth_layer(self.base, self.manifest, self.asset, self.policy,
                               self.root/'log.mp4', input_color='apple_log',
                               actor='automation', reason='Unsupported color')
        forged = deepcopy(self.asset)
        forged['sha256'] = '0'*64
        with self.assertRaisesRegex(ValueError, 'record changed'):
            render_depth_layer(self.base, self.manifest, forged, self.policy,
                               self.root/'forged.mp4', input_color='rec709',
                               actor='automation', reason='Forged registration')
        field = self.root/'depth'/'000000001.npy'
        np.save(field, np.ones((16, 16), dtype=np.float32), allow_pickle=False)
        with self.assertRaisesRegex(ValueError, 'binding changed'):
            render_depth_layer(self.base, self.manifest, self.asset, self.policy,
                               self.root/'field.mp4', input_color='rec709',
                               actor='automation', reason='Changed depth field')

    def test_nonzero_or_unknown_audio_start_is_rejected_before_encoding(self):
        observed = probe_video(self.base, count=True)
        for value in ('1/100', None):
            altered = deepcopy(observed)
            audio = next(stream for stream in altered['streams'] if stream['codec_type'] == 'audio')
            if value is None:
                audio.pop('start_time', None)
            else:
                audio['start_time'] = value
            output = self.root/f'audio-start-{"nonzero" if value else "unknown"}.mp4'
            with self.subTest(value=value), patch('video_harness.depth_render._probe', return_value=altered):
                with self.assertRaisesRegex(ValueError, 'base audio'):
                    render_depth_layer(self.base, self.manifest, self.asset, self.policy,
                                       output, input_color='rec709', actor='automation',
                                       reason='Invalid audio timestamp')
            self.assertFalse(output.exists())

    def test_public_cli_render_seals_technical_evidence(self):
        asset_file = self.root/'asset.json'
        policy_file = self.root/'policy.json'
        write(asset_file, self.asset)
        write(policy_file, self.policy)
        output = self.root/'cli-depth'
        with redirect_stdout(StringIO()):
            depth_cli_main(['render', str(self.base), str(self.manifest),
                            '--asset', str(asset_file), '--policy', str(policy_file),
                            '--input-color', 'rec709', '--output', str(output),
                            '--actor', 'automation', '--note', 'Synthetic CLI depth render'])
        self.assertTrue((output/'video.mp4').is_file())
        evidence = read(output/'depth-render.json')
        self.assertTrue(evidence['review_required'])
        self.assertFalse(evidence['adopted'])
        self.assertEqual(evidence['decoded_pcm_sha256'], _pcm_hash(self.base))
        self.assertEqual(read(output/'result.json')['technical_status'], 'pass')
