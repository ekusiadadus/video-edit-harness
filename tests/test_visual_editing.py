"""Synthetic, local visual EDL renders; no transcript or ASR."""
from datetime import date
from pathlib import Path
import json
import shutil
import subprocess
import tempfile
import unittest
import wave
import struct
import math
import xml.etree.ElementTree as ET

from video_harness.assets import register_asset
from video_harness.common import fingerprint, probe, read
from video_harness.visual_editing import render_visual_edit


@unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'FFmpeg required')
class VisualEditingTests(unittest.TestCase):
    def fixture(self, folder, *, source_audio):
        video = folder / ('environment.mp4' if source_audio else 'silent.mp4')
        cmd = ['ffmpeg', '-v', 'error', '-nostdin', '-n', '-f', 'lavfi',
               '-i', 'color=c=blue:s=128x128:r=10:d=1']
        if source_audio:
            cmd += ['-f', 'lavfi', '-i', 'sine=frequency=440:sample_rate=48000:duration=1']
        cmd += ['-c:v', 'libx264', '-pix_fmt', 'yuv420p']
        if source_audio:
            cmd += ['-c:a', 'aac']
        cmd += [str(video)]
        subprocess.run(cmd, check=True)
        evidence = folder / 'visual-rights.txt'
        evidence.write_text('Synthetic footage generated only for a local test.')
        day = date.today().isoformat()
        asset = register_asset(video, {'asset_id': 'video1', 'kind': 'video', 'creator': 'Test fixture',
            'source_url': 'https://example.org/visual', 'license_url': 'https://example.org/visual-rights',
            'acquired_on': day, 'verified_on': day, 'evidence_path': str(evidence),
            'credit': 'Synthetic test footage', 'cost': 0, 'currency': 'JPY', 'content_id': 'none',
            'rights': {'status': 'verified', 'commercial': True, 'advertising': False,
                       'modification': True, 'destinations': ['youtube'], 'regions': [],
                       'attribution_required': False, 'embedded_use': True,
                       'mixed_audio_handoff': False, 'raw_asset_handoff': False}})
        cfg = {'name': 'Visual Fixture', 'source': str(video), 'input_color': 'rec709',
               'assets': [asset], 'asset_policy': {'destinations': ['youtube'], 'usage': 'monetized'},
               'audio': {'normalize': False, 'target_lufs': -16, 'true_peak_db': -1.5,
                         'loudness_range': 7}, 'editing_pattern': {'id': 'natural'},
               'evidence_kind': 'synthetic'}
        edl = {'version': 4, 'edit_basis': 'visual', 'status': 'reviewed_selection',
               'review': {'actor': 'codex', 'reason': 'Synthetic source range checked',
                          'basis': 'source_inspection'},
               'sequence': [{'id': 'first', 'asset_id': 'video1', 'source_start': 0,
                             'source_end': .4, 'reason': 'Fixture first interval'},
                            {'id': 'second', 'asset_id': 'video1', 'source_start': .6,
                             'source_end': 1, 'reason': 'Fixture final interval'}]}
        return cfg, edl

    def test_silent_source_exports_compatible_silent_audio_and_mapping(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            cfg, edl = self.fixture(root, source_audio=False)
            out = render_visual_edit(cfg, edl, root / 'render', preview=True)
            result = read(out / 'result.json')
            self.assertEqual(result['technical_status'], 'pass')
            mapping = read(out / 'frame-mapping.json')
            self.assertEqual(mapping['edit_basis'], 'visual')
            self.assertEqual([s['id'] for s in mapping['sequence']], ['first', 'second'])
            self.assertEqual(mapping['frame_count'], 8)
            self.assertFalse(mapping['has_source_audio'])
            self.assertTrue(all(s['source_sha256'] == cfg['assets'][0]['sha256'] for s in mapping['sequence']))
            info = probe(out / 'video.mp4')
            self.assertTrue(any(s['codec_type'] == 'audio' for s in info['streams']))
            pcm = subprocess.check_output(['ffmpeg', '-v', 'error', '-i', str(out / 'video.mp4'),
                                           '-vn', '-ac', '1', '-ar', '48000', '-f', 's16le', 'pipe:1'])
            self.assertEqual(set(pcm), {0})
            self.assertIn('Synthetic 48 kHz silence', (out / 'fcp-delivery.json').read_text())
            self.assertEqual((out / 'subtitles.srt').read_text(), '')

    def test_environment_audio_in_source_order(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            cfg, edl = self.fixture(root, source_audio=True)
            out = render_visual_edit(cfg, edl, root / 'render', preview=True)
            mapping = read(out / 'frame-mapping.json')
            self.assertEqual(mapping['sequence'][0]['source_start'], '0s')
            self.assertEqual(mapping['sequence'][1]['source_start'], '3/5s')
            self.assertEqual(mapping['sequence'][1]['output_start'], '2/5s')
            self.assertTrue(mapping['has_source_audio'])
            self.assertIn('asset-clip', (out / 'timeline.fcpxml').read_text())
            self.assertGreater((out / 'environment.wav').stat().st_size, 100)
            self.assertTrue((out / 'audio-only.mp3').is_file())

    def test_optional_licensed_bgm_mix(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            cfg, edl = self.fixture(root, source_audio=False)
            music_path = root / 'music.wav'
            with wave.open(str(music_path), 'wb') as stream:
                stream.setnchannels(1)
                stream.setsampwidth(2)
                stream.setframerate(48000)
                stream.writeframes(b''.join(struct.pack('<h', int(2000 * math.sin(2 * math.pi * 220 * i / 48000)))
                                            for i in range(48000)))
            template = cfg['assets'][0]
            evidence = root / 'music-rights.txt'
            evidence.write_text('Synthetic music generated by test.')
            music = register_asset(music_path, {
                'asset_id': 'music1', 'kind': 'music', 'creator': 'Test fixture',
                'source_url': 'https://example.org/music', 'license_url': 'https://example.org/music-rights',
                'acquired_on': date.today().isoformat(), 'verified_on': date.today().isoformat(),
                'evidence_path': str(evidence), 'credit': 'Synthetic music', 'cost': 0,
                'currency': 'JPY', 'content_id': 'none', 'rights': template['rights']})
            cfg['assets'].append(music)
            cfg['editing_pattern'] = {'id': 'gentle_vlog'}
            out = render_visual_edit(cfg, edl, root / 'render', preview=True)
            production = read(out / 'production.json')
            self.assertEqual(len([c for c in production['cues'] if c['role'] == 'music']), 2)
            self.assertEqual(read(out / 'result.json')['technical_status'], 'pass')
            self.assertTrue((out / 'creative-mix.wav').is_file())

    def test_two_sources_have_distinct_mapping_and_xml_assets(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            cfg, edl = self.fixture(root, source_audio=True)
            second = root / 'silent-second.mp4'
            subprocess.run(['ffmpeg', '-v', 'error', '-nostdin', '-n', '-f', 'lavfi',
                            '-i', 'color=c=red:s=160x90:r=15:d=1', '-c:v', 'libx264',
                            '-pix_fmt', 'yuv420p', str(second)], check=True)
            evidence = root / 'second-rights.txt'
            evidence.write_text('Synthetic second source.')
            second_asset = register_asset(second, {
                'asset_id': 'video2', 'kind': 'video', 'creator': 'Test fixture',
                'source_url': 'https://example.org/second', 'license_url': 'https://example.org/second-rights',
                'acquired_on': date.today().isoformat(), 'verified_on': date.today().isoformat(),
                'evidence_path': str(evidence), 'credit': 'Synthetic second video', 'cost': 0,
                'currency': 'JPY', 'content_id': 'none', 'rights': cfg['assets'][0]['rights']})
            cfg['assets'].append(second_asset)
            edl['sequence'][1]['asset_id'] = 'video2'
            out = render_visual_edit(cfg, edl, root / 'render', preview=True)
            mapping = read(out / 'frame-mapping.json')
            self.assertEqual([row['asset_id'] for row in mapping['sequence']], ['video1', 'video2'])
            self.assertNotEqual(mapping['sequence'][0]['source_sha256'], mapping['sequence'][1]['source_sha256'])
            self.assertTrue(mapping['has_source_audio'])
            xml = ET.parse(out / 'timeline.fcpxml').getroot()
            self.assertEqual(len(xml.findall('./resources/asset')), 2)
            self.assertEqual(len(xml.findall('./resources/format')), 3)
            self.assertEqual(xml.find("./resources/format[@id='fmt']").get('colorSpace'),
                             '1-1-1 (Rec. 709)')
            for asset in xml.findall('./resources/asset'):
                self.assertIsNone(xml.find(f"./resources/format[@id='{asset.get('format')}']").get('colorSpace'))
            self.assertEqual(len(xml.findall('./library/event/project/sequence/spine/asset-clip')), 2)
            self.assertEqual(len(xml.findall('./library/event/project/sequence/spine/asset-clip/conform-rate')), 1)
            dtd = Path('/Applications/Final Cut Pro Creator Studio.app/Contents/Frameworks/Interchange.framework/Versions/A/Resources/FCPXMLv1_10.dtd')
            if shutil.which('xmllint') and dtd.is_file():
                alias = root / 'FCPXMLv1_10.dtd'
                shutil.copyfile(dtd, alias)
                checked = subprocess.run(['xmllint', '--noout', '--dtdvalid', str(alias),
                                          str(out / 'timeline.fcpxml')], capture_output=True, text=True)
                self.assertEqual(checked.returncode, 0, checked.stderr)
            pcm = subprocess.check_output(['ffmpeg', '-v', 'error', '-i', str(out / 'video.mp4'),
                                           '-vn', '-ac', '1', '-ar', '48000', '-f', 's16le', 'pipe:1'])
            self.assertTrue(any(pcm[:48000 * 2 * 3 // 10]))
            self.assertEqual(set(pcm[48000 * 2 * 5 // 10:]), {0})


if __name__ == '__main__':
    unittest.main()
