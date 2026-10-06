"""Pure normalized-depth visibility and encoded-RGB compositing tests."""

from unittest import TestCase
import numpy as np

from video_harness.depth_composite import compose_depth_layer, depth_visibility


class DepthCompositeTests(TestCase):
    def test_far_near_and_smoothstep_boundaries(self):
        depth = np.array([[0, .45, .475, .5, .525, .55, 1]], dtype=np.float32)
        before = depth.copy()
        visible = depth_visibility(depth, 7, 1)
        np.testing.assert_allclose(visible, [[1, 1, .84375, .5, .15625, 0, 0]], atol=1e-6)
        np.testing.assert_array_equal(depth, before)
        self.assertEqual(visible.dtype, np.float64)

    def test_composite_alpha_endpoints_strength_and_half_up_rounding(self):
        base = np.array([[[0, 0, 0], [10, 20, 30], [10, 20, 30],
                          [0, 0, 0], [0, 0, 0]]], dtype=np.uint8)
        layer = np.array([[[255, 255, 255, 255], [200, 200, 200, 255],
                           [200, 200, 200, 0], [255, 255, 255, 255],
                           [255, 255, 255, 255]]], dtype=np.uint8)
        depth = np.array([[0, 1, 0, .5, 0]], dtype=np.float32)
        originals = (base.copy(), layer.copy(), depth.copy())
        result = compose_depth_layer(base, depth, layer)
        np.testing.assert_array_equal(result[0, 0], [255, 255, 255])  # far, opaque
        np.testing.assert_array_equal(result[0, 1], base[0, 1])       # near, opaque
        np.testing.assert_array_equal(result[0, 2], base[0, 2])       # far, transparent
        np.testing.assert_array_equal(result[0, 3], [128, 128, 128])  # midpoint, round half up
        np.testing.assert_array_equal(compose_depth_layer(base, depth, layer, strength=0), base)
        np.testing.assert_array_equal(compose_depth_layer(base, depth, layer, strength=.5)[0, 4],
                                      [128, 128, 128])
        for actual, original in zip((base, layer, depth), originals):
            np.testing.assert_array_equal(actual, original)

    def test_depth_shape_type_values_and_parameters(self):
        good = np.zeros((2, 3), dtype=np.float32)
        bad_depths = [np.zeros((2, 3), dtype=np.uint8), np.zeros((2, 3), dtype=bool),
                      np.zeros((0, 3), dtype=np.float32), np.zeros((2, 3, 1), dtype=np.float32),
                      np.zeros((3, 2), dtype=np.float32), [[0.0] * 3] * 2]
        for depth in bad_depths:
            with self.subTest(depth=repr(depth)), self.assertRaises(ValueError):
                depth_visibility(depth, 3, 2)
        for value in (np.nan, np.inf, -np.inf, -.01, 1.01):
            bad = good.copy()
            bad[0, 0] = value
            with self.subTest(value=value), self.assertRaises(ValueError):
                depth_visibility(bad, 3, 2)
        for width, height in ((True, 2), (3, False), (0, 2), (3, -1), (3.0, 2)):
            with self.subTest(size=(width, height)), self.assertRaises(ValueError):
                depth_visibility(good, width, height)
        for key, invalid in (('threshold', True), ('threshold', np.nan),
                             ('threshold', 1.01), ('softness', False),
                             ('softness', 0), ('softness', np.inf), ('softness', 1.01)):
            with self.subTest(key=key, invalid=invalid), self.assertRaises(ValueError):
                depth_visibility(good, 3, 2, **{key: invalid})

    def test_composite_rejects_malformed_images_and_strength(self):
        base = np.zeros((2, 3, 3), dtype=np.uint8)
        layer = np.zeros((2, 3, 4), dtype=np.uint8)
        depth = np.zeros((2, 3), dtype=np.float32)
        for invalid in (base.astype(np.float32), base[:, :, :2], base[:0], None):
            with self.subTest(base=repr(invalid)), self.assertRaises(ValueError):
                compose_depth_layer(invalid, depth, layer)
        for invalid in (layer.astype(np.float32), layer[:, :, :3], layer[:, :2], None):
            with self.subTest(layer=repr(invalid)), self.assertRaises(ValueError):
                compose_depth_layer(base, depth, invalid)
        for strength in (True, np.nan, -0.1, 1.1, '1'):
            with self.subTest(strength=strength), self.assertRaises(ValueError):
                compose_depth_layer(base, depth, layer, strength=strength)
