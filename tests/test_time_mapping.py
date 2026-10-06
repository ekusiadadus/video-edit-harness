import unittest

from video_harness.time_mapping import compile_retime


def ramp(first=2, end=6, start=1, finish=1, op_id="r1"):
    return {"id": op_id, "kind": "ramp", "source_first_frame": first,
            "source_end_frame_exclusive": end, "speed_start": start,
            "speed_end": finish, "reason": "manual pacing"}


def freeze(at=3, count=2, op_id="f1"):
    return {"id": op_id, "kind": "freeze", "source_frame": at,
            "output_frames": count, "reason": "hold result"}


class CompileRetimeTests(unittest.TestCase):
    def test_identity_and_unity_ramp(self):
        identity = compile_retime(8, "30000/1001", [])
        self.assertEqual(identity["frame_map"], list(range(8)))
        self.assertEqual(identity["fps"], "30000/1001")
        self.assertEqual(identity["version"], 1)
        self.assertFalse(identity["timing_changed"])
        unity = compile_retime(8, "24/1", [ramp()], [(3, 5)])
        self.assertEqual(unity["frame_map"], list(range(8)))
        self.assertFalse(unity["timing_changed"])
        self.assertEqual(unity["spans"][0]["source_coverage"]["distinct_frames"], 4)

    def test_slow_and_fast_ramps_preserve_gaps_and_audit_coverage(self):
        slow = compile_retime(8, "24000/1001", [ramp(start=.5, finish=.5)])
        self.assertEqual(slow["frame_map"], [0, 1, 2, 2, 3, 3, 4, 4, 5, 5, 6, 7])
        self.assertEqual(slow["output_frame_count"], 12)
        self.assertEqual(slow["spans"][0]["effective_speed_start"], 0)
        self.assertEqual(slow["spans"][0]["effective_speed_end"], 0)
        fast = compile_retime(8, "24/1", [ramp(start=2, finish=2)])
        self.assertEqual(fast["frame_map"], [0, 1, 2, 4, 6, 7])
        self.assertEqual(fast["spans"][0]["source_coverage"]["skipped_frames"], 2)
        self.assertEqual(fast["spans"][0]["effective_speed_start"], 2)
        self.assertTrue(fast["timing_changed"])

    def test_varying_ramp_uses_exact_rational_samples(self):
        result = compile_retime(10, "30000/1001", [ramp(1, 9, .5, 1.5)])
        self.assertEqual(result["output_frame_count"], 10)
        self.assertEqual(result["frame_map"], [0, 1, 1, 2, 3, 4, 5, 6, 7, 9])
        self.assertEqual(result["spans"][0]["requested_speed_start"], "1/2")
        self.assertEqual(result["spans"][0]["requested_speed_end"], "3/2")

    def test_freeze_inserts_before_original_and_keeps_later_operations(self):
        result = compile_retime(8, "25/1", [freeze(), ramp(5, 7, 2, 2)])
        self.assertEqual(result["frame_map"], [0, 1, 2, 3, 3, 3, 4, 5, 7])
        self.assertEqual(result["spans"][0]["output_first_frame"], 3)
        self.assertEqual(result["spans"][0]["output_end_frame_exclusive"], 5)
        self.assertEqual(result["spans"][0]["effective_speed_start"], 0)

    def test_protected_half_open_boundaries(self):
        compile_retime(10, "24/1", [ramp(1, 4, 2, 2), freeze(6)], [(4, 6)])
        for operations in ([ramp(2, 5, 2, 2)], [freeze(4)]):
            with self.subTest(operations=operations), self.assertRaisesRegex(ValueError, "protected"):
                compile_retime(10, "24/1", operations, [(4, 6)])

    def test_invalid_shapes_order_values_and_fps(self):
        invalid = [
            [ramp(op_id="a"), freeze(7, op_id="a")],
            [ramp(3, 4)], [ramp(3, 11)], [ramp(3, 6, float("nan"), 1)],
            [ramp(3, 6, float("inf"), 1)], [ramp(3, 6, True, 1)],
            [ramp(3, 6, .24, 1)], [freeze(3, 0)], [freeze(10)],
            [freeze(6), ramp(2, 5)], [ramp(2, 6), freeze(4)],
            [{**ramp(), "unexpected": 1}], [{**freeze(), "id": " "}],
            [{**freeze(), "reason": " "}],
        ]
        for operations in invalid:
            with self.subTest(operations=operations), self.assertRaises(ValueError):
                compile_retime(10, "24/1", operations)
        for fps in ("0/1", "1/0", "nan", " 24/1", 24):
            with self.subTest(fps=fps), self.assertRaises(ValueError):
                compile_retime(10, fps, [])
        for count in (0, True, 2.0):
            with self.subTest(count=count), self.assertRaises(ValueError):
                compile_retime(count, "24/1", [])
        with self.assertRaises(ValueError):
            compile_retime(10, "24/1", [freeze(3)], [(3, 4)])


if __name__ == "__main__":
    unittest.main()
