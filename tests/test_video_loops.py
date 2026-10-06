"""Synthetic picture and provenance checks for looping video overlays."""

from fractions import Fraction
from pathlib import Path
import hashlib
import subprocess
import tempfile
import unittest

import numpy as np

from video_harness.video_cue_phase import video_cue_content_sha256
from video_harness.visual import render_overlays


WIDTH, HEIGHT = 160, 90
COLORS = [(220, 20, 20), (20, 220, 20), (20, 20, 220),
          (220, 220, 20), (220, 20, 220), (20, 220, 220)]


def ffmpeg(*args, input_bytes=None):
    subprocess.run(['ffmpeg', '-v', 'error', '-nostdin', '-y', *map(str, args)],
                   input=input_bytes, stdout=subprocess.DEVNULL,
                   stderr=subprocess.PIPE, check=True)


def source_video(path, fps, *, alpha=False):
    frames = np.zeros((len(COLORS), 48, 64, 4), np.uint8)
    for index, color in enumerate(COLORS):
        frames[index, :, :, :3] = color
        frames[index, :, :, 3] = 128 if alpha else 255
    ffmpeg('-f', 'rawvideo', '-pixel_format', 'rgba',
           '-video_size', '64x48', '-framerate', fps, '-i', 'pipe:0',
           '-frames:v', len(frames), '-c:v', 'ffv1',
           '-pix_fmt', 'bgra', path,
           input_bytes=frames.tobytes())


def primary(path, fps):
    ffmpeg('-f', 'lavfi', '-i', f'color=c=black:s={WIDTH}x{HEIGHT}:r={fps}:d=1',
           '-f', 'lavfi', '-i', 'sine=frequency=440:sample_rate=48000:duration=1',
           '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-c:a', 'aac',
           '-t', '1', path)


