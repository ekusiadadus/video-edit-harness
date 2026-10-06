"""Exact reviewed word-occurrence caption grouping, without media or ASR."""

import copy
import unittest

from video_harness.caption_groups import (annotate_occurrences,
                                          caption_stream_sha256,
                                          group_reviewed_captions)


def cues(*words):
    return [{'id': index, 'start': index * .5, 'end': index * .5 + .4,
             'text': word} for index, word in enumerate(words)]


def plan_for(source, groups, language='ja', phrases=(), minimum=.1, maximum=100):
    marked = annotate_occurrences(source)
    return {'version': 1, 'word_stream_sha256': caption_stream_sha256(source),
            'language': language, 'protected_phrases': list(phrases),
            'groups': [{'id': f'g{index}', 'word_refs': [
                {'word_id': marked[position].get('word_id', marked[position].get('id')),
                 'occurrence_index': marked[position]['occurrence_index']}
                for position in positions], 'reason': 'Reviewed phrase'}
                for index, positions in enumerate(groups)],
            'reading': {'minimum_seconds': minimum,
                        'maximum_units_per_second': maximum}}


class CaptionGroupsTest(unittest.TestCase):
    def test_japanese_negation_name_and_unit_phrases(self):
        source = cues('でき', 'ません。', '山田', '太郎', 'さんは', '5', 'kg', 'です。')
        plan = plan_for(source, [[0, 1], [2, 3, 4], [5, 6, 7]],
                        phrases=['できません。', '山田太郎', '5 kg'])
        result = group_reviewed_captions(source, plan)
        self.assertEqual([c['text'] for c in result['captions']],
                         ['できません。', '山田太郎さんは', '5 kgです。'])
        self.assertEqual(result['status'], 'review_required')
        self.assertEqual(result['reading_metric'], 'nonspace_unicode_codepoints')
        split = plan_for(source, [[0], [1], [2, 3, 4], [5, 6, 7]],
                         phrases=['できません。'])
        with self.assertRaisesRegex(ValueError, 'protected phrase'):
            group_reviewed_captions(source, split)

    def test_english_phrase_and_long_token_rate(self):
        source = cues('New', 'York', 'Supercalifragilisticexpialidocious')
        plan = plan_for(source, [[0, 1], [2]], 'en', ['New York', 'absent'],
                        minimum=.5, maximum=1)
        result = group_reviewed_captions(source, plan)
        self.assertEqual(result['captions'][0]['text'], 'New York')
        self.assertEqual(result['reading_metric'], 'whitespace_words')
        self.assertIn('fast_reading', [d['code'] for d in result['diagnostics']])
        self.assertEqual(next(d for d in result['diagnostics'] if d['group_id'] == 'g1'
                              and d['code'] == 'fast_reading')['units'], 1)
        with self.assertRaisesRegex(ValueError, 'protected phrase'):
            group_reviewed_captions(source,
                plan_for(source, [[0], [1, 2]], 'en', ['New York']))

    def test_repeated_and_reordered_typed_ids(self):
        source = [{'id': 'x', 'start': 0, 'end': .2, 'text': 'a'},
                  {'id': 1, 'start': .2, 'end': .4, 'text': 'b'},
                  {'id': 'x', 'start': .4, 'end': .6, 'text': 'c'},
                  {'id': '1', 'start': .6, 'end': .8, 'text': 'd'},
                  {'id': 1, 'start': .8, 'end': 1, 'text': 'e'}]
        marked = annotate_occurrences(source)
        self.assertEqual([c['occurrence_index'] for c in marked], [0, 0, 1, 0, 1])
        reordered = [marked[i] for i in (2, 1, 0, 4, 3)]
        for index, cue in enumerate(reordered):
            cue['start'], cue['end'] = index * .3, index * .3 + .2
        self.assertEqual([c['occurrence_index'] for c in annotate_occurrences(reordered)],
                         [1, 0, 0, 1, 0])
        self.assertNotEqual(caption_stream_sha256(marked), caption_stream_sha256(reordered))
        result = group_reviewed_captions(reordered,
                                        plan_for(reordered, [[0, 1, 2], [3, 4]], 'en'))
        self.assertEqual(result['captions'][0]['word_refs'][0],
                         {'word_id': 'x', 'occurrence_index': 1})
        self.assertEqual(caption_stream_sha256(reordered), caption_stream_sha256([
            {**cue, 'start': cue['start'] + 10, 'end': cue['end'] + 10}
            for cue in reordered]))

    def test_stale_spelling_and_reference_errors(self):
        source = cues('Hello', 'world')
        good = plan_for(source, [[0], [1]], 'en')
        with self.assertRaisesRegex(ValueError, 'word stream changed'):
            group_reviewed_captions([{**source[0], 'text': 'Hallo'}, source[1]], good)
        for altered in ('unknown', 'duplicate', 'missing', 'reversed'):
            request = copy.deepcopy(good)
            if altered == 'unknown':
                request['groups'][1]['word_refs'][0]['word_id'] = 99
            elif altered == 'duplicate':
                request['groups'][1]['word_refs'][0] = request['groups'][0]['word_refs'][0]
            elif altered == 'missing':
                request['groups'].pop()
            else:
                request['groups'].reverse()
            with self.subTest(altered=altered), self.assertRaises(ValueError):
                group_reviewed_captions(source, request)
        duplicate_id = copy.deepcopy(good)
        duplicate_id['groups'][1]['id'] = 'g0'
        with self.assertRaisesRegex(ValueError, 'unique'):
            group_reviewed_captions(source, duplicate_id)

    def test_junction_at_contiguous_boundary_and_inside_cue(self):
        source = cues('left', 'right')
        source[1]['start'] = source[0]['end']
        request = plan_for(source, [[0, 1]], 'en')
        with self.assertRaisesRegex(ValueError, 'junction'):
            group_reviewed_captions(source, request, junctions=[source[0]['end']])
        with self.assertRaisesRegex(ValueError, 'junction'):
            group_reviewed_captions(source, request, junctions=[.2])
        self.assertEqual(len(group_reviewed_captions(source,
            plan_for(source, [[0], [1]], 'en'), junctions=[source[0]['end']])['captions']), 2)

    def test_frame_expansion_overlap_is_reported_without_time_change(self):
        source = [{'word_id': 'a', 'occurrence_index': 0, 'start': 0,
                   'end': .6, 'text': 'one'},
                  {'word_id': 'b', 'occurrence_index': 0, 'start': .5,
                   'end': 1, 'text': 'two'}]
        self.assertEqual(annotate_occurrences(source), source)
        result = group_reviewed_captions(source, plan_for(source, [[0], [1]], 'en'))
        self.assertEqual([(c['start'], c['end']) for c in result['captions']],
                         [(0, .6), (.5, 1)])
        self.assertEqual(next(d for d in result['diagnostics']
                              if d['code'] == 'overlapping_captions')['overlap_seconds'],
                         .6 - .5)
        reversed_end = [{**source[0], 'end': 1.1}, source[1]]
        with self.assertRaisesRegex(ValueError, 'monotonic'):
            group_reviewed_captions(reversed_end, plan_for(reversed_end, [[0], [1]], 'en'))

    def test_reading_and_punctuation_diagnostics(self):
        source = cues('。', '長い言葉', '「')
        result = group_reviewed_captions(source,
            plan_for(source, [[0], [1], [2]], minimum=.5, maximum=2))
        codes = [d['code'] for d in result['diagnostics']]
        self.assertIn('short_duration', codes)
        self.assertIn('fast_reading', codes)
        self.assertIn('leading_closing_punctuation', codes)
        self.assertIn('trailing_opening_punctuation', codes)

    def test_invalid_inputs_and_empty_stream(self):
        empty = plan_for([], [])
        result = group_reviewed_captions([], empty)
        self.assertEqual(result['captions'], [])
        self.assertEqual(result['diagnostics'], [])
        for bad in (True, float('nan'), float('inf'), 0, -1):
            request = copy.deepcopy(empty)
            request['reading']['minimum_seconds'] = bad
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                group_reviewed_captions([], request)
        for bad in (True, float('nan'), float('-inf'), 0):
            request = copy.deepcopy(empty)
            request['reading']['maximum_units_per_second'] = bad
            with self.subTest(rate=bad), self.assertRaises(ValueError):
                group_reviewed_captions([], request)
        with self.assertRaises(ValueError):
            caption_stream_sha256([{'id': True, 'text': 'word'}])
        with self.assertRaises(ValueError):
            annotate_occurrences([{'id': 1, 'occurrence_index': True}])
        with self.assertRaises(ValueError):
            group_reviewed_captions([{'id': 1, 'start': 0, 'end': float('inf'),
                                     'text': 'word'}], plan_for(cues('word'), [[0]]))


if __name__ == '__main__':
    unittest.main()
