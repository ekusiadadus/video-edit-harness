import math
import struct
import tempfile
import unittest
import wave
import subprocess
import shutil
from copy import deepcopy
from datetime import date
from pathlib import Path

from video_harness.assets import register_asset
from video_harness.production import resolve_production, mix_key, freeze_pattern
from video_harness.render_cache import digest


class ProductionTests(unittest.TestCase):
    def test_session_snapshot_survives_definition_refresh(self):
        from unittest.mock import patch
        cfg = freeze_pattern({'editing_pattern': {'id': 'natural'}})
        original = cfg['_editing_pattern_snapshot']
        with patch('video_harness.production.resolve_pattern', side_effect=AssertionError('Unexpected definition refresh')):
            self.assertEqual(resolve_production(cfg, {'duration': 1})['pattern'], original)
            self.assertEqual(freeze_pattern(cfg)['_editing_pattern_snapshot'], original)

    def fixture(self, folder, *, mixed=False, raw=False):
        path = folder / 'original-tone.wav'
        with wave.open(str(path), 'wb') as stream:
            stream.setnchannels(1)
            stream.setsampwidth(2)
            stream.setframerate(48000)
            stream.writeframes(b''.join(struct.pack('<h', round(1000 * math.sin(i / 48000 * 2 * math.pi * 220))) for i in range(48000 * 2)))
        rights = {'status': 'verified', 'commercial': True, 'advertising': False,
                  'modification': True, 'destinations': ['youtube'], 'regions': [],
                  'attribution_required': False, 'embedded_use': True,
                  'mixed_audio_handoff': mixed, 'raw_asset_handoff': raw}
        day = date.today().isoformat()
        evidence = folder / 'fixture-rights.txt'
        evidence.write_text('Generated sine tone owned by this test fixture. No external recording used.')
        asset = register_asset(path, {'asset_id': 'original', 'kind': 'music', 'creator': 'Test fixture',
            'source_url': 'https://example.org/original', 'license_url': 'https://example.org/license',
            'acquired_on': day, 'verified_on': day, 'credit': 'Original test tone',
            'rights': rights, 'evidence_path': str(evidence), 'cost': 0, 'currency': 'JPY', 'content_id': 'none'})
        return {'editing_pattern': {'id': 'gentle_vlog'}, 'assets': [asset],
                'asset_policy': {'destinations': ['youtube'], 'usage': 'monetized'}}

    def test_natural_discards_previous_additions(self):
        cfg = {'editing_pattern': {'id': 'natural'}, 'assets': [{'asset_id': 'missing'}],
               'cue_plan': {'invalid': 'old cues'}}
        result = resolve_production(cfg, {'duration': 5})
        self.assertEqual(result['cues'], [])
        self.assertEqual(result['assets'], [])

    def test_cues_bind_mapping_and_invalidate_sound(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = self.fixture(Path(tmp))
            mapping = {'duration': 5, 'sequence': []}
            resolved = resolve_production(cfg, mapping)
            self.assertEqual(len(resolved['cues']), 2)
            cfg['cue_plan'] = {'version': 1, 'mapping_sha256': digest(mapping), 'cues': resolved['cues']}
            first = resolve_production(cfg, mapping)
            cfg['cue_plan']['cues'][0]['gain_db'] = -6
            self.assertNotEqual(mix_key(first), mix_key(resolve_production(cfg, mapping)))
            with self.assertRaisesRegex(ValueError, 'stale'):
                resolve_production(cfg, {'duration': 6})

    def test_tampered_asset_rejected_before_placement(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = self.fixture(Path(tmp))
            Path(cfg['assets'][0]['path']).write_bytes(b'tampered')
            with self.assertRaisesRegex(ValueError, 'changed'):
                resolve_production(cfg, {'duration': 5})

    @unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'requires FFmpeg')
    def test_render_natural_pcm_equivalence_and_music_change(self):
        from video_harness.common import fingerprint, read
        from video_harness.edl import build_plan
        from video_harness.editing import render_edit
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cfg = self.fixture(root)
            source = root / 'source.mp4'
            subprocess.run(['ffmpeg', '-v', 'error', '-nostdin', '-n',
                '-f', 'lavfi', '-i', 'color=c=gray:s=128x128:r=30:d=2',
                '-f', 'lavfi', '-i', 'sine=frequency=440:sample_rate=48000:duration=2',
                '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-c:a', 'aac', str(source)], check=True)
            cfg.update(source=str(source), name='Synthetic integration fixture', input_color='rec709',
                evidence_kind='synthetic', render_cache_root=str(root / 'cache'),
                audio={'normalize': True, 'target_lufs': -16, 'true_peak_db': -1.5, 'loudness_range': 7})
            # Generated tones and synthetic word anchors test mechanics only.
            transcript = {'version': 1, 'source': fingerprint(source), 'duration': 2,
                          'words': [{'id': 'fixture-word', 'start': .2, 'end': 1.8, 'text': 'Fixture', 'probability': 1.0}],
                          'segments': []}
            plan = build_plan(cfg, transcript, [])
            baseline = deepcopy(cfg)
            baseline.pop('editing_pattern')
            render_edit(baseline, plan, root / 'legacy', True)
            natural = deepcopy(cfg)
            natural['editing_pattern'] = {'id': 'natural'}
            render_edit(natural, plan, root / 'natural', True)
            render_edit(cfg, plan, root / 'music', True)
            def decoded(folder, kind):
                args = ['-vn', '-f', 's16le', '-acodec', 'pcm_s16le'] if kind == 'audio' else ['-an', '-f', 'rawvideo', '-pix_fmt', 'yuv420p']
                return subprocess.check_output(['ffmpeg', '-v', 'error', '-i', str(root / folder / 'video.mp4'), *args, 'pipe:1'])
            self.assertEqual(decoded('legacy', 'audio'), decoded('natural', 'audio'))
            self.assertEqual(decoded('legacy', 'video'), decoded('natural', 'video'))
            self.assertNotEqual(decoded('natural', 'audio'), decoded('music', 'audio'))
            self.assertEqual(decoded('natural', 'video'), decoded('music', 'video'))
            self.assertTrue((root / 'music' / 'production.json').is_file())
            self.assertEqual(read(root / 'music' / 'result.json')['technical_status'], 'pass')
