"""Source provenance and timeline coverage for retimed visual mappings."""

import unittest
from copy import deepcopy
from fractions import Fraction
import hashlib
from pathlib import Path
import subprocess
import tempfile

from video_harness.render_cache import digest
from video_harness.retime_mapping import conform_source_frames, remap_visual_mapping
from video_harness.time_mapping import compile_retime
from video_harness.visual import render_visual_edl


def source_row(asset, path, sha, source_fps, source_first, source_end, output_first, output_end):
    return {'id': asset, 'asset_id': asset, 'source_path': path, 'source_sha256': sha,
            'source_fps': source_fps, 'source_first_frame': source_first,
            'source_end_frame_exclusive': source_end, 'output_first_frame': output_first,
            'output_end_frame_exclusive': output_end, 'output_fps': '30/1'}


def mapping():
    return {'version': 4, 'edit_basis': 'visual', 'duration': 0.3,
            'frame_count': 9, 'fps': '30/1', 'has_source_audio': True,
            'audio': 'source or silence', 'metadata': {'review': 'retained'},
            'sequence': [{**source_row('a', '/media/a.mp4', 'a' * 64, '15/1', 10, 13, 0, 6),
                          'source_frame_map': [10, 10, 11, 11, 12, 12]},
                         {**source_row('b', '/media/b.mp4', 'b' * 64, '60/1', 20, 26, 6, 9),
                          'source_frame_map': [20, 22, 24]}]}


