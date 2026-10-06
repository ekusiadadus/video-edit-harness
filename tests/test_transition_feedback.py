"""Synthetic correspondence checks for attached visual transitions."""

from copy import deepcopy
from fractions import Fraction
import unittest

from tests.test_transition_mapping import fixture, request
from video_harness.feedback import map_output
from video_harness.transition_feedback import attach_transitions
from video_harness.transition_mapping import compile_transitions


def mapped(output_fps="24", rates=("24", "24"), spans=((10, 22), (40, 52)), lengths=(12, 12),
           transition=None):
    mapping, sources = fixture(output_fps, rates, spans, lengths)
    for row in mapping["sequence"]:
        source_rate = Fraction(row["source_fps"])
        rate = Fraction(output_fps)
        row.update(source_start=f"{Fraction(row['source_first_frame'], 1) / source_rate}",
                   source_end=f"{Fraction(row['source_end_frame_exclusive'], 1) / source_rate}",
                   output_start=f"{Fraction(row['output_first_frame'], 1) / rate}",
                   output_end=f"{Fraction(row['output_end_frame_exclusive'], 1) / rate}")
    proposal = compile_transitions(mapping, transition or request(), sources, "codex", "observed cut")
    return mapping, proposal


class TransitionFeedbackTests(unittest.TestCase):
    def test_attach_preserves_input_and_exact_cut_reference(self):
        mapping, proposal = mapped()
        original, compiled = deepcopy(mapping), deepcopy(proposal)
        attached = attach_transitions(mapping, proposal)
        self.assertEqual((mapping, proposal), (original, compiled))
        self.assertEqual(attached["sequence"], mapping["sequence"])
        result = map_output(attached, 11 / 24, 13 / 24)
        self.assertEqual(result["source_time_scope"], "discrete composed frame coverage")
        self.assertEqual(result["cut_reference"]["label"], "original cut reference only")
        self.assertEqual([f["output_frame"] for f in result["frame_correspondence"]], [11, 12])
        self.assertEqual([[r["side"] for r in f["references"]] for f in result["frame_correspondence"]],
                         [["left", "right"], ["left", "right"]])
        self.assertEqual({r["asset_id"] for r in result["source_spans"]}, {"asset-0", "asset-1"})
        self.assertEqual([r["source_first_frame"] for r in result["source_spans"]], [21, 39, 22, 40])
        self.assertEqual([r["event_id"] for r in result["source_spans"]], ["transition-1"] * 4)

    def test_mixed_rate_push_and_untransitioned_frame(self):
        mapping, proposal = mapped("30", ("24", "30"), ((10, 18), (40, 50)), (10, 10),
                                   request("push", direction="up", before=2, after=2))
        attached = attach_transitions(mapping, proposal)
        before = map_output(attached, 0)
        self.assertEqual([r["side"] for r in before["frame_correspondence"][0]["references"]], ["base"])
        self.assertEqual(before["frame_correspondence"][0]["references"][0]["source_frame"], 10)
        at_cut = map_output(attached, 10 / 30)
        frame = at_cut["frame_correspondence"][0]
        self.assertEqual(at_cut["boundaries"][0]["scope"], "original cut reference only")
        self.assertEqual((at_cut["boundaries"][0]["left_sequence_id"],
                          at_cut["boundaries"][0]["right_sequence_id"]),
                         ("segment-0", "segment-1"))
        self.assertEqual(at_cut["cut_reference"]["label"], "original cut reference only")
        self.assertEqual((frame["spatial_operator"], frame["direction"]), ("push", "up"))
        self.assertEqual([r["asset_id"] for r in frame["references"]], ["asset-0", "asset-1"])
        self.assertEqual([r["source_first_frame"] for r in at_cut["source_spans"]],
                         [r["source_frame"] for r in frame["references"]])
        self.assertEqual(at_cut["source_spans"][0]["source_end"],
                         (frame["references"][0]["source_frame"] + 1) / 24)

    def test_point_at_duration_and_fractional_window_edges(self):
        mapping, proposal = mapped()
        attached = attach_transitions(mapping, proposal)
        result = map_output(attached, 10.2 / 24, 13.1 / 24)
        self.assertEqual([f["output_frame"] for f in result["frame_correspondence"]], [10, 11, 12, 13])
        end = map_output(attached, 1)
        self.assertEqual(end["frame_correspondence"][0]["output_frame"], 23)
        self.assertEqual(end["frame_correspondence"][0]["references"][0]["side"], "base")

    def test_tampering_and_invalid_attachments_rejected(self):
        mapping, proposal = mapped()
        attached = attach_transitions(mapping, proposal)
        mutations = [
            lambda m: m["transitions"]["compiled"]["events"][0]["frames"][0]["weights"].update(left="0/1"),
            lambda m: m["transitions"]["compiled"].update(input_mapping_sha256="0" * 64),
            lambda m: m["transitions"]["compiled"]["events"][0].update(first_frame=9),
            lambda m: m["transitions"]["compiled"].update(adopted=0),
            lambda m: m["sequence"][0]["source_frame_map"].__setitem__(0, 99),
            lambda m: m["transitions"].update(version=True),
            lambda m: m.update(retime={}),
        ]
        for mutate in mutations:
            changed = deepcopy(attached)
            mutate(changed)
            with self.subTest(changed=changed), self.assertRaises(ValueError):
                map_output(changed, 11 / 24)
        with self.assertRaises(ValueError):
            attach_transitions(attached, proposal)
        with self.assertRaises(ValueError):
            attach_transitions({**mapping, "retime": {}}, proposal)
        with self.assertRaises(ValueError):
            map_output(attached, 1.1)

    def test_nontransition_visual_feedback_unchanged(self):
        mapping, _ = mapped()
        result = map_output(mapping, 12 / 24)
        self.assertNotIn("frame_correspondence", result)
        self.assertEqual(result["source_spans"][0]["sequence_id"], "segment-1")


if __name__ == "__main__":
    unittest.main()
