"""Exact validation of nonlinear video-cue frame selection."""
import json
import unittest
from unittest.mock import patch
from video_harness.cues import validate_cues, validate_video_phase


def cue(**extra):
    return {"id": "v", "asset_id": "v", "role": "video", "output_start": "1/10",
            "output_end": "1/2", "source_start": "0", "source_end": "1/5",
            "phase_map": {"version": 1, "original_start_frame": 1, "original_frame_count": 2, "original_time_base": "1/10", "original_input_pts_shift": 0, "original_timestamps": [1, 2], "frames": [0, 0, 1, 1]}, **extra}


class CuePhaseContractTests(unittest.TestCase):
    def test_legacy_clock_readback_does_not_invent_an_offset(self):
        original = cue()
        del original['phase_map']['original_input_pts_shift']
        self.assertEqual(validate_video_phase(original, '10'), original['phase_map'])
        from video_harness.video_cue_phase import retime_video_cue_layer
        with self.assertRaisesRegex(ValueError, 'fresh original render'):
            retime_video_cue_layer('/unused.mp4', original, {}, (160, 90), '10', '/unused.mkv')

    def test_sealed_output_layer_contract(self):
        layer = {'path': '/sealed.mkv', 'sha256': 'a'*64, 'bytes': 10,
                 'frame_count': 2, 'width': 160, 'height': 90, 'fps': '10/1'}
        phase = {'version': 2, 'original_start_frame': 1, 'original_frame_count': 2,
                 'original_layer': layer, 'original_cue_sha256': 'a'*64, 'frames': [0, 0, 1, 1]}
        result = validate_video_phase(cue(phase_map=phase), '10')
        self.assertEqual(result, phase)
        self.assertIsNot(result['original_layer'], layer)
        self.assertIsNot(result['frames'], phase['frames'])
        for changed in ({**layer, 'path': 'relative.mkv'}, {**layer, 'sha256': 'x'*64},
                        {**layer, 'frame_count': True}, {**layer, 'fps': '10'},
                        {**layer, 'frame_count': 3}, {**layer, 'width': 0}):
            with self.subTest(layer=changed), self.assertRaises(ValueError):
                validate_video_phase(cue(phase_map={**phase, 'original_layer': changed}), '10')
        with self.assertRaises(ValueError):
            validate_video_phase(cue(phase_map={**phase, 'frames': [0, 1, 0, 1]}), '10')

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
        variations = [cue(phase_map={**original["phase_map"], "original_input_pts_shift": True}),
            cue(phase_map={**original["phase_map"], "original_time_base": "0"}),
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
