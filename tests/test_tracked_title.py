import copy
import math
import unittest

from video_harness.tracked_title import compile_title_positions, validate_follow_parameters


CARD = [.4, .4, .6, .5]


def row(frame, box, state="tracked"):
    return {"frame": frame, "box": box, "state": state, "quality": {"observed": True}}


class TrackedTitleTests(unittest.TestCase):
    def test_moving_above_positions_use_integer_translation_of_original_png(self):
        rows = [row(3, [.3, .5, .5, .8], "manual"),
                row(4, [.4, .5, .6, .8])]
        original = copy.deepcopy(rows)
        positions = compile_title_positions(rows, 3, 5, 1000, 500, CARD, {})
        self.assertEqual(rows, original)
        self.assertEqual(positions, [
            {"frame": 3, "bounds": [.3, .38, .5, .48], "x_pixels": -100, "y_pixels": -10},
            {"frame": 4, "bounds": [.4, .38, .6, .48], "x_pixels": 0, "y_pixels": -10},
        ])

    def test_side_placement_and_offsets(self):
        rows = [row(0, [.3, .5, .5, .8])]
        positions = compile_title_positions(rows, 0, 1, 1000, 500, CARD,
                                            {"placement": "right", "offset_x": .01,
                                             "offset_y": -.02})
        self.assertEqual(positions, [{"frame": 0, "bounds": [.53, .58, .73, .68],
                                      "x_pixels": 130, "y_pixels": 90}])

    def test_defaults_and_strict_controls(self):
        self.assertEqual(validate_follow_parameters({}),
                         {"placement": "above", "gap_fraction": .02,
                          "offset_x": 0., "offset_y": 0.})
        for controls in ({"placement": "center"}, {"text": "not a control"},
                         {"gap_fraction": -.01}, {"gap_fraction": .21},
                         {"offset_x": -.51}, {"offset_y": .51},
                         {"gap_fraction": math.nan}, {"offset_x": True},
                         {"placement": []}):
            with self.subTest(controls=controls), self.assertRaises(ValueError):
                validate_follow_parameters(controls)

    def test_lost_missing_and_malformed_observations_fail(self):
        valid = row(0, [.3, .5, .5, .8])
        invalid = (
            [row(0, None, "lost")],
            [],
            [row(1, [.3, .5, .5, .8])],
            [row(0, [.3, .5, math.nan, .8])],
            [row(0, [.3, .5, .2, .8])],
            [row(0, [-.1, .5, .5, .8])],
            [{"frame": 0, "box": valid["box"]}],
        )
        for rows in invalid:
            with self.subTest(rows=rows), self.assertRaises(ValueError):
                compile_title_positions(rows, 0, 1, 1000, 500, CARD, {})

    def test_out_of_frame_and_malformed_geometry_fail(self):
        with self.assertRaisesRegex(ValueError, "leaves the frame"):
            compile_title_positions([row(0, [.3, .05, .5, .3])],
                                    0, 1, 1000, 500, CARD, {})
        for width, height, card in ((0, 500, CARD), (1000, math.nan, CARD),
                                    (1000, 500, [.4, .4, .4, .5]),
                                    (1000, 500, [.4, .4, math.nan, .5])):
            with self.subTest(width=width, height=height, card=card), self.assertRaises(ValueError):
                compile_title_positions([row(0, [.3, .5, .5, .8])],
                                        0, 1, width, height, card, {})


if __name__ == "__main__":
    unittest.main()
