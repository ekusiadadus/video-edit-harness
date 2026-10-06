"""Focused tests for the versioned effect parameter contract."""

import json
import unittest

from video_harness.effect_catalog import catalog, validate_parameters


class EffectCatalogTest(unittest.TestCase):
    def test_catalog_is_versioned_json_and_independent(self):
        first = catalog()
        self.assertEqual(first["version"], 1)
        self.assertTrue({"smooth_zoom", "saturation_pulse", "comparison_wipe"} <= set(first["effects"]))
        for definition in first["effects"].values():
            self.assertEqual(definition["version"], 1)
            self.assertEqual(definition["backend"], "local_burned")
            self.assertTrue(definition["intent"])
        json.dumps(first, allow_nan=False)
        first["effects"]["smooth_zoom"]["parameters"]["anchor_x"]["default"] = 0.1
        self.assertEqual(catalog()["effects"]["smooth_zoom"]["parameters"]["anchor_x"]["default"], 0.5)

    def test_defaults_and_valid_extremes(self):
        self.assertEqual(validate_parameters("smooth_zoom", {}), {
            "anchor_x": 0.5, "anchor_y": 0.5, "max_scale": 1.12, "easing": "smoothstep"})
        self.assertEqual(validate_parameters("saturation_pulse", None), {
            "minimum_saturation": 0.0, "easing": "smoothstep"})
        supplied = {"anchor_x": 0, "anchor_y": 1, "max_scale": 1.5, "easing": "cosine"}
        self.assertEqual(validate_parameters("smooth_zoom", supplied), {
            "anchor_x": 0.0, "anchor_y": 1.0, "max_scale": 1.5, "easing": "cosine"})
        self.assertEqual(supplied["anchor_x"], 0)
        self.assertEqual(validate_parameters("saturation_pulse", {
            "minimum_saturation": 1, "easing": "cosine"}), {
            "minimum_saturation": 1.0, "easing": "cosine"})

    def test_rejects_invalid_kinds_fields_and_values(self):
        invalid = [
            ("missing", {}, "Unsupported"),
            ("smooth_zoom", [], "object"),
            ("smooth_zoom", {"unknown": 1}, "Unknown"),
            ("smooth_zoom", {"anchor_x": -0.01}, "between"),
            ("smooth_zoom", {"anchor_y": 1.01}, "between"),
            ("smooth_zoom", {"max_scale": 0.99}, "between"),
            ("smooth_zoom", {"max_scale": 1.51}, "between"),
            ("smooth_zoom", {"max_scale": True}, "finite number"),
            ("smooth_zoom", {"anchor_x": float("nan")}, "finite number"),
            ("smooth_zoom", {"anchor_x": float("inf")}, "finite number"),
            ("smooth_zoom", {"anchor_x": "0.5"}, "finite number"),
            ("smooth_zoom", {"easing": "linear"}, "one of"),
            ("saturation_pulse", {"minimum_saturation": -0.01}, "between"),
            ("saturation_pulse", {"minimum_saturation": 1.01}, "between"),
            ("saturation_pulse", {"minimum_saturation": False}, "finite number"),
        ]
        for kind, parameters, message in invalid:
            with self.subTest(kind=kind, parameters=parameters):
                with self.assertRaisesRegex(ValueError, message):
                    validate_parameters(kind, parameters)


if __name__ == "__main__":
    unittest.main()