def registered(path):
    return {'asset_id': 'secondary', 'kind': 'video', 'path': str(path),
            'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}


def pictures(path):
    raw = subprocess.check_output(['ffmpeg', '-v', 'error', '-nostdin',
                                   '-i', str(path), '-map', '0:v:0',
                                   '-f', 'rawvideo', '-pix_fmt', 'rgb24', 'pipe:1'])
    return np.frombuffer(raw, np.uint8).reshape(-1, HEIGHT, WIDTH, 3)


def pcm(path):
    return subprocess.check_output(['ffmpeg', '-v', 'error', '-nostdin',
                                    '-i', str(path), '-map', '0:a:0',
                                    '-f', 's16le', 'pipe:1'])


def cue(fps, *, first=3, count=13, source_fps=30):
    rate = Fraction(fps)
    source_rate = Fraction(source_fps)
    return {'id': 'loop', 'asset_id': 'secondary', 'role': 'video',
            'output_start': str(Fraction(first, 1) / rate),
            'output_end': str(Fraction(first + count, 1) / rate),
            'source_start': str(Fraction(1, 1) / source_rate),
            'source_end': str(Fraction(4, 1) / source_rate),
            'position': 'center', 'opacity': 1, 'loop': True}


class VideoLoopTests(unittest.TestCase):
    def test_loop_keeps_varying_primary_frame_identity_outside_overlay(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            base, source, output = root/'base.mp4', root/'source.mkv', root/'loop.mp4'
            primary_frames = np.empty((30, HEIGHT, WIDTH, 3), dtype=np.uint8)
            for index in range(30):
                primary_frames[index] = 35 if index % 2 == 0 else 190
            ffmpeg('-f', 'rawvideo', '-pixel_format', 'rgb24', '-video_size', f'{WIDTH}x{HEIGHT}',
                '-framerate', '30', '-i', 'pipe:0', '-f', 'lavfi', '-i', 'sine=frequency=440:sample_rate=48000:duration=1',
                '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-t', '1', base,
                input_bytes=primary_frames.tobytes())
            source_video(source, '30')
            render_overlays(base, [cue('30')], [registered(source)], output, 1)
            before, after = pictures(base), pictures(output)
            self.assertEqual(len(before), len(after))
            difference = np.abs(before[:, :10, :10].astype(int)-after[:, :10, :10].astype(int))
            self.assertLess(float(np.mean(difference)), 4)
            self.assertEqual(pcm(base), pcm(output))

    def test_editable_fcp_rejects_unrepresented_visual_fades(self):
        from video_harness.production_fcp import export_production_xml
        with tempfile.TemporaryDirectory() as tmp:
            for role in ('video', 'image', 'title'):
                with self.subTest(role=role), self.assertRaisesRegex(ValueError, 'Visual cue fades'):
                    export_production_xml('/unused.fcpxml', {'cues': [{'role': role, 'fade_in': '1/10'}]},
                        None, Path(tmp)/(role+'.fcpxml'), mode='editable')

    def test_loop_fades_are_baked_once_and_retimed_samples_keep_alpha(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            base, source = root/'base.mp4', root/'source.mkv'
            primary(base, '30')
            source_video(source, '30')
            plan = dict(cue('30'), fade_in='1/5', fade_out='1/5', opacity=.5)
            original = root/'faded.mp4'
            result = render_overlays(base, [plan], [registered(source)], original, 1)
            frames = pictures(original)
            center = frames[:, 43, 80].astype(int)
            self.assertLess(center[3].max(), 10)
            for frame, factor in ((4, 1/12), (5, 1/6), (6, .25), (9, .5), (10, .5), (13, .25), (14, 1/6), (15, 1/12)):
                expected = np.array(COLORS[1+(frame-3)%3])*factor
                self.assertLess(float(np.mean(np.abs(center[frame]-expected))), 16)
            clock = result['video_cue_clocks'][0]
            selected = [0, 3, 9, 12]
            phase = {'version': 2, 'original_start_frame': 3, 'original_frame_count': 13,
                'original_layer': clock['original_layer'], 'original_cue_sha256': clock['original_cue_sha256'], 'frames': selected}
            mapped = dict(plan, output_start='1/2', output_end='19/30', phase_map=phase)
            retimed = root/'retimed.mp4'
            render_overlays(base, [mapped], [registered(source)], retimed, 1)
            replay = pictures(retimed)
            for index, old_index in enumerate(selected):
                difference = np.abs(replay[15+index,40:48,75:85].astype(int)-frames[3+old_index,40:48,75:85].astype(int))
                self.assertLess(float(np.mean(difference)), 8)
            with self.assertRaisesRegex(ValueError, 'baked placement changed'):
                render_overlays(base, [dict(mapped, fade_in='1/15')], [registered(source)], root/'stale.mp4', 1)

    def test_image_and_title_fades_are_applied_on_output_clock(self):
        from PIL import Image
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            base = root/'base.mp4'
            primary(base, '30')
            image = root/'image.png'
            Image.new('RGBA', (64, 48), (220, 30, 30, 128)).save(image)
            for role in ('image', 'title'):
                with self.subTest(role=role):
                    plan = {'id': role, 'role': role, 'output_start': '1/10',
                        'output_end': '8/15', 'fade_in': '1/10', 'fade_out': '1/10', 'opacity': .5}
                    if role == 'image':
                        plan['asset_id'] = 'secondary'
                        assets = [{**registered(image), 'kind': 'image'}]
                    else:
                        plan['text'] = 'MOVE'
                        assets = []
                    output = root/(role+'.mp4')
                    render_overlays(base, [plan], assets, output, 1)
                    frames = pictures(output)
                    self.assertLess(int(frames[3].max()), 10)
                    self.assertLess(int(frames[16].max()), 10)
                    self.assertGreater(float(frames[6].mean()), 1.5*float(frames[4].mean()))
                    self.assertGreater(int(frames[6].max()), 40)
                    self.assertEqual(pcm(base), pcm(output))

    def test_trimmed_frames_repeat_at_seams_with_exact_half_open_window_and_audio(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            base, source, output = (root / name for name in ('base.mp4', 'source.mkv', 'loop.mp4'))
            primary(base, '30')
            source_video(source, '30')
            plan = cue('30')
            result = render_overlays(base, [plan], [registered(source)], output, 1)
            frames = pictures(output)
            period = result['video_loop_periods'][0]
            self.assertEqual((period['output_first_frame'], period['output_end_frame_exclusive']), (3, 16))
            self.assertEqual(period['period_frames'], 3)
            self.assertEqual(len(frames), 30)
            self.assertEqual(pcm(base), pcm(output))
            center = frames[:, 43, 80].astype(int)
            self.assertLess(int(center[2].max()), 10)
            self.assertLess(int(center[16].max()), 10)
            self.assertGreater(int(center[3].max()), 90)
            # The source trim is frames [1, 4); frame 4 must never enter the loop.
            for offset, color in enumerate(COLORS[1:4]):
                self.assertLess(float(np.mean(np.abs(center[3 + offset] - color))), 16)
            for index in range(3, 13):
                self.assertLess(float(np.mean(np.abs(center[index] - center[index + 3]))), 5)
            self.assertGreater(float(np.mean(np.abs(center[3] - center[4]))), 70)

    def test_fractional_project_clock_mixed_source_rate_and_alpha(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            base, source, output = (root / name for name in ('base.mp4', 'alpha.mkv', 'loop.mp4'))
            primary(base, '30000/1001')
            source_video(source, '24', alpha=True)
            plan = cue('30000/1001', first=4, count=15, source_fps=24)
            result = render_overlays(base, [plan], [registered(source)], output, 1)
            frames = pictures(output)
            period = result['video_loop_periods'][0]
            length = period['period_frames']
            self.assertEqual(period['fps'], '30000/1001')
            self.assertEqual(length, 4)
            self.assertEqual(len(frames), 30)
            self.assertEqual(pcm(base), pcm(output))
            center = frames[:, 43, 80].astype(int)
            self.assertLess(int(center[3].max()), 10)
            self.assertLess(int(center[19].max()), 10)
            for index in range(4, 19 - length):
                self.assertLess(float(np.mean(np.abs(center[index] - center[index + length]))), 5)
            # A 50%-alpha red/green/blue source must stay translucent on black.
            self.assertGreater(int(center[4].max()), 80)
            self.assertLess(int(center[4].max()), 160)
            for offset, source_index in enumerate((1, 2, 3, 3)):
                expected = np.array(COLORS[source_index]) * (128/255)
                self.assertLess(float(np.mean(np.abs(center[4+offset] - expected))), 16)

    def test_sealed_phase_replays_actual_old_loop_frames_and_rejects_stale_bindings(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            base, source = root / 'base.mp4', root / 'source.mkv'
            old_output, mapped_output = root / 'old.mp4', root / 'mapped.mp4'
            primary(base, '30')
            source_video(source, '30')
            asset = registered(source)
            old = cue('30', first=3, count=9)
            old_result = render_overlays(base, [old], [asset], old_output, 1)
            selected = [0, 0, 2, 3, 3, 5, 6, 8, 8]
            clock = old_result['video_cue_clocks'][0]
            phase = {'version': 2, 'original_start_frame': 3,
                     'original_frame_count': 9,
                     'original_layer': clock['original_layer'],
                     'original_cue_sha256': clock['original_cue_sha256'],
                     'frames': selected}
            mapped = {**old, 'output_start': '15/30', 'output_end': '24/30',
                      'phase_map': phase}
            result = render_overlays(base, [mapped], [asset], mapped_output, 1)
            self.assertEqual(result['video_phase_layers'][0]['frame_count'], len(selected))
            self.assertEqual(pcm(old_output), pcm(mapped_output))
            old_frames, new_frames = pictures(old_output), pictures(mapped_output)
            for index, old_index in enumerate(selected):
                difference = np.abs(old_frames[3 + old_index, 40:48, 75:85].astype(int)
                                    - new_frames[15 + index, 40:48, 75:85].astype(int))
                self.assertLess(float(np.mean(difference)), 8)
            self.assertLess(int(new_frames[14, 43, 80].max()), 10)
            self.assertLess(int(new_frames[24, 43, 80].max()), 10)
            with self.assertRaisesRegex(ValueError, 'source too short without loop|baked placement changed'):
                render_overlays(base, [{**mapped, 'loop': False}], [asset], root / 'no-loop.mp4', 1)
            with self.assertRaisesRegex(ValueError, 'baked placement changed'):
                render_overlays(base, [{**mapped, 'source_start': '0'}], [asset], root / 'new-trim.mp4', 1)
            with self.assertRaisesRegex(ValueError, 'SHA-256 mismatch'):
                render_overlays(base, [mapped], [{**asset, 'sha256': '0' * 64}], root / 'new-source.mp4', 1)
            legacy = {'version': 1, 'original_start_frame': 3, 'original_frame_count': 9,
                      'original_time_base': '1/30', 'original_timestamps': list(range(3, 12)),
                      'frames': selected}
            with self.assertRaisesRegex(ValueError, 'sealed version-2'):
                render_overlays(base, [{**mapped, 'phase_map': legacy}], [asset], root / 'legacy.mp4', 1)

    def test_loop_digest_changes_only_when_loop_is_enabled(self):
        plan = cue('30')
        source_sha = 'a' * 64
        self.assertNotEqual(video_cue_content_sha256(plan, source_sha),
                            video_cue_content_sha256({**plan, 'loop': False}, source_sha))
        without = {key: value for key, value in plan.items() if key != 'loop'}
        self.assertEqual(video_cue_content_sha256(without, source_sha),
                         video_cue_content_sha256({**without, 'loop': False}, source_sha))


if __name__ == '__main__':
    unittest.main()
