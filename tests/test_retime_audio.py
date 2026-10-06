import unittest
from pathlib import Path
import shutil
import tempfile
from unittest.mock import patch

import numpy as np

from video_harness.retime_audio import retime_audio
from video_harness.time_mapping import compile_retime


SR = 8000
FPS = "25/1"
FRAME_SAMPLES = SR // 25


def tone(frame_count: int, hz: float = 440.0) -> np.ndarray:
    t = np.arange(frame_count * FRAME_SAMPLES, dtype=np.float64) / SR
    return np.stack((.4 * np.sin(2 * np.pi * hz * t),
                     .2 * np.sin(2 * np.pi * hz * t)), axis=1).astype(np.float32)


def ramp(first, end, start, finish):
    return {"id": "ramp", "kind": "ramp", "source_first_frame": first,
            "source_end_frame_exclusive": end, "speed_start": start,
            "speed_end": finish, "reason": "test"}


def dominant_frequency(values: np.ndarray) -> float:
    window = np.hanning(len(values))
    spectrum = np.abs(np.fft.rfft(values * window))
    return float(np.fft.rfftfreq(len(values), 1 / SR)[np.argmax(spectrum[1:]) + 1])


class RetimeAudioTests(unittest.TestCase):
    def test_identity_copies_all_samples_without_optional_dependency(self):
        source = tone(50)
        output, evidence = retime_audio(source, SR, compile_retime(50, FPS, []))
        np.testing.assert_array_equal(output, source)
        self.assertEqual(output.dtype, np.float32)
        self.assertEqual(evidence["output_samples"], len(source))

    def test_constant_ramps_preserve_tone_pitch_and_exact_length(self):
        for speed in (.5, 2):
            with self.subTest(speed=speed):
                source = tone(100)
                mapping = compile_retime(100, FPS, [ramp(10, 90, speed, speed)])
                output, evidence = retime_audio(source, SR, mapping)
                self.assertEqual(len(output), mapping["output_frame_count"] * FRAME_SAMPLES)
                self.assertEqual(evidence["spans"][0]["method"], "nonuniform_phase_vocoder")
                first = mapping["spans"][0]["output_first_frame"] * FRAME_SAMPLES
                end = mapping["spans"][0]["output_end_frame_exclusive"] * FRAME_SAMPLES
                center = output[first + 4 * FRAME_SAMPLES:end - 4 * FRAME_SAMPLES]
                self.assertLess(abs(dominant_frequency(center[:, 0]) - 440), 12)
                self.assertLess(abs(dominant_frequency(center[:, 1]) - 440), 12)
                # Stereo channels retain one shared source-time map.
                np.testing.assert_allclose(center[:, 1], center[:, 0] * .5, atol=.01)
                np.testing.assert_array_equal(output[:first], source[:first])
                suffix_length = (100 - 90) * FRAME_SAMPLES
                np.testing.assert_array_equal(output[-suffix_length:], source[-suffix_length:])

    def test_varying_ramp_follows_compiler_duration(self):
        source = tone(100)
        mapping = compile_retime(100, FPS, [ramp(10, 90, .5, 1.5)])
        output, evidence = retime_audio(source, SR, mapping)
        self.assertEqual(len(output), mapping["output_frame_count"] * FRAME_SAMPLES)
        self.assertTrue(np.isfinite(output).all())
        self.assertGreater(np.max(np.abs(output)), .1)
        self.assertEqual(evidence["spans"][0]["method"], "nonuniform_phase_vocoder")

    @unittest.skipUnless(shutil.which("rubberband"), "rubberband CLI unavailable")
    def test_rubberband_constant_fast_ramp_preserves_pitch_and_logs(self):
        source = tone(100)
        mapping = compile_retime(100, FPS, [ramp(10, 90, 2, 2)])
        with tempfile.TemporaryDirectory() as temporary:
            output, evidence = retime_audio(source, SR, mapping, backend="rubberband",
                                            log_dir=temporary)
            detail = evidence["spans"][0]
            self.assertEqual(detail["method"], "rubberband_r3_timemap")
            self.assertTrue(detail["tool_version"])
            self.assertEqual(len(detail["anchor_sha256"]), 64)
            self.assertGreater(detail["anchor_count"], 2)
            self.assertTrue((Path(detail["log_dir"]) / "command.txt").exists())
            self.assertTrue((Path(detail["log_dir"]) / "stderr.txt").exists())
            first = 10 * FRAME_SAMPLES
            end = 50 * FRAME_SAMPLES
            center = output[first + 4 * FRAME_SAMPLES:end - 4 * FRAME_SAMPLES]
            self.assertLess(abs(dominant_frequency(center[:, 0]) - 440), 12)
            self.assertEqual(len(output), 60 * FRAME_SAMPLES)
            np.testing.assert_array_equal(output[:first], source[:first])
            np.testing.assert_array_equal(output[-10 * FRAME_SAMPLES:],
                                          source[-10 * FRAME_SAMPLES:])

    @unittest.skipUnless(shutil.which("rubberband"), "rubberband CLI unavailable")
    def test_rubberband_varying_ramp_exact_duration(self):
        source = tone(100)
        mapping = compile_retime(100, FPS, [ramp(10, 90, .5, 1.5)])
        output, evidence = retime_audio(source, SR, mapping, backend="rubberband")
        self.assertEqual(len(output), mapping["output_frame_count"] * FRAME_SAMPLES)
        self.assertTrue(np.isfinite(output).all())
        self.assertGreater(np.max(np.abs(output)), .1)
        self.assertEqual(evidence["spans"][0]["method"], "rubberband_r3_timemap")
        self.assertEqual(evidence["spans"][0]["sample_adjustment"], 0)

    def test_requested_rubberband_does_not_fall_back(self):
        mapping = compile_retime(30, FPS, [ramp(5, 25, 2, 2)])
        with patch("video_harness.retime_audio.shutil.which", return_value=None):
            with self.assertRaisesRegex(RuntimeError, "executable is unavailable"):
                retime_audio(tone(30), SR, mapping, backend="rubberband")

    def test_freeze_is_silence_then_source_resumes(self):
        source = tone(30)
        mapping = compile_retime(30, FPS, [{"id": "hold", "kind": "freeze",
                                            "source_frame": 10, "output_frames": 5,
                                            "reason": "test"}])
        output, evidence = retime_audio(source, SR, mapping)
        self.assertEqual(len(output), 35 * FRAME_SAMPLES)
        np.testing.assert_array_equal(output[:10 * FRAME_SAMPLES], source[:10 * FRAME_SAMPLES])
        np.testing.assert_array_equal(output[10 * FRAME_SAMPLES:15 * FRAME_SAMPLES], 0)
        np.testing.assert_array_equal(output[15 * FRAME_SAMPLES:], source[10 * FRAME_SAMPLES:])
        self.assertEqual(evidence["freeze_audio_policy"],
                         "inserted_silence_then_resume_source_pcm")

    def test_fractional_fps_has_exact_output_sample_count(self):
        fps = "30000/1001"
        frames = 60
        source_count = round(frames * SR * 1001 / 30000)
        source = np.zeros((source_count, 1), dtype=np.float32)
        mapping = compile_retime(frames, fps, [ramp(8, 40, 2, 2)])
        output, _ = retime_audio(source, SR, mapping)
        self.assertEqual(len(output), round(mapping["output_frame_count"] * SR * 1001 / 30000))

    def test_rejects_short_source_and_nonfinite_samples(self):
        mapping = compile_retime(30, FPS, [])
        with self.assertRaisesRegex(ValueError, "too short"):
            retime_audio(np.zeros((10, 1), dtype=np.float32), SR, mapping)
        source = tone(30)
        source[0, 0] = np.nan
        with self.assertRaisesRegex(ValueError, "finite"):
            retime_audio(source, SR, mapping)
        with self.assertRaisesRegex(ValueError, "at least one sample"):
            retime_audio(np.zeros((0, 1), dtype=np.float32), SR, mapping)

    def test_short_ramp_rejected_and_clipping_count_reported(self):
        source = np.full((30 * FRAME_SAMPLES, 1), 1.2, dtype=np.float32)
        output, evidence = retime_audio(source, SR, compile_retime(30, FPS, []))
        self.assertEqual(evidence["samples_over_full_scale"], output.size)
        tiny = np.zeros((12, 1), dtype=np.float32)
        tiny_mapping = compile_retime(6, "4000/1", [ramp(1, 5, .5, .5)])
        with self.assertRaisesRegex(ValueError, "fewer than 64 source samples"):
            retime_audio(tiny, SR, tiny_mapping)


if __name__ == "__main__":
    unittest.main()
