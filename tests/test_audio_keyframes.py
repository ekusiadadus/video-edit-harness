import math
import unittest
from fractions import Fraction

import numpy as np

from video_harness.audio_keyframes import compile_gain_keyframes


def reconstruct(result):
    """Model the claimed FCPXML linear-in-dB interpolation at every sample."""
    points = result["keyframes"]
    output = np.empty(result["samples"], dtype=np.float64)
    for left, right in zip(points, points[1:]):
        first, end = left["sample"], right["sample"]
        db_first = float(left["value"][:-2])
        db_last = float(right["value"][:-2])
        fraction = np.arange(end - first + 1, dtype=np.float64) / (end - first)
        output[first:end + 1] = 10 ** ((db_first + (db_last - db_first) * fraction) / 20)
    if len(points) == 1:
        output[0] = 10 ** (float(points[0]["value"][:-2]) / 20)
    return output


class AudioKeyframeTests(unittest.TestCase):
    def assert_bounded(self, curve, result, tolerance=2e-5):
        measured = float(np.max(np.abs(reconstruct(result) - curve)))
        self.assertLessEqual(measured, tolerance + 1e-12)
        self.assertAlmostEqual(result["max_absolute_gain_error"], measured, places=12)

    def test_unity_uses_endpoints(self):
        curve = np.ones(4800, dtype=np.float32)
        result = compile_gain_keyframes(curve)
        self.assertEqual([row["sample"] for row in result["keyframes"]], [0, 4799])
        self.assertEqual([row["value"] for row in result["keyframes"]], ["0.000000dB"] * 2)
        self.assertEqual(result["keyframes"][0]["time"], "0s")
        self.assertEqual(result["keyframes"][-1]["time"], "4799/48000s")
        self.assert_bounded(curve, result)

    def test_zero_floor_has_explicit_approximation_error(self):
        curve = np.zeros(120, dtype=np.float32)
        result = compile_gain_keyframes(curve)
        self.assertEqual(result["zero_floor_db"], -96)
        self.assertEqual(result["keyframes"][0]["value"], "-96.000000dB")
        self.assertGreater(result["max_absolute_gain_error"], 0)
        self.assert_bounded(curve, result)
        with self.assertRaisesRegex(ValueError, "floor"):
            compile_gain_keyframes(curve, absolute_error=1e-6)

    def test_fade_is_bounded_at_every_sample(self):
        curve = np.linspace(0, 1, 1200, dtype=np.float32)
        result = compile_gain_keyframes(curve)
        self.assertGreater(len(result["keyframes"]), 2)
        self.assert_bounded(curve, result)

    def test_step_duck_keeps_neighbor_samples(self):
        curve = np.r_[np.full(180, .7), np.full(220, .25)].astype(np.float32)
        result = compile_gain_keyframes(curve)
        indices = {row["sample"] for row in result["keyframes"]}
        self.assertIn(179, indices)
        self.assertIn(180, indices)
        self.assert_bounded(curve, result)

    def test_loop_seam_retains_short_dip(self):
        curve = np.ones(500, dtype=np.float32)
        curve[237:251] = np.linspace(1, 0, 14, dtype=np.float32)
        curve[251:265] = np.linspace(0, 1, 14, dtype=np.float32)
        result = compile_gain_keyframes(curve)
        indices = {row["sample"] for row in result["keyframes"]}
        self.assertIn(250, indices)
        self.assertIn(251, indices)
        self.assert_bounded(curve, result)

    def test_rational_source_clock_and_scalar_gain(self):
        curve = np.full(3, .5, dtype=np.float32)
        result = compile_gain_keyframes(curve, source_start=Fraction(1, 3), scalar_gain=.5)
        self.assertEqual(result["keyframes"][0]["time"], "1/3s")
        self.assertEqual(Fraction(result["keyframes"][-1]["time"][:-1]), Fraction(8001, 24000))
        self.assertEqual(result["scalar_gain"], .5)
        self.assert_bounded(curve * .5, result)

    def test_near_floor_and_quantization_threshold(self):
        curve = np.array([0, .00001, .00002, .00003], dtype=np.float32)
        result = compile_gain_keyframes(curve)
        self.assert_bounded(curve, result)
        with self.assertRaises(ValueError):
            compile_gain_keyframes(curve, absolute_error=1e-8)

    def test_rejects_complexity_and_bad_input(self):
        jagged = np.tile(np.array([.1, .9], dtype=np.float32), 30)
        with self.assertRaisesRegex(ValueError, "max_keyframes"):
            compile_gain_keyframes(jagged, max_keyframes=3)
        for curve in ([], [[1, 2]], [float("nan")], [-1], [float("inf")]):
            with self.subTest(curve=curve), self.assertRaises(ValueError):
                compile_gain_keyframes(curve)
        with self.assertRaisesRegex(ValueError, "sample rate"):
            compile_gain_keyframes([1], sample_rate=44100)
        with self.assertRaisesRegex(ValueError, "limit"):
            compile_gain_keyframes([10 ** (24.01 / 20)])
        with self.assertRaises(ValueError):
            compile_gain_keyframes([1], scalar_gain=math.inf)
