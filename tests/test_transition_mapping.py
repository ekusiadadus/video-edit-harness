"""Pure, synthetic checks for source-bound visual transition compilation."""

from copy import deepcopy
from fractions import Fraction
import unittest

from video_harness.retime_mapping import conform_source_frames
from video_harness.transition_mapping import compile_transitions


def fixture(output_fps="24", source_fps=("24", "24"), spans=((10, 34), (40, 64)), lengths=(12, 12)):
    sources = {}
    rows = []
    cursor = 0
    for i, ((first, end), rate, length) in enumerate(zip(spans, source_fps, lengths)):
        asset = f"asset-{i}"
        sources[asset] = {"path": f"/synthetic/{asset}.mov", "sha256": str(i + 1) * 64,
                          "bytes": 1024, "fps": rate, "frame_count": 100}
        rows.append({"id": f"segment-{i}", "asset_id": asset, "source_path": sources[asset]["path"],
                     "source_sha256": sources[asset]["sha256"], "source_fps": rate,
                     "output_fps": output_fps, "source_first_frame": first,
                     "source_end_frame_exclusive": end, "output_first_frame": cursor,
                     "output_end_frame_exclusive": cursor + length,
                     "source_frame_map": conform_source_frames(first, end, rate, length, output_fps)})
        cursor += length
    mapping = {"version": 4, "edit_basis": "visual", "fps": output_fps,
               "duration": float(Fraction(cursor, 1) / Fraction(output_fps)),
               "frame_count": cursor, "sequence": rows}
    return mapping, sources


def request(kind="dissolve", before=2, after=2, **fields):
    event = {"id": "transition-1", "left_segment_id": "segment-0",
             "before_frames": before, "after_frames": after, "type": kind,
             "reason": "observed motion continues across this cut"}
    if kind == "push":
        event["direction"] = "left"
    event.update(fields)
    return {"version": 1, "events": [event]}


def compile_(mapping=None, sources=None, transition=None):
    default_mapping, default_sources = fixture()
    return compile_transitions(mapping if mapping is not None else default_mapping,
                               transition if transition is not None else request(),
                               sources if sources is not None else default_sources,
                               "codex", "requested source-bound transition")


