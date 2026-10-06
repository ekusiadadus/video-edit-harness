"""Synthetic MP4 finishing checks for fractional-frame retime endpoints.

These checks establish encoded timing and decode behavior, not perceptual review.
"""

from fractions import Fraction
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

from PIL import Image

from video_harness.video_effects import render_effects, resolve_effects
from video_harness.visual import render_overlays


FRAME_COUNT = 56
FPS = 30
DURATION = Fraction(FRAME_COUNT, FPS)


def run(*args):
    return subprocess.run(args, check=True, capture_output=True)


def probe(path):
    return json.loads(run('ffprobe', '-v', 'error', '-count_frames',
                          '-show_streams', '-of', 'json', str(path)).stdout)


def pcm(path):
    return run('ffmpeg', '-v', 'error', '-xerror', '-i', str(path),
               '-map', '0:a:0', '-f', 's16le', '-acodec', 'pcm_s16le',
               'pipe:1').stdout


def pixels(path):
    return run('ffmpeg', '-v', 'error', '-xerror', '-i', str(path),
               '-map', '0:v:0', '-f', 'rawvideo', '-pix_fmt', 'rgb24',
               'pipe:1').stdout


def assert_finished(test, path, expected_pcm):
    streams = probe(path)['streams']
    video = next(s for s in streams if s['codec_type'] == 'video')
    audio = next(s for s in streams if s['codec_type'] == 'audio')
    test.assertEqual(int(video['nb_read_frames']), FRAME_COUNT)
    test.assertEqual(Fraction(video['avg_frame_rate']), Fraction(FPS))
    test.assertEqual(Fraction(video['r_frame_rate']), Fraction(FPS))
    test.assertEqual((video.get('color_primaries'), video.get('color_transfer'),
                      video.get('color_space')), ('bt709', 'bt709', 'bt709'))
    test.assertEqual(Fraction(audio['duration_ts']) * Fraction(audio['time_base']), DURATION)
    test.assertEqual(audio['codec_name'], 'aac')
    test.assertEqual(int(audio['sample_rate']), 48000)
    test.assertEqual(pcm(path), expected_pcm)
    # A full decode checks every mapped video and audio packet, not just metadata.
    run('ffmpeg', '-v', 'error', '-xerror', '-i', str(path), '-f', 'null', '-')


class RetimeFinishingTests(unittest.TestCase):
    def test_overlay_then_smooth_zoom_preserves_fractional_audio_end(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / 'source.mp4'
            overlay = root / 'overlay.mp4'
            overlay_default = root / 'overlay-default.mp4'
            finished = root / 'finished.mp4'
            finished_default = root / 'finished-default.mp4'
            picture = root / 'picture.png'
            # 48 kHz timescale is intentional: 56/30 s equals 89600 samples.
            run('ffmpeg', '-v', 'error', '-nostdin', '-y',
                '-f', 'lavfi', '-i', 'testsrc2=s=256x256:r=30',
                '-f', 'lavfi', '-i',
                f'sine=frequency=440:sample_rate=48000:duration={float(DURATION)}',
                '-frames:v', str(FRAME_COUNT),
                '-vf', 'setparams=color_primaries=bt709:color_trc=bt709:colorspace=bt709',
                '-c:v', 'libx264',
                '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-ar', '48000',
                '-movie_timescale', '48000', str(source))
            before = pcm(source)
            assert_finished(self, source, before)

            Image.new('RGBA', (48, 48), 'green').save(picture)
            assets = [{'asset_id': 'picture', 'kind': 'image', 'path': str(picture),
                       'sha256': hashlib.sha256(picture.read_bytes()).hexdigest()}]
            cues = [{'id': 'photo', 'asset_id': 'picture', 'role': 'image',
                     'output_start': '0', 'output_end': '1'}]
            overlay_report = render_overlays(source, cues, assets, overlay,
                                             float(DURATION), preserve_audio_end=True)
            self.assertEqual(overlay_report['cues'], ['photo'])
            assert_finished(self, overlay, before)
            render_overlays(source, cues, assets, overlay_default, float(DURATION))
            self.assertEqual(pixels(overlay_default), pixels(overlay))

            mapping = {'fps': str(FPS), 'duration': str(DURATION), 'sequence': []}
            mapping_sha = hashlib.sha256(json.dumps(
                mapping, sort_keys=True, ensure_ascii=False,
                separators=(',', ':'), allow_nan=False).encode()).hexdigest()
            event = {'id': 'zoom', 'type': 'smooth_zoom', 'output_start': '0',
                     'output_end': str(DURATION), 'strength': .5,
                     'reason': 'Synthetic finishing endpoint',
                     'parameters': {'anchor_x': .5, 'anchor_y': .5}}
            plan = resolve_effects({'version': 1, 'mapping_sha256': mapping_sha,
                                    'events': [event]}, mapping)
            effect_report = render_effects(overlay, plan, finished,
                                           preserve_audio_end=True)
            self.assertEqual(effect_report['frame_count'], FRAME_COUNT)
            assert_finished(self, finished, before)
            render_effects(overlay, plan, finished_default)
            self.assertEqual(pixels(finished_default), pixels(finished))

    def test_preserve_audio_end_rejects_non_boolean_flags(self):
        with self.assertRaisesRegex(ValueError, 'preserve_audio_end must be boolean'):
            render_overlays('unused.mp4', [], [], 'unused-output.mp4', DURATION,
                            preserve_audio_end=1)
        with self.assertRaisesRegex(ValueError, 'preserve_audio_end must be boolean'):
            render_effects('unused.mp4', {}, 'unused-output.mp4',
                           preserve_audio_end='true')
