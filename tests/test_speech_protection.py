"""Transcript word protection on the assembled source-edit timeline."""

from copy import deepcopy
from pathlib import Path
import tempfile
import unittest

from video_harness.common import fingerprint
from video_harness.edl import build_plan, validate_plan
from video_harness.editorial import build_story_plan, make_brief
from video_harness.render_cache import digest
from video_harness.speech_protection import derive_speech_protection


class SpeechProtectionTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        source = Path(tmp.name) / 'source.mov'
        source.write_bytes(b'synthetic source')
        self.cfg = {'source': str(source), 'editorial': {'goal': 'Tell story'}}
        self.transcript = {'version': 1, 'source': fingerprint(source), 'duration': 4.,
            'words': [
                {'id': 'a', 'start': .1, 'end': .3, 'text': 'First', 'probability': .9},
                {'id': 'b', 'start': 1., 'end': 1.2, 'text': 'Extra', 'probability': .9},
                {'id': 'c', 'start': 2., 'end': 2.2, 'text': 'Second', 'probability': .9},
                {'id': 'd', 'start': 3., 'end': 3.2, 'text': 'Third', 'probability': .9},
            ], 'segments': []}

    def mapping(self, plan, *, fps=10, keep=None):
        if keep is None:
            keep = validate_plan(plan)
        duration = sum(end - start for start, end in keep)
        return {'source': deepcopy(plan['source']), 'keep': [list(span) for span in keep],
                'duration': duration}

    def test_v2_cuts_omit_word_and_preserve_ids(self):
        plan = build_plan(self.cfg, self.transcript)
        plan['cuts'] = [{'id': 1, 'start': 1., 'end': 1.2, 'enabled': True,
                         'kind': 'speech', 'removed_word_ids': ['b'],
                         'review_note': 'Remove repeated word'}]
        mapping = self.mapping(plan)
        result = derive_speech_protection(plan, mapping, fps=10, frame_count=38)
        self.assertEqual([w['word_id'] for w in result['word_occurrences']], ['a', 'c', 'd'])
        self.assertEqual(result['protected_intervals'], [[1, 3], [18, 20], [28, 30]])
        self.assertEqual(result['input_mapping_sha256'], digest(mapping))
        self.assertEqual(result['plan_sha256'], digest(plan))
        self.assertTrue(result['review_required'])

    def test_partial_word_from_aligned_v2_keep_is_protected(self):
        plan = build_plan(self.cfg, self.transcript)
        # A source end aligned a few milliseconds inside the final word.
        keep = [(0., 3.195)]
        # The reviewed span must end near the aligned span.
        plan['duration'] = 3.2
        plan['transcript']['duration'] = 3.2
        from video_harness.edl import _digest
        plan['transcript_sha256'] = _digest(plan['transcript'])
        mapping = self.mapping(plan, keep=keep)
        # 639/200 seconds is exactly 639 frames at 200 fps.
        result = derive_speech_protection(plan, mapping, fps=200, frame_count=639)
        partial = result['word_occurrences'][-1]
        self.assertEqual(partial['word_id'], 'd')
        self.assertTrue(partial['partial'])
        self.assertEqual((partial['start_frame'], partial['end_frame_exclusive']), (600, 639))

    def test_partial_word_at_fractional_frame_start_clips_to_output_zero(self):
        transcript = deepcopy(self.transcript)
        transcript['duration'] = 1.
        transcript['words'] = [
            {'id': 'crosses', 'start': .32, 'end': .4,
             'text': 'Crosses', 'probability': .9}]
        plan = build_plan(self.cfg, transcript)
        plan['editing_settings']['word_padding'] = 0
        plan['acoustic_intervals'] = [[0., .3]]
        plan['cuts'] = [{'id': 1, 'start': 0., 'end': .3, 'enabled': True,
                         'kind': 'pause', 'review_note': 'Acoustic interval checked'}]
        mapping = self.mapping(plan, keep=[(1 / 3, 1.)])
        result = derive_speech_protection(plan, mapping, fps=30, frame_count=20)
        word = result['word_occurrences'][0]
        self.assertTrue(word['partial'])
        self.assertEqual((word['start_frame'], word['end_frame_exclusive']), (0, 2))
        self.assertEqual(result['protected_intervals'], [[0, 2]])

    def test_v3_order_and_omission(self):
        brief = make_brief(self.cfg)
        spec = {'chapters': [
            {'id': 'lead', 'goal_ids': ['goal-1'], 'spans': [
                {'id': 'c', 'start_word_id': 'c', 'end_word_id': 'd', 'reason': 'Lead with outcome'}]},
            {'id': 'setup', 'goal_ids': ['goal-1'], 'spans': [
                {'id': 'a', 'start_word_id': 'a', 'end_word_id': 'a', 'reason': 'Then context'}]}],
            'omissions': [{'word_ids': ['b'], 'goal_ids': ['goal-1'], 'reason': 'Aside'}]}
        plan = build_story_plan(self.cfg, self.transcript, brief, spec)
        mapping = self.mapping(plan)
        result = derive_speech_protection(plan, mapping, fps=100, frame_count=172)
        self.assertEqual([w['word_id'] for w in result['word_occurrences']], ['c', 'd', 'a'])
        self.assertEqual([w['occurrence_index'] for w in result['word_occurrences']], [0, 0, 0])

    def test_fractional_fps_expands_and_merges_touching_frames(self):
        plan = build_plan(self.cfg, self.transcript)
        plan['transcript']['words'] = [
            {'id': 'x', 'start': .02, 'end': .05, 'text': 'x', 'probability': .9},
            {'id': 'y', 'start': .05, 'end': .08, 'text': 'y', 'probability': .9}]
        from video_harness.edl import _digest
        plan['duration'] = 4.004
        plan['transcript']['duration'] = 4.004
        plan['transcript_sha256'] = _digest(plan['transcript'])
        mapping = self.mapping(plan)
        result = derive_speech_protection(plan, mapping, fps='30000/1001', frame_count=120)
        self.assertEqual(result['protected_intervals'], [[0, 3]])

    def test_raw_word_edges_protect_frames_lost_by_subtitle_rounding(self):
        transcript = deepcopy(self.transcript)
        transcript['duration'] = 1.
        transcript['words'] = [
            {'id': 'edge', 'start': .19999999, 'end': .50000001,
             'text': 'Edge', 'probability': .9}]
        plan = build_plan(self.cfg, transcript)
        result = derive_speech_protection(plan, self.mapping(plan), fps=30, frame_count=30)
        word = result['word_occurrences'][0]
        self.assertEqual((word['start'], word['end']), (.2, .5))
        self.assertEqual((word['start_frame'], word['end_frame_exclusive']), (5, 16))
        self.assertEqual(result['protected_intervals'], [[5, 16]])

    def test_v3_aligned_spans_keep_repeated_word_occurrences(self):
        transcript = deepcopy(self.transcript)
        transcript['duration'] = .4
        transcript['words'] = [
            {'id': 'tiny', 'start': .08999999, 'end': .09999999, 'text': 'A', 'probability': .9},
            {'id': 'next', 'start': .2, 'end': .3, 'text': 'B', 'probability': .9}]
        brief = make_brief(self.cfg)
        spec = {'chapters': [{'id': 'one', 'goal_ids': ['goal-1'], 'spans': [
                    {'id': 's1', 'start_word_id': 'tiny', 'end_word_id': 'tiny',
                     'pad_before': .00999999, 'pad_after': .00000001, 'reason': 'Opening'},
                    {'id': 's2', 'start_word_id': 'next', 'end_word_id': 'next',
                     'pad_before': .09, 'pad_after': 0, 'reason': 'Repeat overlap'}]}],
                'omissions': []}
        plan = build_story_plan(self.cfg, transcript, brief, spec)
        mapping = self.mapping(plan, keep=[(.08, .1), (.08, .3)])
        result = derive_speech_protection(plan, mapping, fps=100, frame_count=24)
        self.assertEqual([w['word_id'] for w in result['word_occurrences']],
                         ['tiny', 'tiny', 'next'])
        self.assertEqual([w['occurrence_index'] for w in result['word_occurrences']],
                         [0, 1, 0])
        repeated = result['word_occurrences'][1]
        self.assertEqual(repeated['start'], .03)
        self.assertEqual((repeated['start_frame'], repeated['end_frame_exclusive']), (2, 4))

    def test_empty_words_require_review(self):
        plan = build_plan(self.cfg, self.transcript)
        plan['transcript']['words'] = []
        from video_harness.edl import _digest
        plan['transcript_sha256'] = _digest(plan['transcript'])
        result = derive_speech_protection(plan, self.mapping(plan), fps=10, frame_count=40)
        self.assertEqual(result['protected_intervals'], [])
        self.assertEqual(result['word_occurrences'], [])
        self.assertTrue(result['review_required'])

    def test_source_duration_and_bounds_fail_closed(self):
        plan = build_plan(self.cfg, self.transcript)
        mapping = self.mapping(plan)
        wrong_source = deepcopy(mapping)
        wrong_source['source']['sha256'] = '0' * 64
        with self.assertRaisesRegex(ValueError, 'source differs'):
            derive_speech_protection(plan, wrong_source, fps=10, frame_count=40)
        wrong_duration = deepcopy(mapping)
        wrong_duration['duration'] = 2.
        with self.assertRaisesRegex(ValueError, 'frame dimensions'):
            derive_speech_protection(plan, wrong_duration, fps=10, frame_count=40)
        with self.assertRaisesRegex(ValueError, 'frame dimensions'):
            derive_speech_protection(plan, mapping, fps=10, frame_count=39)
        beyond_source = self.mapping(plan, keep=[(0., 4.06)])
        with self.assertRaisesRegex(ValueError, 'aligned keep'):
            derive_speech_protection(plan, beyond_source, fps=50, frame_count=203)
        with self.assertRaisesRegex(ValueError, 'Invalid fps'):
            derive_speech_protection(plan, mapping, fps=float('nan'), frame_count=40)


if __name__ == '__main__':
    unittest.main()
