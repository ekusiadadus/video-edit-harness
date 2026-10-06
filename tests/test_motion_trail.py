"""Focused graph and evidence checks for causal motion trails."""
from fractions import Fraction
import unittest

from video_harness.motion_trail import build_trail_graph


def event(start='1/5', end='3/5', history=3, decay=.5, strength=.8):
    return {'type': 'motion_trail', 'output_start': start, 'output_end': end,
            'strength': strength,
            'parameters': {'history_frames': history, 'decay': decay}}


class MotionTrailGraphTests(unittest.TestCase):
    def test_middle_window_is_trimmed_before_tmix_and_reassembled(self):
        graph, proof = build_trail_graph('graded', 'trail', event(), Fraction(10), 8)
        self.assertIn('[graded]split=3[trail_prefix_src][trail_effect_src][trail_suffix_src]', graph)
        self.assertIn('trim=start_frame=0:end_frame=2', graph)
        self.assertIn('trim=start_frame=2:end_frame=6,settb=expr=1/10,setpts=N,tmix=', graph)
        self.assertIn('tmix=frames=3:weights=0.2 0.4 1:scale=0', graph)
        self.assertIn('trim=start_frame=6:end_frame=8', graph)
        self.assertTrue(graph.endswith('[trail_prefix][trail_effect][trail_suffix]concat=n=3:v=1:a=0,settb=expr=1/10,setpts=N[trail]'))
        self.assertEqual((proof['window_first_frame'], proof['window_end_frame_exclusive']), (2, 6))
        self.assertEqual(proof['causal_frame_offsets_oldest_to_newest'], [-2, -1, 0])
        self.assertEqual(proof['output_frame_count'], 8)
        self.assertAlmostEqual(sum(proof['normalized_weights_oldest_to_newest']), 1)
        self.assertGreater(proof['normalized_weights_oldest_to_newest'][-1],
                           proof['normalized_weights_oldest_to_newest'][-2])

    def test_full_window_has_no_split_or_concat(self):
        graph, proof = build_trail_graph('v0', 'vtrail', event('0', '4/5', 4, .2, .5), 10, 8)
        self.assertNotIn('split=', graph)
        self.assertNotIn('concat=', graph)
        self.assertIn('trim=start_frame=0:end_frame=8', graph)
        self.assertTrue(graph.endswith('[vtrail]'))
        self.assertEqual(proof['warmup_frames'], 3)
        self.assertIn('replicated', proof['warmup'])
        for actual, expected in zip(proof['weights_oldest_to_newest'], [.004, .02, .1, 1.0]):
            self.assertAlmostEqual(actual, expected)

    def test_edge_and_short_event_windows_keep_actual_frame_count(self):
        for start, end, expected in [('0', '1/10', 2), ('7/10', '4/5', 2)]:
            with self.subTest(start=start):
                graph, proof = build_trail_graph('v0', 'out', event(start, end), 10, 8)
                self.assertIn(f'concat=n={expected}:v=1:a=0', graph)
                self.assertEqual(proof['warmup_frames'], 1)
                self.assertEqual(proof['output_frame_count'], 8)
                self.assertNotIn('minterpolate', graph)

    def test_fractional_rate_uses_exact_frame_timebase(self):
        graph, proof = build_trail_graph('v0', 'out', event('1001/30000', '3003/30000'),
                                         Fraction(30000, 1001), 4)
        self.assertIn('trim=start_frame=1:end_frame=3,settb=expr=1001/30000,setpts=N', graph)
        self.assertEqual(proof['frame_rate'], '30000/1001')

    def test_rejects_out_of_bounds_or_unaligned_window(self):
        for row in [event('1/20', '1/10'), event('0', '9/10'), event('1/5', '1/5')]:
            with self.subTest(row=row):
                with self.assertRaises(ValueError):
                    build_trail_graph('v0', 'out', row, 10, 8)


if __name__ == '__main__':
    unittest.main()