class TransitionMappingTests(unittest.TestCase):
    def test_cfr_boundary_still_requires_real_post_handle_and_strict_types(self):
        mapping, sources = fixture('30', ('24', '24'), spans=((0, 2), (5, 7)), lengths=(2, 2))
        sources['asset-0']['frame_count'] = 2
        with self.assertRaisesRegex(ValueError, 'missing source pre/post handle'):
            compile_(mapping, sources, request(before=1, after=1))
        mapping, sources = fixture(spans=((1, 25), (40, 64)))
        mapping['sequence'][0]['source_frame_map'][0] = True
        with self.assertRaisesRegex(ValueError, 'canonical'):
            compile_(mapping, sources)
        for event in (request(type=[]), request('push', direction=[])):
            with self.assertRaises(ValueError):
                compile_(transition=event)

    def test_exact_endpoints_audio_and_real_handles(self):
        mapping, sources = fixture()
        result = compile_(mapping, sources)
        self.assertEqual((result["frame_count"], result["fps"], result["audio_policy"]),
                         (24, "24", "base_audio_unchanged"))
        self.assertTrue(result["review_required"])
        self.assertFalse(result["adopted"])
        event = result["events"][0]
        self.assertEqual((event["first_frame"], event["end_frame_exclusive"]), (10, 14))
        self.assertEqual([f["progress"] for f in event["frames"]], ["0/1", "1/3", "2/3", "1/1"])
        self.assertEqual(event["frames"][0]["weights"], {"left": "1/1", "right": "0/1"})
        self.assertEqual(event["frames"][-1]["weights"], {"left": "0/1", "right": "1/1"})
        self.assertEqual([f["left"]["source_frame"] for f in event["frames"][:2]],
                         mapping["sequence"][0]["source_frame_map"][-2:])
        self.assertEqual([f["right"]["source_frame"] for f in event["frames"][2:]],
                         mapping["sequence"][1]["source_frame_map"][:2])
        self.assertEqual(event["frames"][0]["right"]["source_frame"], 38)
        self.assertEqual(event["frames"][-1]["left"]["source_frame"], 23)

    def test_mixed_fps_and_spatial_push(self):
        for output, rates in (("24", ("30", "24")), ("30", ("24", "30")),
                              ("30000/1001", ("24", "30"))):
            with self.subTest(output=output):
                mapping, sources = fixture(output, rates)
                result = compile_(mapping, sources, request("push", direction="up"))
                frames = result["events"][0]["frames"]
                self.assertEqual(result["fps"], output)
                self.assertEqual(result["events"][0]["direction"], "up")
                self.assertTrue(all(f["spatial_operator"] == "push" and "weights" not in f for f in frames))
                self.assertEqual([f["left"]["source_frame"] for f in frames[:2]],
                                 mapping["sequence"][0]["source_frame_map"][-2:])
                self.assertEqual([f["right"]["source_frame"] for f in frames[2:]],
                                 mapping["sequence"][1]["source_frame_map"][:2])

    def test_missing_pre_and_post_handles_rejected(self):
        mapping, sources = fixture(spans=((10, 34), (0, 24)))
        with self.assertRaisesRegex(ValueError, "missing source pre/post handle"):
            compile_(mapping, sources)
        mapping, sources = fixture(spans=((89, 100), (40, 64)))
        sources["asset-0"]["frame_count"] = 100
        with self.assertRaisesRegex(ValueError, "missing source pre/post handle"):
            compile_(mapping, sources)

    def test_overlapping_windows_and_segment_boundaries(self):
        mapping, sources = fixture(lengths=(6, 6))
        third, third_sources = fixture(lengths=(6, 6))
        row = deepcopy(third["sequence"][1])
        row.update(id="segment-2", output_first_frame=12, output_end_frame_exclusive=18)
        mapping["sequence"].append(row)
        mapping["frame_count"] = 18
        mapping["duration"] = 18 / 24
        events = [request(before=2, after=4)["events"][0],
                  {**request(before=3, after=2)["events"][0], "id": "transition-2",
                   "left_segment_id": "segment-1"}]
        with self.assertRaisesRegex(ValueError, "overlap"):
            compile_(mapping, sources, {"version": 1, "events": events})
        with self.assertRaisesRegex(ValueError, "neighboring selected segments"):
            compile_(mapping, sources, request(before=7))

    def test_rejects_invalid_maps_retime_and_stale_bindings(self):
        mapping, sources = fixture()
        mutations = [
            (lambda m, s: m["sequence"][0]["source_frame_map"].__setitem__(0, 11), "canonical"),
            (lambda m, s: m["sequence"][1].__setitem__("output_first_frame", 13), "partition"),
            (lambda m, s: m.__setitem__("retime", {}), "retimed"),
            (lambda m, s: m["sequence"][0].__setitem__("source_sha256", "f" * 64), "SHA"),
            (lambda m, s: s["asset-0"].__setitem__("fps", "25"), "FPS"),
            (lambda m, s: s["asset-1"].__setitem__("sha256", "a" * 64), "SHA"),
        ]
        for mutate, message in mutations:
            with self.subTest(message=message):
                changed_mapping, changed_sources = deepcopy(mapping), deepcopy(sources)
                mutate(changed_mapping, changed_sources)
                with self.assertRaisesRegex(ValueError, message):
                    compile_(changed_mapping, changed_sources)

    def test_invalid_requests(self):
        mapping, sources = fixture()
        invalid = [request(before=0), request(after=True), request(before=23, after=2),
                   request("push", direction="diagonal"), request(direction="left"),
                   request(left_segment_id="segment-1"), request(extra="unrecognized"),
                   {"version": 1, "events": []}, {"version": True, "events": [request()["events"][0]]}]
        for value in invalid:
            with self.subTest(value=value), self.assertRaises(ValueError):
                compile_(mapping, sources, value)


if __name__ == "__main__":
    unittest.main()
