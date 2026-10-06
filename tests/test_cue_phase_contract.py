"""Exact validation of nonlinear video-cue frame selection."""
import json
import unittest
from unittest.mock import patch
from video_harness.cues import validate_cues, validate_video_phase


def cue(**extra):
    return {"id": "v", "asset_id": "v", "role": "video", "output_start": "1/10",
            "output_end": "1/2", "source_start": "0", "source_end": "1/5",
            "phase_map": {"version": 1, "original_start_frame": 1, "original_frame_count": 2, "original_time_base": "1/10", "original_timestamps": [1, 2], "frames": [0, 0, 1, 1]}, **extra}


class CuePhaseContractTests(unittest.TestCase):
    def test_stretched_duration_checks_original_source_span(self):
        value = cue()
        with patch("video_harness.cues._check_asset", return_value={"kind": "video"}), patch(
            "video_harness.cues.subprocess.check_output", return_value=json.dumps({"format": {"duration": "1"}}).encode()):
            result = validate_cues([value], [{"asset_id": "v", "path": "/v.mp4"}], "1", "10")
            self.assertEqual(result[0]["phase_map"], value["phase_map"])
            self.assertIsNot(result[0]["phase_map"]["frames"], value["phase_map"]["frames"])
            with self.assertRaisesRegex(ValueError, "source too short"):
                validate_cues([cue(source_end="1/10")], [{"asset_id": "v", "path": "/v.mp4"}], "1", "10")

    def test_malformed_or_inapplicable_phase_rejects(self):
        original = cue()
        variations = [cue(phase_map={**original["phase_map"], "original_time_base": "0"}),
            cue(phase_map={**original["phase_map"], "original_timestamps": [0, 1]}),
            cue(phase_map={**original["phase_map"], "original_timestamps": [1, True]}),
            cue(phase_map=None), cue(role="music"), cue(loop=True),
            cue(output_start="0.11"), cue(phase_map={**original["phase_map"], "version": True}),
            cue(phase_map={**original["phase_map"], "frames": [0, 1, 0, 1]}),
            cue(phase_map={**original["phase_map"], "frames": [0, 0, True, 1]}),
            cue(phase_map={**original["phase_map"], "frames": [0, 0, 1]}),
            cue(phase_map={**original["phase_map"], "original_frame_count": 4097})]
        for value in variations:
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate_video_phase(value, "10")
        with self.assertRaisesRegex(ValueError, "explicit FPS"):
            validate_video_phase(original, None)


if __name__ == "__main__":
    unittest.main()
