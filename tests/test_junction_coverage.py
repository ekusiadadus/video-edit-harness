"""Long-form junction reports expose skipped IDs and bind review coverage."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from video_harness.common import read
from video_harness.editing import _audition_sequence
from video_harness.session import validate_junction_coverage


class JunctionCoverageTests(unittest.TestCase):
    def test_twenty_six_junctions_paginate_with_visible_remaining_ids(self):
        sequence = [{'id': f's{i}', 'start': i * 2.0, 'end': i * 2.0 + 1.0,
                     'reason': 'Synthetic junction'} for i in range(27)]
        plan = {'sequence': sequence, 'duration': 54.0}
        with tempfile.TemporaryDirectory() as tmp, patch('video_harness.editing.run'):
            root = Path(tmp)
            first = root / 'first'
            second = root / 'second'
            _audition_sequence({'source': 'synthetic.mov'}, plan, first, None, 1.0, 0, 24)
            _audition_sequence({'source': 'synthetic.mov'}, plan, second, None, 1.0, 24, 24)
            a, b = read(first / 'junctions.json'), read(second / 'junctions.json')
            self.assertEqual((a['generated_count'], a['total_candidates']), (24, 26))
            self.assertEqual(a['remaining_ids'], ['s24', 's25'])
            self.assertEqual([i['id'] for i in b['items']], ['s24', 's25'])

    def test_review_coverage_requires_exact_render_and_each_junction(self):
        ids = [f's{i}' for i in range(26)]
        base = {'render_sha256': 'a' * 64, 'mode': 'selected',
                'reviewed_ids': ids[:25], 'waived': [], 'note': 'Synthetic review'}
        with self.assertRaisesRegex(ValueError, 'every selected cut'):
            validate_junction_coverage(base, 'a' * 64, ids)
        with self.assertRaisesRegex(ValueError, 'exact render'):
            validate_junction_coverage(base, 'b' * 64, ids)
        with self.assertRaisesRegex(ValueError, 'at least one listened'):
            validate_junction_coverage({**base, 'reviewed_ids': [],
                                        'waived': [{'id': item, 'reason': 'Omitted'} for item in ids]},
                                       'a' * 64, ids)
        validate_junction_coverage({**base, 'waived': [{'id': ids[-1], 'reason': 'Explicitly omitted'}]},
                                   'a' * 64, ids)
        validate_junction_coverage({'render_sha256': 'a' * 64, 'mode': 'full_listening',
                                    'note': 'Listened to the complete output'}, 'a' * 64, ids)


if __name__ == '__main__':
    unittest.main()
