import unittest

from video_harness.title_collisions import check_title_collisions


LEFT = [0.05, 0.1, 0.35, 0.3]
RIGHT = [0.55, 0.1, 0.85, 0.3]
MIDDLE = [0.25, 0.1, 0.65, 0.3]


def event(event_id, kind='keyword_title', first=0, last=5):
    return {'id': event_id, 'type': kind,
            'output_start': str(first), 'output_end': str(last)}


def asset(event_id, bounds, positions=None):
    result = {'event_id': event_id, 'bounds': bounds}
    if positions is not None:
        result['frame_positions'] = [
            {'frame': frame, 'bounds': box} for frame, box in enumerate(positions)]
    return result


class TitleCollisionsTest(unittest.TestCase):
    def test_rise_requires_positions_and_roundoff_is_not_a_collision(self):
        rising = {**event('a'), 'parameters': {'motion': 'rise'}}
        with self.assertRaisesRegex(ValueError, 'Missing positions for rising title'):
            check_title_collisions([rising, event('b')],
                                   [asset('a', LEFT), asset('b', RIGHT)], fps=1)
        touched = [LEFT[2]-1e-16, .1, .65, .3]
        self.assertEqual(check_title_collisions([event('a'), event('b')],
                         [asset('a', LEFT), asset('b', touched)], fps=1)[0]['frames_checked'],4)

    def test_fixed_titles_collide_on_visible_frame(self):
        with self.assertRaisesRegex(ValueError, r'a and b at frame 1 \(output time 1s\)'):
            check_title_collisions([event('a'), event('b')],
                                   [asset('a', LEFT), asset('b', MIDDLE)], fps=1)

    def test_fixed_titles_clear_and_exact_exclusive_interval(self):
        result = check_title_collisions([event('a'), event('b')],
                                        [asset('a', LEFT), asset('b', RIGHT)], fps=1)
        self.assertEqual(result, [{'event_ids': ['a', 'b'], 'output_start': '1',
                                   'output_end': '5', 'status': 'no_detected_conflict',
                                   'frames_checked': 4}])

    def test_contact_has_no_area(self):
        result = check_title_collisions([event('a'), event('b')],
                                        [asset('a', LEFT), asset('b', [0.35, 0.1, 0.65, 0.3])], fps=1)
        self.assertEqual(result[0]['frames_checked'], 4)

    def test_temporally_disjoint_and_end_exclusive(self):
        events = [event('a', first=0, last=2), event('b', first=2, last=4)]
        self.assertEqual(check_title_collisions(events, [asset('a', LEFT), asset('b', LEFT)], fps=1), [])

    def test_first_fade_frame_is_transparent(self):
        events = [event('a', first=0, last=3), event('b', first=1, last=3)]
        with self.assertRaisesRegex(ValueError, r'a and b at frame 2'):
            check_title_collisions(events, [asset('a', LEFT), asset('b', LEFT)], fps=1)

    def test_only_shared_first_frame_has_no_visible_pair(self):
        events = [event('a', first=0, last=2), event('b', first=1, last=2)]
        self.assertEqual(check_title_collisions(events, [asset('a', LEFT), asset('b', LEFT)], fps=1), [])

    def test_fixed_and_tracked_cross_late(self):
        tracked = asset('b', RIGHT, [RIGHT, RIGHT, RIGHT, RIGHT, MIDDLE])
        with self.assertRaisesRegex(ValueError, r'a and b at frame 4'):
            check_title_collisions([event('a'), event('b', 'tracked_title')],
                                   [asset('a', LEFT), tracked], fps=1)

    def test_two_tracked_titles_cross_late(self):
        a = asset('a', LEFT, [LEFT] * 5)
        b = asset('b', RIGHT, [RIGHT] * 4 + [MIDDLE])
        with self.assertRaisesRegex(ValueError, r'a and b at frame 4'):
            check_title_collisions([event('a', 'tracked_title'), event('b', 'tracked_title')],
                                   [a, b], fps=1)

    def test_keyword_position_overrides_fixed_bounds(self):
        a = asset('a', LEFT, [LEFT] * 4 + [MIDDLE])
        with self.assertRaisesRegex(ValueError, r'a and b at frame 4'):
            check_title_collisions([event('a'), event('b')], [a, asset('b', RIGHT)], fps=1)

    def test_missing_or_duplicate_positions_fail(self):
        events = [event('a', 'tracked_title'), event('b')]
        with self.assertRaisesRegex(ValueError, r'Missing positions for tracked title a'):
            check_title_collisions(events, [asset('a', LEFT), asset('b', RIGHT)], fps=1)
        missing = asset('a', LEFT, [LEFT] * 4)
        with self.assertRaisesRegex(ValueError, r'Missing position for title a at frame 4'):
            check_title_collisions(events, [missing, asset('b', RIGHT)], fps=1)
        duplicate = asset('a', LEFT, [LEFT] * 5)
        duplicate['frame_positions'].append({'frame': 3, 'bounds': LEFT})
        with self.assertRaisesRegex(ValueError, r'Duplicate position for title a at frame 3'):
            check_title_collisions(events, [duplicate, asset('b', RIGHT)], fps=1)

    def test_malformed_bounds_and_duplicate_assets_fail(self):
        events = [event('a'), event('b')]
        with self.assertRaisesRegex(ValueError, r'Title a bounds'):
            check_title_collisions(events, [asset('a', [0, 0, 2, 1]), asset('b', RIGHT)], fps=1)
        with self.assertRaisesRegex(ValueError, r'Duplicate measured title asset for a'):
            check_title_collisions(events, [asset('a', LEFT), asset('a', LEFT), asset('b', RIGHT)], fps=1)

    def test_rational_output_times(self):
        events = [event('a', first=0, last='1001/10000'),
                  event('b', first=0, last='1001/10000')]
        result = check_title_collisions(events, [asset('a', LEFT), asset('b', RIGHT)],
                                        fps='30000/1001')
        self.assertEqual(result[0]['output_start'], '1001/30000')
        self.assertEqual(result[0]['output_end'], '1001/10000')
        self.assertEqual(result[0]['frames_checked'], 2)


if __name__ == '__main__':
    unittest.main()
