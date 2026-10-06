import hashlib
import subprocess
import tempfile
import unittest
import wave
import xml.etree.ElementTree as ET
from pathlib import Path

from PIL import Image

from video_harness.common import probe
from video_harness.fcp import export_timeline
from video_harness.production_fcp import (compare_production_reexport,
                                          DTD_PATHS, export_production_xml,
                                          inspect_production_xml,
                                          resolve_media_path)
from video_harness.visual_editing import _write_xml


def asset(path, kind, identifier):
    return {'path': str(path), 'kind': kind, 'asset_id': identifier,
            'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}


class ProductionFCPTests(unittest.TestCase):
    def fixtures(self, root):
        source = root / 'source.mp4'
        subprocess.run(['ffmpeg', '-v', 'error', '-nostdin', '-y', '-f', 'lavfi',
                        '-i', 'color=c=black:s=160x90:r=30:d=4', '-f', 'lavfi',
                        '-i', 'sine=frequency=440:sample_rate=48000:duration=4',
                        '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-c:a', 'aac',
                        '-shortest', str(source)], check=True)
        base = root / 'base.fcpxml'
        export_timeline(source, probe(source), [(1, 2), (3, 4)], base, 'Fixture')
        music = root / 'music.wav'
        mixed = root / 'mixed.wav'
        for path, seconds in ((music, 1), (mixed, 2)):
            with wave.open(str(path), 'wb') as stream:
                stream.setparams((2, 2, 48000, 0, 'NONE', 'not compressed'))
                stream.writeframes(b'\x00\x00\x00\x00' * 48000 * seconds)
        picture = root / 'picture.png'
        Image.new('RGBA', (64, 64), 'yellow').save(picture)
        return base, mixed, [asset(music, 'music', 'm'), asset(picture, 'image', 'p')]

    def test_video_phase_uses_baked_handoff_and_rejects_editable_loss(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            base, mixed, _ = self.fixtures(root)
            source = root / 'source.mp4'
            video = asset(source, 'video', 'v')
            production = {'assets': [video], 'cues': [{
                'id': 'overlay', 'asset_id': 'v', 'role': 'video',
                'output_start': '1/30', 'output_end': '7/30', 'source_start': '0', 'source_end': '1/10',
                'phase_map': {'version': 1, 'original_start_frame': 1,
                              'original_frame_count': 3, 'original_time_base': '1/15360', 'original_input_pts_shift': 0,
                              'original_timestamps': [512, 1024, 1536], 'frames': [0, 0, 1, 1, 2, 2]}}]}
            with self.assertRaisesRegex(ValueError, 'baked'):
                export_production_xml(base, production, mixed, root / 'editable.fcpxml', mode='editable')
            self.assertFalse((root / 'editable.fcpxml').exists())
            result = export_production_xml(base, production, mixed, root / 'baked.fcpxml', mode='mix')
            self.assertEqual(result['mode'], 'mix')
            self.assertTrue((root / 'baked.fcpxml').is_file())

    def test_three_modes_and_strict_readback(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            base, mixed, assets = self.fixtures(root)
            cues = [{'id': 'music', 'asset_id': 'm', 'role': 'music',
                     'output_start': 0, 'output_end': 2,
                     'source_start': 0, 'source_end': 1, 'loop': True,
                     'gain_db': -6, 'fade_in': .1, 'fade_out': .1, 'duck': True,
                     'beat_anchor': .5},
                    {'id': 'still', 'asset_id': 'p', 'role': 'image',
                     'output_start': .5, 'output_end': 1.5}]
            production = {'assets': assets, 'cues': cues}
            mix = root / 'mix.fcpxml'
            result = export_production_xml(base, production, mixed, mix, mode='mix')
            self.assertEqual(result['dtd'], 'passed' if any(p.is_file() for p in DTD_PATHS) else 'unavailable')
            observed = inspect_production_xml(mix, result)
            self.assertTrue(all(clip['srcEnable'] == 'video' for clip in observed['primary']))
            self.assertEqual(len(observed['connected']), 1)
            self.assertEqual(observed['connected'][0]['offset'], '1s')
            self.assertEqual(observed['connected'][0]['output_start'], '0s')
            self.assertTrue(compare_production_reexport(mix, mix)['matched'])
            editable = root / 'editable.fcpxml'
            result = export_production_xml(base, production, mixed, editable, mode='editable')
            self.assertEqual(result['dtd'], 'passed' if any(p.is_file() for p in DTD_PATHS) else 'unavailable')
            self.assertTrue(any('ducking' in item for item in result['manual_remaining']))
            observed = inspect_production_xml(editable, result)
            self.assertEqual(len(observed['connected']), 3)  # two music loops plus still
            self.assertEqual(observed['connected'][0]['gain'], '-6.000dB')
            self.assertEqual(observed['connected'][0]['fade_in'], '1/10s')
            self.assertIn('1/10s', [node['fade_out'] for node in observed['connected']])
            second_music = next(node for node in observed['connected'] if node['name'] == 'music' and node['output_start'] == '1s')
            self.assertEqual(second_music['offset'], '3s')
            self.assertEqual(observed['markers'][0]['start'], '3/2s')
            self.assertEqual(observed['markers'][0]['output_time'], '1/2s')
            only = export_production_xml(base, production, None, root / 'none.fcpxml',
                                         mode='video_only')
            self.assertIsNone(only['xml'])
            self.assertFalse((root / 'none.fcpxml').exists())
            altered = root / 'altered.fcpxml'
            tree = ET.parse(editable)
            tree.find('.//asset-clip/asset-clip').set('audioRole', 'effects')
            tree.write(altered)
            with self.assertRaisesRegex(ValueError, 'changed'):
                compare_production_reexport(editable, altered)
            dropped_marker = root / 'dropped-marker.fcpxml'
            tree = ET.parse(editable)
            marker = tree.find('.//marker')
            parent = next(node for node in tree.iter() if marker in list(node))
            parent.remove(marker)
            tree.write(dropped_marker)
            with self.assertRaisesRegex(ValueError, 'changed'):
                compare_production_reexport(editable, dropped_marker)
            title = root / 'title.fcpxml'
            title_result = export_production_xml(base, {'assets': [], 'cues': [
                {'id': 'heading', 'asset_id': None, 'role': 'title', 'text': 'Hello',
                 'output_start': 0, 'output_end': .5}]}, None, title, mode='editable')
            self.assertEqual(title_result['dtd'], 'passed' if any(p.is_file() for p in DTD_PATHS) else 'unavailable')

    def test_rejects_stale_media_and_wrong_pcm_length(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            base, mixed, assets = self.fixtures(root)
            production = {'assets': assets, 'cues': [{'id': 'm', 'asset_id': 'm',
                         'role': 'music', 'output_start': 0, 'output_end': 1,
                         'source_start': 0, 'source_end': 1}]}
            with self.assertRaisesRegex(ValueError, 'match base'):
                export_production_xml(base, production, assets[0]['path'],
                                      root / 'wrong.fcpxml', mode='mix')
            Path(assets[0]['path']).write_bytes(b'changed')
            with self.assertRaisesRegex(ValueError, 'SHA-256 mismatch'):
                export_production_xml(base, production, mixed,
                                      root / 'stale.fcpxml', mode='editable')

    def test_mixed_fps_conform_is_preserved_and_checked(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            base, mixed, _ = self.fixtures(root)
            second = root / '25fps.mp4'
            subprocess.run(['ffmpeg', '-v', 'error', '-nostdin', '-y', '-f', 'lavfi',
                            '-i', 'color=c=green:s=160x90:r=25:d=2', '-an',
                            '-c:v', 'libx264', '-pix_fmt', 'yuv420p', str(second)], check=True)
            mapping = {'fps': '30', 'frame_count': 60, 'sequence': [
                {'asset_id': 'a', 'source_fps': '30', 'source_first_frame': 30,
                 'output_first_frame': 0, 'output_end_frame_exclusive': 30},
                {'asset_id': 'b', 'source_fps': '25', 'source_first_frame': 0,
                 'output_first_frame': 30, 'output_end_frame_exclusive': 60}]}
            base = root / 'mixed-base.fcpxml'
            _write_xml(base, {}, mapping, {'a': {'path': str(root / 'source.mp4')},
                                          'b': {'path': str(second)}}, 'Mixed FPS')
            result = export_production_xml(base, {'assets': [], 'cues': []}, mixed,
                                           root / 'mixed-conform.fcpxml', mode='mix')
            self.assertEqual(result['dtd'], 'passed' if any(p.is_file() for p in DTD_PATHS) else 'unavailable')
            observed = inspect_production_xml(result['xml'])
            self.assertIsNone(observed['primary'][0]['conform_rate']['conform'])
            self.assertEqual(observed['primary'][1]['conform_rate']['conform']['srcFrameRate'], '25')
            layered = export_production_xml(base, {'assets': [asset(second, 'video', 'v')],
                'cues': [{'id': 'visual', 'asset_id': 'v', 'role': 'video',
                          'output_start': .25, 'output_end': .75,
                          'source_start': 0, 'source_end': .5}]}, None,
                root / 'mixed-layer.fcpxml', mode='editable')
            self.assertEqual(layered['dtd'], 'passed' if any(p.is_file() for p in DTD_PATHS) else 'unavailable')
            visual = next(item for item in inspect_production_xml(layered['xml'])['connected']
                          if item['name'] == 'visual')
            self.assertEqual(visual['conform_rate']['srcFrameRate'], '25')
            bad = ET.parse(base)
            bad.find('.//conform-rate').set('srcFrameRate', '30')
            altered = root / 'bad-conform.fcpxml'
            bad.write(altered)
            with self.assertRaisesRegex(ValueError, 'disagrees'):
                export_production_xml(altered, {'assets': [], 'cues': []}, mixed,
                                      root / 'bad-output.fcpxml', mode='mix')

    def test_portable_media_uri_resolves_and_blocks_traversal(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            media = root / 'media'
            media.mkdir()
            item = media / 'name with space.wav'
            item.write_bytes(b'fixture')
            xml = root / 'bundle.fcpxml'
            self.assertEqual(resolve_media_path('./media/name%20with%20space.wav', xml), item.resolve())
            for uri in ('./media/%2e%2e/secret.wav', '../secret.wav',
                        'https://example.com/sound.wav', 'file://otherhost/path.wav',
                        './media/name.wav?token=secret', './media/name.wav#track'):
                with self.subTest(uri=uri), self.assertRaises(ValueError):
                    resolve_media_path(uri, xml)
            escape = media / 'link.wav'
            escape.symlink_to(root.parent / 'outside.wav')
            with self.assertRaisesRegex(ValueError, 'escapes'):
                resolve_media_path('./media/link.wav', xml)


if __name__ == '__main__':
    unittest.main()
