import tempfile
import unittest
import wave
from pathlib import Path

import numpy as np

from video_harness.beats import analyze_beats, map_beats, snap_cut_times


class BeatTests(unittest.TestCase):
    def test_manual_grid_trim_loop_and_protected_speech(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'click.wav'
            samples = np.zeros((48000 * 2, 2), dtype='<i2')
            for frame in (0, 24000, 48000, 72000):
                samples[frame:frame + 100] = 10000
            with wave.open(str(path), 'wb') as stream:
                stream.setparams((2, 2, 48000, 0, 'NONE', 'not compressed'))
                stream.writeframes(samples.tobytes())
            beats = analyze_beats(path, manual_beats=[0, .5, 1, 1.5])
            cue = {'id': 'm', 'output_start': 0, 'output_end': 4,
                   'source_start': 0, 'source_end': 2, 'loop': True}
            mapped = map_beats(beats, [cue], '30000/1001', [(0, .7)])
            self.assertEqual(len(mapped['beats']), 8)
            self.assertTrue(mapped['beats'][0]['protected_speech'])
            self.assertFalse(mapped['beats'][-1]['protected_speech'])
            self.assertEqual(snap_cut_times([.5], mapped, .1, .2, [(0, .7)])[0]['suggested'], .5)
            triple = map_beats(beats, [{'id': 'repeat', 'output_start': 0,
                'output_end': 6, 'source_start': 0, 'source_end': 2, 'loop': True}], 30)
            self.assertEqual([part['output_time'] for part in triple['loop_seams']], [2, 4])
            self.assertEqual(len(triple['beats']), 12)
            self.assertTrue(next(item for item in triple['beats'] if item['output_time'] == 2)['loop_seam_nearby'])
            self.assertEqual(triple['source_sha256'], beats['source_sha256'])

    def test_silence_does_not_claim_reliable_grid(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'silence.wav'
            with wave.open(str(path), 'wb') as stream:
                stream.setparams((1, 2, 48000, 0, 'NONE', 'not compressed'))
                stream.writeframes(b'\0\0' * 48000)
            result = analyze_beats(path)
            self.assertEqual(result['beats'], [])
            self.assertTrue(result['review_required'])
            shifted = analyze_beats(path, manual_bpm=120, start=.25, duration=.5)
            self.assertEqual(shifted['beats'][0], .25)
