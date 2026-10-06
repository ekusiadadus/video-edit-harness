"""Geometry, strict XML readback and synthetic media checks; no FCP GUI."""

import hashlib
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
import xml.etree.ElementTree as ET

from PIL import Image

from video_harness.overlay_placement import (check_overlay_video_timing,
                                             check_video_geometry,
                                             measure_placement,
                                             parse_static_placement)
from video_harness.production_fcp import _validate_spatial_context
from video_harness.visual import render_overlays


class PlacementTests(unittest.TestCase):
    def test_measured_ffmpeg_aspect_rounding_cases(self):
        cases = [(120, 40, 160, 90, 112, 37),
                 (101, 333, 1920, 1080, 164, 540),
                 (803, 307, 1920, 1080, 1344, 514),
                 (4096, 2160, 1080, 1920, 756, 399),
                 (37, 41, 160, 90, 41, 45)]
        for sw, sh, cw, ch, rw, rh in cases:
            with self.subTest(source=(sw, sh), canvas=(cw, ch)):
                measured = measure_placement({'role': 'image'}, cw, ch, sw, sh)
                self.assertEqual(measured['rendered_size'], [rw, rh])

    def test_title_is_full_canvas_with_same_position_rule(self):
        result = measure_placement({'role': 'title', 'position': 'top',
                                    'opacity': '.4'}, 1920, 1080, 1920, 1080)
        self.assertEqual(result['rendered_size'], [1920, 1080])
        self.assertEqual(result['y_pixels'], 108)
        self.assertEqual(result['transform_scale'], [1, 1])
        self.assertEqual(result['transform_position'], [0, -10])
        self.assertEqual(result['opacity'], .4)

    def test_yuv420_overlay_effective_top_pixel(self):
        top = measure_placement({'role': 'image', 'position': 'top'}, 160, 90, 120, 40)
        center = measure_placement({'role': 'image', 'position': 'center'}, 160, 90, 120, 40)
        self.assertEqual((top['x_pixels'], top['y_pixels']), (24, 8))
        self.assertEqual((center['x_pixels'], center['y_pixels']), (24, 22))

    @unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'FFmpeg required')
    def test_rgba_white_overlay_decoded_pixel_bounds(self):
        with tempfile.TemporaryDirectory(prefix='placement-bbox-') as directory:
            root = Path(directory)
            background = root / 'background.mp4'
            picture = root / 'white.png'
            subprocess.run(['ffmpeg', '-v', 'error', '-nostdin', '-f', 'lavfi',
                            '-i', 'color=c=black:s=160x90:r=30:d=1',
                            '-c:v', 'libx264', '-pix_fmt', 'yuv420p', str(background)], check=True)
            Image.new('RGBA', (120, 40), (255, 255, 255, 255)).save(picture)
            asset = {'asset_id': 'white', 'kind': 'image', 'path': str(picture),
                     'sha256': hashlib.sha256(picture.read_bytes()).hexdigest()}
            for position, expected_y in [('top', 8), ('center', 22)]:
                with self.subTest(position=position):
                    cue = {'id': 'white', 'asset_id': 'white', 'role': 'image',
                           'output_start': 0, 'output_end': '.9', 'position': position}
                    output = root / f'{position}.mp4'
                    render_overlays(background, [cue], [asset], output, 1)
                    raw = subprocess.check_output(['ffmpeg', '-v', 'error', '-nostdin',
                                                   '-ss', '0.5', '-i', str(output),
                                                   '-frames:v', '1', '-f', 'rawvideo',
                                                   '-pix_fmt', 'rgb24', '-'])
                    self.assertEqual(len(raw), 160 * 90 * 3)
                    lit = [(index % 160, index // 160)
                           for index in range(160 * 90)
                           if min(raw[index * 3:index * 3 + 3]) > 220]
                    self.assertTrue(lit)
                    self.assertEqual((min(x for x, _ in lit), min(y for _, y in lit)),
                                     (24, expected_y))

    def test_rejects_ambiguous_source_display_geometry(self):
        stream = {'codec_type': 'video', 'width': 100, 'height': 50,
                  'sample_aspect_ratio': '4:3'}
        with self.assertRaisesRegex(ValueError, 'non-square'):
            check_video_geometry(stream)
        stream['sample_aspect_ratio'] = '1:1'
        stream['side_data_list'] = [{'side_data_type': 'Display Matrix', 'rotation': -90}]
        with self.assertRaisesRegex(ValueError, 'rotated'):
            check_video_geometry(stream)

    def test_overlay_video_timing_rejects_vfr_and_nonzero_start(self):
        stream = {'codec_type': 'video', 'r_frame_rate': '30/1',
                  'avg_frame_rate': '30/1', 'start_time': '0.000000'}
        self.assertEqual(check_overlay_video_timing(stream), 30)
        with self.assertRaisesRegex(ValueError, 'frame rate'):
            check_overlay_video_timing({**stream, 'avg_frame_rate': '24/1'})
        with self.assertRaisesRegex(ValueError, 'start_time'):
            check_overlay_video_timing({**stream, 'start_time': '0.5'})
        with self.assertRaisesRegex(ValueError, 'unknown'):
            check_overlay_video_timing({key: value for key, value in stream.items()
                                        if key != 'start_time'})

    def test_spatial_nodes_are_rejected_outside_direct_connected_video(self):
        trio = ('<adjust-conform type="none"/>'
                '<adjust-transform scale="1 1"/>'
                '<adjust-blend amount="1"/>')
        templates = [f'<resources><asset>{trio}</asset></resources><spine><asset-clip/></spine>',
                     f'<sequence>{trio}<spine><asset-clip/></spine></sequence>',
                     f'<spine><asset-clip>{trio}</asset-clip></spine>',
                     f'<spine><asset-clip><asset-clip srcEnable="audio">{trio}</asset-clip></asset-clip></spine>',
                     f'<spine><asset-clip><asset-clip srcEnable="video"><gap>{trio}</gap></asset-clip></asset-clip></spine>']
        for contents in templates:
            with self.subTest(contents=contents):
                root = ET.fromstring('<fcpxml>' + contents + '</fcpxml>')
                with self.assertRaisesRegex(ValueError, 'outside a connected video clip'):
                    _validate_spatial_context(root, root.find('.//spine'))
        good = ET.fromstring('<fcpxml><spine><asset-clip><asset-clip srcEnable="video">'
                                  + trio + '</asset-clip></asset-clip></spine></fcpxml>')
        _validate_spatial_context(good, good.find('spine'))

    def test_static_xml_parser_canonicalizes_equivalent_defaults(self):
        clip = ET.fromstring('<asset-clip><adjust-conform type="none"/>'
                             '<adjust-transform position="0.00 -25.0" scale="1.0 0.5"/>'
                             '<adjust-blend amount="1.00"/></asset-clip>')
        self.assertEqual(parse_static_placement(clip),
                         {'conform': 'none', 'position': ['0', '-25'],
                          'scale': ['1', '0.5'], 'opacity': '1'})
        self.assertIsNone(parse_static_placement(ET.fromstring('<asset-clip/>')))

    def test_static_xml_parser_rejects_effect_changes(self):
        good = ('<adjust-conform type="none"/><adjust-transform scale="1 1"/>'
                '<adjust-blend amount="1"/>')
        bad = [good.replace('scale="1 1"', 'scale="NaN 1"'),
               good.replace('<adjust-blend amount="1"/>', ''),
               good.replace('scale="1 1"', 'rotation="1" scale="1 1"'),
               good.replace('<adjust-blend amount="1"/>',
                            '<adjust-blend amount="1"><param/></adjust-blend>'),
               good.replace('type="none"', 'type="fit"'),
               good.replace('scale="1 1"', 'scale="1 1" mystery="1"')]
        for children in bad:
            with self.subTest(children=children):
                clip = ET.fromstring('<asset-clip>' + children + '</asset-clip>')
                with self.assertRaises(ValueError):
                    parse_static_placement(clip)



    @unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'FFmpeg required')
    def test_actual_nonzero_stream_clock_is_rejected_by_preview_and_export(self):
        from video_harness.common import probe
        from video_harness.fcp import export_timeline
        from video_harness.production_fcp import export_production_xml
        from video_harness.visual import render_overlays
        with tempfile.TemporaryDirectory(prefix='overlay-clock-') as tmp:
            root = Path(tmp)
            base = root / 'base.mp4'
            shifted = root / 'shifted.mp4'
            for path, filters in ((base, []), (shifted, ['-vf', 'setpts=PTS+0.25/TB', '-fps_mode', 'passthrough'])):
                subprocess.run(['ffmpeg', '-v', 'error', '-nostdin', '-n', '-f', 'lavfi',
                                '-i', 'color=c=black:s=160x90:r=30:d=1', *filters,
                                '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-an', str(path)], check=True)
            stream = next(row for row in probe(shifted)['streams'] if row['codec_type'] == 'video')
            self.assertGreater(float(stream['start_time']), 0)
            record = {'asset_id': 'shifted', 'kind': 'video', 'path': str(shifted),
                      'sha256': hashlib.sha256(shifted.read_bytes()).hexdigest()}
            cue = {'id': 'late', 'role': 'video', 'asset_id': 'shifted',
                   'output_start': 0, 'output_end': .5, 'source_start': 0, 'source_end': .5}
            preview = root / 'preview.mp4'
            with self.assertRaisesRegex(ValueError, 'nonzero overlay'):
                render_overlays(base, [cue], [record], preview, 1)
            self.assertFalse(preview.exists())
            xml = root / 'base.fcpxml'
            export_timeline(base, probe(base), [(0, 1)], xml, 'Clock guard')
            output = root / 'editable.fcpxml'
            with self.assertRaisesRegex(ValueError, 'nonzero overlay'):
                export_production_xml(xml, {'assets': [record], 'cues': [cue]}, None, output, 'editable')
            self.assertFalse(output.exists())


    @unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'FFmpeg required')
    def test_small_average_rate_difference_does_not_hide_a_missing_frame(self):
        from fractions import Fraction
        from video_harness.common import probe
        from video_harness.overlay_placement import check_overlay_video_clock
        with tempfile.TemporaryDirectory(prefix='overlay-vfr-') as tmp:
            path = Path(tmp) / 'missing-frame.mp4'
            subprocess.run(['ffmpeg', '-v', 'error', '-nostdin', '-n', '-f', 'lavfi',
                            '-i', 'color=c=black:s=160x90:r=30:d=4', '-vf', r'select=not(eq(n\,60))',
                            '-fps_mode', 'vfr', '-c:v', 'libx264', '-pix_fmt', 'yuv420p',
                            '-an', str(path)], check=True)
            stream = next(row for row in probe(path)['streams'] if row['codec_type'] == 'video')
            rate = Fraction(stream['r_frame_rate'])
            average = Fraction(stream['avg_frame_rate'])
            self.assertLess(abs(rate - average) / rate, Fraction(1, 100))
            self.assertEqual(check_overlay_video_timing(stream), rate)
            with self.assertRaisesRegex(ValueError, 'constant frame timestamps'):
                check_overlay_video_clock(path, stream)


    def test_fcp_position_uses_project_height_for_small_overlay_source(self):
        placement = measure_placement({'role': 'image', 'position': 'top'}, 160, 90, 120, 40)
        # Actual decoded bounds are x24/y8 and112x37; their center is26.5px,
        # 18.5px above the90px project center, independent of40px source height.
        self.assertAlmostEqual(placement['transform_position'][0], 0)
        self.assertAlmostEqual(placement['transform_position'][1], 18.5 / 90 * 100)

if __name__ == '__main__':
    unittest.main()
