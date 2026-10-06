"""Pure frame-map tests for visual setting migration."""

import json
import unittest
from copy import deepcopy
from unittest.mock import patch

from video_harness.render_cache import digest
from video_harness.retime_settings import migrate_visual_settings


def mapping():
    return {"version": 4, "edit_basis": "visual", "fps": "30/1", "duration": .2,
        "frame_count": 6, "sequence": [{"id": "shot", "asset_id": "source",
        "source_path": "/source.mp4", "source_sha256": "a" * 64,
        "source_fps": "30/1", "output_fps": "30/1", "source_first_frame": 0,
        "source_end_frame_exclusive": 6, "output_first_frame": 0,
        "output_end_frame_exclusive": 6}]}


def compiled(frames=None):
    frames = frames if frames is not None else [0, 0, 1, 1, 2, 2, 3, 3, 4, 4, 4, 5]
    return {"version": 1, "fps": "30/1", "input_frame_count": 6,
            "output_frame_count": len(frames), "frame_map": frames}


def title(start="1/15", end="1/6", **extra):
    return {"id": "title", "role": "title", "text": "Test", "output_start": start,
            "output_end": end, "reason": "Observed title", **extra}


def config(**settings):
    return {"assets": [], **settings}


class VisualSettingMigrationTests(unittest.TestCase):
    def migrate(self, cfg, original=None, retime=None, **extra):
        with patch("video_harness.retime_settings.resolve_production"):
            return migrate_visual_settings(cfg, original or mapping(), retime or compiled(), **extra)

    def test_ramp_hold_exact_inverse_bounds_preserve_content_and_input(self):
        old = mapping()
        cue = title(fade_in="1/30", fade_out="1/30")
        event = {"id": "fx", "type": "monochrome", "output_start": "1/15",
                 "output_end": "1/6", "strength": .5, "reason": "Observed emphasis"}
        guide = {"id": "ui", "kind": "ui", "output_start": "1/15",
                 "output_end": "1/6", "rect": [.1, .1, .3, .3], "reason": "Observed UI"}
        cfg = config(cue_plan={"version": 1, "mapping_sha256": digest(old), "cues": [cue]},
                     video_effects={"version": 1, "mapping_sha256": digest(old), "events": [event]},
                     composition_guides=[guide])
        before = deepcopy(cfg)
        result = self.migrate(cfg, old)
        changes = result["changes"]
        for row in (changes["cue_plan"]["cues"][0], changes["video_effects"]["events"][0],
                    changes["composition_guides"][0]):
            self.assertEqual((row["output_start"], row["output_end"]), ("2/15", "11/30"))
        self.assertEqual(changes["cue_plan"]["cues"][0]["fade_in"], "1/30")
        self.assertEqual(changes["video_effects"]["events"][0]["reason"], event["reason"])
        self.assertEqual(changes["composition_guides"][0]["rect"], guide["rect"])
        self.assertEqual(changes["cue_plan"]["mapping_sha256"], result["evidence"]["new_mapping_sha256"])
        self.assertEqual(changes["video_effects"]["mapping_sha256"], result["evidence"]["new_mapping_sha256"])
        self.assertEqual(result["evidence"]["items"][0]["old_frames"], [2, 5])
        self.assertEqual(result["evidence"]["items"][0]["new_frames"], [4, 11])
        self.assertEqual(cfg, before)

    def test_animated_effect_preserves_old_relative_frame_phase(self):
        old = mapping()
        event = {"id": "pulse", "type": "smooth_zoom", "output_start": "1/15",
                 "output_end": "1/6", "strength": .5, "reason": "Observed motion"}
        cfg = config(video_effects={"version": 1, "mapping_sha256": digest(old), "events": [event]})
        result = self.migrate(cfg, old)
        moved = result["changes"]["video_effects"]["events"][0]
        self.assertEqual(moved["phase_map"], {"version": 1, "original_frame_count": 3,
                                             "frames": [0, 0, 1, 1, 2, 2, 2]})
        self.assertEqual(result["evidence"]["items"][0]["content_policy"], "original_frame_effect_phase")

    def test_keyword_title_migrates_its_original_animation_phase(self):
        old = mapping()
        event = {"id": "keyword", "type": "keyword_title", "output_start": "1/15",
                 "output_end": "1/6", "strength": .5, "reason": "Observed label",
                 "parameters": {"text": "MOVE", "motion": "rise"}}
        cfg = config(video_effects={"version": 1, "mapping_sha256": digest(old), "events": [event]})
        moved = self.migrate(cfg, old)["changes"]["video_effects"]["events"][0]
        self.assertEqual(moved["parameters"]["motion"], "rise")
        self.assertEqual(moved["phase_map"], {"version": 1, "original_frame_count": 3,
                                             "frames": [0, 0, 1, 1, 2, 2, 2]})
        self.assertEqual(moved["parameters"]["text"], "MOVE")

    def test_existing_phase_map_is_composed_without_resetting_shape(self):
        old = mapping()
        event = {"id": "pulse", "type": "smooth_zoom", "output_start": "1/15",
                 "output_end": "1/6", "strength": .5, "reason": "Observed phase",
                 "phase_map": {"version": 1, "original_frame_count": 5, "frames": [1, 2, 4]}}
        cfg = config(video_effects={"version": 1, "mapping_sha256": digest(old), "events": [event]})
        moved = self.migrate(cfg, old)["changes"]["video_effects"]["events"][0]
        self.assertEqual(moved["phase_map"], {"version": 1, "original_frame_count": 5,
                                             "frames": [1, 1, 2, 2, 4, 4, 4]})

    def test_video_content_follows_original_output_frames(self):
        old = mapping()
        cue = {"id": "video", "role": "video", "asset_id": "v", "output_start": "1/15",
               "output_end": "1/6", "source_start": "0", "source_end": "1", "reason": "Observed video"}
        cfg = config(cue_plan={"version": 1, "mapping_sha256": digest(old), "cues": [cue]})
        with patch("video_harness.retime_settings.validate_cues"):
            clock = {'original_start_frame': 2, 'original_frame_count': 3,
                     'original_time_base': '1/30', 'original_timestamps': [2, 3, 4]}
            result = self.migrate(cfg, old, video_clocks={'video': clock})
        moved = result["changes"]["cue_plan"]["cues"][0]
        self.assertEqual(moved["phase_map"], {"version": 1, "original_start_frame": 2, "original_frame_count": 3, "original_time_base": "1/30",
                                             "original_timestamps": [2, 3, 4], "frames": [0, 0, 1, 1, 2, 2, 2]})
        self.assertEqual(result["evidence"]["items"][0]["content_policy"], "original_output_frame_video_content")

    def test_sfx_requires_complete_one_to_one_content(self):
        old = mapping()
        for role in ("sfx",):
            cue = {"id": "media", "role": role, "asset_id": "asset",
                   "output_start": "1/15", "output_end": "1/6", "source_start": "0",
                   "source_end": "1", "reason": "Observed synchronized media"}
            cfg = config(cue_plan={"version": 1, "mapping_sha256": digest(old), "cues": [cue]})
            for frames in ([0, 1, 3, 4, 5], [0, 1, 2, 3, 3, 4, 5]):
                with self.assertRaisesRegex(ValueError, "source-content retiming"):
                    self.migrate(cfg, old, compiled(frames))

    def test_music_explicitly_keeps_normal_playback_on_new_clock(self):
        old = mapping()
        cue = {"id": "music", "role": "music", "asset_id": "song",
               "output_start": "1/15", "output_end": "1/6", "source_start": "0",
               "source_end": "1", "reason": "New output BGM", "beat_anchor": "1/10"}
        cfg = config(cue_plan={"version": 1, "mapping_sha256": digest(old), "cues": [cue]})
        with patch("video_harness.retime_settings.validate_cues"):
            result = self.migrate(cfg, old)
        self.assertEqual(result["changes"]["cue_plan"]["cues"][0]["source_start"], "0")
        self.assertEqual(result["changes"]["cue_plan"]["cues"][0]["beat_anchor"], "1/6")
        self.assertEqual(result["evidence"]["items"][0]["content_policy"],
                         "normal_playback_on_new_output_clock")

    def test_omitted_and_unaligned_intervals_rejected(self):
        old = mapping()
        for cue, frames, text in [(title("1/15", "1/10"), [0, 1, 3, 4, 5], "omitted"),
                                  (title("0.01", "1/10"), list(range(6)), "frame-aligned")]:
            cfg = config(cue_plan={"version": 1, "mapping_sha256": digest(old), "cues": [cue]})
            with self.assertRaisesRegex(ValueError, text):
                self.migrate(cfg, old, compiled(frames))

    def test_stale_digest_and_previously_retimed_mapping_rejected(self):
        old = mapping()
        cfg = config(cue_plan={"version": 1, "mapping_sha256": "0" * 64,
                               "cues": [title()]})
        with self.assertRaisesRegex(ValueError, "stale"):
            self.migrate(cfg, old)
        old["retime"] = {"frames": []}
        with self.assertRaisesRegex(ValueError, "previously retimed"):
            self.migrate(config(), old)

    def test_ambiguous_beat_anchor_and_tracked_artifacts_rejected(self):
        old = mapping()
        cfg = config(cue_plan={"version": 1, "mapping_sha256": digest(old),
                               "cues": [title(beat_anchor="1/15")]})
        with self.assertRaisesRegex(ValueError, "ambiguous"):
            self.migrate(cfg, old)
        cfg = config(composition_guides=[{"id": "tracked", "kind": "subject",
            "output_start": "0", "output_end": "1/30", "track_path": "/track.json",
            "reason": "Observed subject"}])
        with self.assertRaisesRegex(ValueError, "tracking"):
            self.migrate(cfg, old)
        cfg = config(video_effects={"version": 1, "mapping_sha256": digest(old), "events": [
            {"id": "tracked", "type": "tracked_zoom", "output_start": "0",
             "output_end": "1/10", "strength": .5, "reason": "Observed subject"}]})
        with self.assertRaisesRegex(ValueError, "tracking"):
            self.migrate(cfg, old)

    def test_unlooped_source_shorter_than_stretched_cue_rejected(self):
        old = mapping()
        cue = {"id": "music", "role": "music", "asset_id": "song",
               "output_start": "1/15", "output_end": "1/10", "source_start": "0",
               "source_end": "1/30", "loop": False, "reason": "Observed music"}
        cfg = config(assets=[{"asset_id": "song", "path": "/song.wav"}],
                     cue_plan={"version": 1, "mapping_sha256": digest(old), "cues": [cue]})
        with patch("video_harness.cues._check_asset", return_value={"kind": "music"}), \
             patch("video_harness.cues.subprocess.check_output",
                   return_value=json.dumps({"format": {"duration": "1"}}).encode()), \
             self.assertRaisesRegex(ValueError, "source too short"):
            self.migrate(cfg, old)


if __name__ == "__main__":
    unittest.main()
