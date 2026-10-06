"""Framewise composition checks against sealed synthetic tracking artifacts."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from video_harness.composition import check_composition, resolve_guides


FPS = 10
SHA = "a" * 64


def mapping():
    return {"fps": str(FPS), "duration": "1", "sequence": []}


def track_document(boxes):
    rows = []
    for frame, box in enumerate(boxes):
        rows.append({
            "frame": frame,
            "box": box,
            "state": "lost" if box is None else "manual",
            "quality": {"feature_count": 0, "reason": "occlusion"} if box is None else {"feature_count": 10},
        })
    return {
        "version": 1,
        "algorithm": "lk-affine-v1",
        "source": {"path": "/tmp/synthetic-source.mp4", "sha256": SHA, "bytes": 1},
        "fps": str(FPS),
        "start_frame": 0,
        "end_frame_exclusive": len(rows),
        "review_required": True,
        "rows": rows,
    }


def tracked_guide(path, *, kind="subject", start="0", end="1", sha=None):
    row = {
        "id": "moving-subject",
        "kind": kind,
        "track_path": str(path),
        "output_start": start,
        "output_end": end,
        "reason": "Observed synthetic subject motion",
    }
    if sha is not None:
        row["track_sha256"] = sha
    return row


def title(start="0", end="1"):
    return {
        "id": "title",
        "type": "keyword_title",
        "output_start": start,
        "output_end": end,
        "strength": 1,
        "parameters": {"motion": "fade"},
    }


def zoom(start="0", end="1", *, anchor_x=0.5, anchor_y=0.5, max_scale=1.5):
    return {
        "id": "zoom",
        "type": "smooth_zoom",
        "output_start": start,
        "output_end": end,
        "strength": 1,
        "parameters": {
            "anchor_x": anchor_x,
            "anchor_y": anchor_y,
            "max_scale": max_scale,
            "easing": "smoothstep",
        },
    }


class TrackedCompositionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "track.json"

    def save_track(self, boxes):
        self.path.write_text(json.dumps(track_document(boxes)), encoding="utf-8")
        return hashlib.sha256(self.path.read_bytes()).hexdigest()

    def resolve(self, **guide_options):
        return resolve_guides([tracked_guide(self.path, **guide_options)], mapping())

    def test_resolves_canonical_path_and_sha_and_rejects_replacement(self):
        digest = self.save_track([[.1, .2, .3, .5]] * 10)
        resolved = self.resolve()
        guide = resolved["guides"][0]
        self.assertEqual(guide["track_path"], str(self.path.resolve()))
        self.assertEqual(guide["track_sha256"], digest)
        self.assertEqual(guide["output_start"], "0")
        self.assertEqual(guide["output_end"], "1")
        self.assertEqual(self.resolve(sha=digest)["guides"][0]["track_sha256"], digest)
        with self.assertRaises(ValueError):
            self.resolve(sha="0" * 64)

        # An existing resolved plan must not silently consume edited tracking rows.
        self.path.write_text(self.path.read_text(encoding="utf-8") + "\n", encoding="utf-8")
        with self.assertRaises(ValueError):
            check_composition([title()], resolved, [{"event_id": "title", "bounds": [.8, .2, .9, .5]}], fps=FPS)

    def test_moving_box_crosses_title_only_on_late_frames(self):
        self.save_track([[.1 + i * .05, .2, .3 + i * .05, .5] for i in range(10)])
        resolved = self.resolve()
        # The first frame clears the title; a later frame intersects it.
        with self.assertRaisesRegex(ValueError, "intersects"):
            check_composition([title()], resolved,
                              [{"event_id": "title", "bounds": [.55, .25, .7, .45]}], fps=FPS)

    def test_clear_title_records_number_of_checked_frames(self):
        self.save_track([[.1 + i * .04, .2, .3 + i * .04, .5] for i in range(10)])
        resolved = self.resolve()
        report = check_composition([title("1/5", "4/5")], resolved,
                                   [{"event_id": "title", "bounds": [.8, .25, .95, .45]}], fps=FPS)
        self.assertEqual(report["checks"][0]["status"], "no_detected_conflict")
        self.assertEqual(report["checks"][0]["frames_checked"], 6)

    def test_lost_interval_and_fps_mismatch_fail_during_resolution(self):
        boxes = [[.1, .2, .3, .5]] * 10
        boxes[5] = None
        self.save_track(boxes)
        with self.assertRaises(ValueError):
            self.resolve()
        # A guide ending before loss has a fully usable interval.
        self.assertEqual(self.resolve(end="1/2")["guides"][0]["output_end"], "1/2")

        document = track_document([[.1, .2, .3, .5]] * 10)
        document["fps"] = "11"
        self.path.write_text(json.dumps(document), encoding="utf-8")
        with self.assertRaises(ValueError):
            self.resolve()

    def test_ui_cannot_use_a_tracking_artifact(self):
        self.save_track([[.1, .2, .3, .5]] * 10)
        with self.assertRaises(ValueError):
            self.resolve(kind="ui")

    def test_smooth_zoom_uses_pulse_geometry_for_crop_and_title_collision(self):
        self.save_track([[.72, .2, .90, .5]] * 10)
        resolved = self.resolve()
        # At both ends the pulse is unscaled; the middle moves the visible right edge.
        with self.assertRaisesRegex(ValueError, "crops"):
            check_composition([zoom(anchor_x=0, max_scale=1.5)], resolved, fps=FPS)

        self.save_track([[.35, .2, .45, .5]] * 10)
        resolved = self.resolve()
        events = [zoom(anchor_x=1, max_scale=1.5), title()]
        # The raw tracked box clears this title, while the zoomed box crosses it.
        with self.assertRaisesRegex(ValueError, "intersects"):
            check_composition(events, resolved,
                              [{"event_id": "title", "bounds": [.17, .25, .29, .45]}], fps=FPS)

    def test_tracked_title_requires_measured_bounds(self):
        self.save_track([[.1, .2, .3, .5]] * 10)
        with self.assertRaises(ValueError):
            check_composition([title()], self.resolve(), fps=FPS)

    def test_tracked_zoom_checks_each_frame_with_sealed_anchor(self):
        digest = self.save_track([[.2 + i * .02, .2, .4 + i * .02, .5] for i in range(10)])
        event = {
            "id": "follow",
            "type": "tracked_zoom",
            "output_start": "0",
            "output_end": "1",
            "strength": 1,
            "parameters": {
                "track_path": str(self.path),
                "track_sha256": digest,
                "max_scale": 1.5,
                "easing": "smoothstep",
            },
        }
        report = check_composition([event], self.resolve(), fps=FPS)
        self.assertEqual(report["checks"][0]["status"], "no_detected_conflict")
        self.assertEqual(report["checks"][0]["frames_checked"], 10)

    def test_unknown_geometry_cannot_claim_tracked_clearance(self):
        self.save_track([[.1, .2, .3, .5]] * 10)
        event = {"id": "split", "type": "split_screen", "output_start": "0", "output_end": "1"}
        with self.assertRaises(ValueError):
            check_composition([event], self.resolve(), fps=FPS)

    def test_nongeometric_effect_is_explicitly_unchecked(self):
        self.save_track([[.1, .2, .3, .5]] * 10)
        event = {"id": "border", "type": "color_frame", "output_start": "1/5", "output_end": "4/5"}
        report = check_composition([event], self.resolve(), fps=FPS)
        self.assertEqual(report["checks"], [{
            "event_id": "border",
            "guide_id": "moving-subject",
            "status": "not_checked_for_this_effect",
        }])


if __name__ == "__main__":
    unittest.main()