class RetimeVisualMappingTests(unittest.TestCase):
    def test_frame_references_match_ffmpeg_visual_renderer_pixels(self):
        # Every source frame is a unique gray value; inspect decoded output
        # pixels to check the actual fps conform, including duplicated/skipped frames.
        width = height = 16
        source_count = 12
        values = [24 + i * 16 for i in range(source_count)]
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for source_fps, output_fps, container in (
                    (24, 30, 'mp4'), (30, 24, 'mp4'), (15, 10, 'mp4'), (60, 30, 'mp4'),
                    (24, 30, 'mkv'), (30, 24, 'mkv'), (15, 10, 'mkv'), (60, 30, 'mkv')):
                with self.subTest(source_fps=source_fps, output_fps=output_fps, container=container):
                    raw = root / f'{source_fps}-{output_fps}-{container}.gray'
                    raw.write_bytes(b''.join(bytes([value]) * (width * height) for value in values))
                    source = root / f'{source_fps}-{output_fps}-source.{container}'
                    encoder = (['-c:v', 'ffv1'] if container == 'mkv' else
                               ['-c:v', 'libx264', '-crf', '0', '-pix_fmt', 'yuv420p',
                                '-video_track_timescale', '120000'])
                    subprocess.run(['ffmpeg', '-v', 'error', '-nostdin', '-y', '-f', 'rawvideo',
                                    '-pix_fmt', 'gray', '-s', f'{width}x{height}', '-r', str(source_fps),
                                    '-i', str(raw), *encoder, str(source)], check=True)
                    asset = {'asset_id': 'synthetic', 'kind': 'video', 'path': str(source),
                             'sha256': hashlib.sha256(source.read_bytes()).hexdigest()}
                    decoded_source = subprocess.check_output(['ffmpeg', '-v', 'error', '-nostdin',
                        '-i', str(source), '-map', '0:v:0', '-f', 'rawvideo', '-pix_fmt', 'gray', 'pipe:1'])
                    self.assertEqual([min(range(source_count), key=lambda j: abs(
                        decoded_source[i * width * height] - values[j])) for i in range(source_count)],
                        list(range(source_count)))
                    edl = {'version': 4, 'edit_basis': 'visual', 'status': 'proposed',
                           'sequence': [{'id': 'clip', 'asset_id': 'synthetic', 'source_start': 0,
                                         'source_end': str(Fraction(source_count, source_fps)),
                                         'reason': 'Check real frame selection'}]}
                    output = root / f'{source_fps}-{output_fps}-{container}.mp4'
                    rendered = render_visual_edl(edl, [asset], output, fps=f'{output_fps}/1')
                    source_frames = conform_source_frames(0, source_count, str(source_fps),
                                                          rendered['frame_count'], rendered['fps'])
                    self.assertEqual(rendered['frame_mapping'][0]['source_frame_map'], source_frames)
                    row = {**rendered['frame_mapping'][0], 'source_path': str(source),
                           'source_sha256': asset['sha256'], 'source_frame_map': source_frames}
                    original = {'version': 4, 'edit_basis': 'visual', 'duration': rendered['duration'],
                                'frame_count': rendered['frame_count'], 'fps': rendered['fps'],
                                'sequence': [row]}
                    mapped = remap_visual_mapping(original, compile_retime(
                        rendered['frame_count'], rendered['fps'], []))
                    pixels = subprocess.check_output(['ffmpeg', '-v', 'error', '-nostdin',
                                                       '-i', str(output), '-map', '0:v:0',
                                                       '-f', 'rawvideo', '-pix_fmt', 'gray', 'pipe:1'])
                    frame_size = width * height
                    self.assertEqual(len(pixels), rendered['frame_count'] * frame_size)
                    means = [sum(pixels[frame * frame_size:(frame + 1) * frame_size]) / frame_size
                             for frame in range(rendered['frame_count'])]
                    observed = [min(range(source_count), key=lambda i: abs(means[frame] - values[i]))
                        for frame in range(rendered['frame_count'])]
                    self.assertEqual([ref['source_frame'] for ref in mapped['retime']['frames']], observed,
                                     f'output gray means: {means}')

    def test_old_mapping_requires_measured_conform_and_rejects_invalid_map(self):
        original = mapping()
        original['sequence'][0].pop('source_frame_map')
        with self.assertRaisesRegex(ValueError, 'needs source_frame_map'):
            remap_visual_mapping(original, compile_retime(9, '30/1', []))
        original = mapping()
        original['sequence'][0]['source_frame_map'] = [10, 11]
        with self.assertRaisesRegex(ValueError, 'source_frame_map is invalid'):
            remap_visual_mapping(original, compile_retime(9, '30/1', []))
        original = mapping()
        original['sequence'][0]['source_frame_map'] = [10, 11, 10, 11, 12, 12]
        with self.assertRaisesRegex(ValueError, 'source_frame_map is invalid'):
            remap_visual_mapping(original, compile_retime(9, '30/1', []))

    def test_multisource_different_fps_and_identity_binding(self):
        original = mapping()
        before = deepcopy(original)
        compiled = compile_retime(9, '30/1', [])
        result = remap_visual_mapping(original, compiled)
        self.assertEqual(original, before)
        self.assertEqual(result['metadata'], before['metadata'])
        self.assertEqual(result['retime']['input_mapping_sha256'], digest(before))
        self.assertEqual(result['retime']['compiled_mapping'], compiled)
        refs = result['retime']['frames']
        self.assertEqual([(r['asset_id'], r['source_frame']) for r in refs],
                         [('a', 10), ('a', 10), ('a', 11), ('a', 11), ('a', 12), ('a', 12),
                          ('b', 20), ('b', 22), ('b', 24)])
        self.assertEqual([r['base_output_frame'] for r in refs], list(range(9)))
        self.assertEqual([r['source_sha256'] for r in refs[:6]], ['a' * 64] * 6)
        self.assertEqual([r['source_path'] for r in refs[6:]], ['/media/b.mp4'] * 3)
        self.assertEqual([(r['output_first_frame'], r['output_end_frame_exclusive'])
                          for r in result['sequence']],
                         [(0, 1), (1, 3), (3, 5), (5, 6), (6, 7), (7, 8), (8, 9)])
        self.assertEqual(result['sequence'][4]['source_start'], '1/3s')
        self.assertEqual(result['sequence'][4]['output_start'], '1/5s')

    def test_freeze_duplicate_and_fast_ramp_skip_split_rows(self):
        original = {'version': 4, 'edit_basis': 'visual', 'duration': 0.4,
                    'frame_count': 10, 'fps': '25/1',
                    'sequence': [{**source_row('a', '/a', 'a' * 64, '25/1', 4, 14, 0, 10),
                                  'output_fps': '25/1'}]}
        compiled = compile_retime(10, '25/1', [
            {'id': 'hold', 'kind': 'freeze', 'source_frame': 3, 'output_frames': 2,
             'reason': 'hold'},
            {'id': 'fast', 'kind': 'ramp', 'source_first_frame': 6,
             'source_end_frame_exclusive': 10, 'speed_start': 2, 'speed_end': 2,
             'reason': 'faster'}])
        result = remap_visual_mapping(original, compiled)
        self.assertEqual(compiled['frame_map'], [0, 1, 2, 3, 3, 3, 4, 5, 6, 8])
        self.assertEqual([r['source_frame'] for r in result['retime']['frames']],
                         [4, 5, 6, 7, 7, 7, 8, 9, 10, 12])
        self.assertEqual([(r['source_first_frame'], r['source_end_frame_exclusive'],
                           r['output_first_frame'], r['output_end_frame_exclusive'])
                          for r in result['sequence']],
                         [(4, 8, 0, 4), (7, 8, 4, 5), (7, 11, 5, 9), (12, 13, 9, 10)])
        self.assertEqual(result['duration'], 0.4)

    def test_rejects_stale_dimensions_fps_and_invalid_coverage(self):
        original = mapping()
        compiled = compile_retime(9, '30/1', [])
        stale = deepcopy(compiled)
        stale['input_frame_count'] = 8
        with self.assertRaisesRegex(ValueError, 'dimensions'):
            remap_visual_mapping(original, stale)
        stale = deepcopy(compiled)
        stale['fps'] = '24/1'
        with self.assertRaisesRegex(ValueError, 'fps'):
            remap_visual_mapping(original, stale)
        for frames in ([0, 2, 1], [0, 9], [True, 1]):
            stale = deepcopy(compiled)
            stale['frame_map'] = frames
            stale['output_frame_count'] = len(frames)
            with self.subTest(frames=frames), self.assertRaisesRegex(ValueError, 'indices'):
                remap_visual_mapping(original, stale)
        for bad_first in (5, 7):
            stale = mapping()
            stale['sequence'][1]['output_first_frame'] = bad_first
            with self.subTest(bad_first=bad_first), self.assertRaisesRegex(ValueError, 'gap, overlap'):
                remap_visual_mapping(stale, compiled)
        stale = mapping()
        stale['sequence'][-1]['output_end_frame_exclusive'] = 8
        stale['sequence'][-1]['source_frame_map'] = [20, 22]
        with self.assertRaisesRegex(ValueError, 'cover frame_count'):
            remap_visual_mapping(stale, compiled)
        stale = mapping()
        stale['duration'] = 1.0
        with self.assertRaisesRegex(ValueError, 'duration differs'):
            remap_visual_mapping(stale, compiled)
        stale = mapping()
        stale['sequence'][0]['output_fps'] = '24/1'
        with self.assertRaisesRegex(ValueError, 'output fps differs'):
            remap_visual_mapping(stale, compiled)


if __name__ == '__main__':
    unittest.main()
