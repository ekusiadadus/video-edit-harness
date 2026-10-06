import hashlib
import tempfile
import unittest
import wave
from pathlib import Path

import numpy as np

from video_harness.audio_mix import render_mix


def wav(path, samples, rate=48000):
    with wave.open(str(path), 'wb') as out:
        out.setparams((2, 2, rate, 0, 'NONE', 'not compressed'))
        out.writeframes((np.clip(samples, -1, 1) * 32767).astype('<i2').tobytes())


class MixTests(unittest.TestCase):
    def test_loop_speech_duck_and_exact_pcm(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            t = np.arange(48000) / 48000
            music = np.column_stack([.05 * np.sin(2 * np.pi * 220 * t)] * 2)
            speech = np.zeros((2 * 48000, 2))
            speech[:24000] = .13 * np.column_stack([np.sin(2 * np.pi * 330 * t[:24000])] * 2)
            wav(root / 'music.wav', music)
            wav(root / 'speech.wav', speech)
            asset = {'asset_id': 'm', 'kind': 'music', 'path': str(root / 'music.wav'),
                     'sha256': hashlib.sha256((root / 'music.wav').read_bytes()).hexdigest()}
            cue = {'id': 'bg', 'asset_id': 'm', 'role': 'music', 'output_start': 0,
                   'output_end': 2, 'source_start': 0, 'source_end': 1,
                   'loop': True, 'duck': True, 'fade_in': .1, 'fade_out': .1}
            evidence = render_mix(root / 'speech.wav', [cue], [asset], root / 'out.wav', 2,
                                  {'duck_hold_seconds': .4})
            self.assertEqual(evidence['samples'], 96000)
            self.assertEqual(evidence['normalization'], 'not_applied')
            self.assertTrue(evidence['cues'][0]['duck'])
            self.assertEqual(evidence['cues'][0]['loop_period_samples'], 48000)
            # The .4 s hold must terminate; otherwise the background never recovers.
            self.assertLess(evidence['duck']['active_windows'], 12)
            with wave.open(str(root / 'out.wav')) as rendered:
                self.assertEqual(rendered.getnframes(), 96000)
                self.assertEqual(rendered.getframerate(), 48000)
            silent = render_mix(None, [cue], [asset], root / 'music-only.wav', 2)
            self.assertEqual(silent['speech_rms'], 0)
