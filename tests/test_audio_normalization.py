import hashlib
import json
import struct
import tempfile
import unittest
import wave
from pathlib import Path
from unittest.mock import patch

import numpy as np

from video_harness.audio_normalization import prove_scalar_normalization


def pcm16(path, samples, rate=48000):
    with wave.open(str(path), "wb") as stream:
        stream.setparams((2, 2, rate, 0, "NONE", "not compressed"))
        stream.writeframes((np.clip(samples, -1, 1) * 32767).astype("<i2").tobytes())


def float32_wav(path, samples, rate=48000):
    """Write a minimal IEEE-float stereo WAV without another audio library."""
    payload = np.asarray(samples, dtype="<f4").tobytes()
    format_chunk = struct.pack("<HHIIHH", 3, 2, rate, rate * 8, 8, 32)
    body = b"WAVE" + b"fmt " + struct.pack("<I", len(format_chunk)) + format_chunk
    body += b"data" + struct.pack("<I", len(payload)) + payload
    path.write_bytes(b"RIFF" + struct.pack("<I", len(body)) + body)


class AudioNormalizationTests(unittest.TestCase):
    def test_float_wav_exact_common_scalar(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            t = np.arange(2400) / 48000
            source = np.column_stack((.3 * np.sin(2 * np.pi * 220 * t),
                                      .2 * np.cos(2 * np.pi * 330 * t))).astype(np.float32)
            float32_wav(root / "in.wav", source)
            float32_wav(root / "out.wav", source * .7)
            proof = prove_scalar_normalization(root / "in.wav", root / "out.wav")
            self.assertEqual(proof["status"], "verified_scalar")
            self.assertAlmostEqual(proof["scalar_gain"], .7, places=6)
            self.assertLessEqual(proof["max_absolute_error"], proof["absolute_error_tolerance"])
            self.assertEqual(proof["samples"], 2400)
            self.assertEqual(proof["input"]["sha256"], hashlib.sha256((root / "in.wav").read_bytes()).hexdigest())
            self.assertNotIn(str(root), json.dumps(proof))

    def test_pcm16_quantization_bounded_at_explicit_tolerance(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = np.tile(np.array([[.2, -.4], [.3, -.1]], dtype=np.float32), (600, 1))
            pcm16(root / "in.wav", source)
            pcm16(root / "out.wav", source * .5)
            proof = prove_scalar_normalization(root / "in.wav", root / "out.wav", absolute_error=3e-5)
            self.assertEqual(proof["status"], "verified_scalar")
            self.assertLessEqual(proof["max_absolute_error"], 3e-5)

    def test_channel_specific_and_clipping_are_non_scalar(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = np.tile(np.array([[.7, -.7], [.4, -.4]], dtype=np.float32), (500, 1))
            float32_wav(root / "in.wav", source)
            alternate = source.copy()
            alternate[:, 0] *= .5
            alternate[:, 1] *= .8
            float32_wav(root / "channel.wav", alternate)
            proof = prove_scalar_normalization(root / "in.wav", root / "channel.wav")
            self.assertEqual(proof["status"], "non_scalar")
            self.assertGreater(proof["max_absolute_error"], proof["absolute_error_tolerance"])
            float32_wav(root / "clip.wav", np.clip(source * 2, -1, 1))
            proof = prove_scalar_normalization(root / "in.wav", root / "clip.wav")
            self.assertEqual(proof["status"], "non_scalar")

    def test_rejects_mismatched_length_and_native_rate(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pcm16(root / "in.wav", np.zeros((100, 2)))
            pcm16(root / "short.wav", np.zeros((99, 2)))
            with self.assertRaisesRegex(ValueError, "sample counts"):
                prove_scalar_normalization(root / "in.wav", root / "short.wav")
            pcm16(root / "wrong-rate.wav", np.zeros((100, 2)), rate=44100)
            with self.assertRaisesRegex(ValueError, "native 48 kHz"):
                prove_scalar_normalization(root / "in.wav", root / "wrong-rate.wav")

    def test_source_changed_during_decode_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pcm16(root / "in.wav", np.ones((100, 2)) * .1)
            pcm16(root / "out.wav", np.ones((100, 2)) * .1)
            from video_harness import audio_mix
            decode = audio_mix._decode

            def changed_decode(path):
                data = decode(path)
                if Path(path) == root / "in.wav":
                    with Path(path).open("ab") as stream:
                        stream.write(b"changed")
                return data

            with patch.object(audio_mix, "_decode", side_effect=changed_decode):
                with self.assertRaisesRegex(ValueError, "changed during decode"):
                    prove_scalar_normalization(root / "in.wav", root / "out.wav")

    def test_silence_has_unity_only_if_output_silent(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            zero = np.zeros((100, 2), dtype=np.float32)
            pcm16(root / "in.wav", zero)
            pcm16(root / "zero.wav", zero)
            pcm16(root / "sound.wav", np.full_like(zero, .1))
            proof = prove_scalar_normalization(root / "in.wav", root / "zero.wav")
            self.assertEqual((proof["status"], proof["scalar_gain"]), ("verified_scalar", 1.0))
            proof = prove_scalar_normalization(root / "in.wav", root / "sound.wav")
            self.assertEqual((proof["status"], proof["scalar_gain"]), ("non_scalar", None))
