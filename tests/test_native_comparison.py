"""Real encoded media verify returned-native diagnostics, not native API execution."""
from pathlib import Path
import subprocess
import tempfile
import unittest

from video_harness.native_comparison import compare_native_results


class NativeComparisonTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.folder = Path(cls.tmp.name)
        for name, color, tone, duration, offset in (
                ('base', 'blue', 440, '0.5', 0),
                ('picture', 'red', 440, '0.5', 0),
                ('audio', 'blue', 880, '0.5', 0),
                ('short', 'blue', 440, '0.25', 0),
                ('offset', 'blue', 440, '0.5', 1),
                ('silent', 'blue', None, '0.5', 0)):
            cmd = ['ffmpeg', '-v', 'error', '-nostdin', '-f', 'lavfi', '-i',
                   f'color=c={color}:s=96x96:r=24']
            if tone:
                cmd += ['-f', 'lavfi', '-i', f'sine=frequency={tone}:sample_rate=48000']
            cmd += ['-t', duration, '-c:v', 'libx264', '-pix_fmt', 'yuv420p']
            if tone:
                cmd += ['-c:a', 'aac']
            cmd += ['-output_ts_offset', str(offset), str(cls.folder/(name+'.mp4'))]
            subprocess.run(cmd, check=True, capture_output=True)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def compare(self, after, before='base'):
        output = self.folder / ('comparison-'+before+'-'+after)
        return compare_native_results(self.folder/(before+'.mp4'), self.folder/(after+'.mp4'), output)

    def test_picture_change_preserves_exact_audio_without_approval(self):
        r = self.compare('picture')
        self.assertTrue(r['audio']['pcm_equal'])
        self.assertFalse(r['picture']['reduced_picture_equal'])
        self.assertTrue(r['picture']['frame_timestamps_equal'])
        self.assertIsNone(r['picture']['whole_picture_equal'])
        for flag in ('human_whole_watch_listen', 'native_api_response_verified',
                     'source_relationship_verified', 'cross_platform_rights_verified', 'published'):
            self.assertFalse(r[flag])

    def test_audio_change_and_identical_picture(self):
        r = self.compare('audio')
        self.assertFalse(r['audio']['pcm_equal'])
        self.assertTrue(r['picture']['reduced_picture_equal'])

    def test_different_duration_or_clock_is_not_aligned(self):
        short = self.compare('short')
        self.assertFalse(short['picture']['comparable'])
        self.assertFalse(short['audio']['same_sample_count'])
        offset = self.compare('offset')
        self.assertFalse(offset['picture']['comparable'])
        self.assertFalse(offset['picture']['frame_timestamps_equal'])
        self.assertNotIn('frame_rms_difference', offset['picture'])

    def test_missing_audio_and_non_mp4_are_not_native_proof(self):
        silent = self.compare('silent', 'silent')
        self.assertFalse(silent['audio']['comparable'])
        self.assertIsNone(silent['audio']['pcm_equal'])
        playlist = self.folder/'remote.mp4'
        playlist.write_text('#EXTM3U\nhttps://example.invalid/video.ts\n')
        with self.assertRaises(subprocess.CalledProcessError):
            compare_native_results(playlist, self.folder/'base.mp4', self.folder/'reject')
