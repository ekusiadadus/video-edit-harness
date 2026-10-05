import copy
import tempfile
import unittest
from pathlib import Path

from video_harness.common import fingerprint
from video_harness.edl import derive_edit, remap_subtitles, validate_plan, write_srt
from video_harness.editorial import approve_story, build_story_plan, make_brief, pack_transcript, revise_story, revise_pause_plan
from video_harness.edl import build_plan


class EditorialTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        source = Path(self.tmp.name) / 'source.mov'
        source.write_bytes(b'source')
        self.cfg = {'source': str(source), 'editorial': {'goal': 'Explain the result'}}
        self.transcript = {'version': 1, 'source': fingerprint(source), 'duration': 5.,
                           'words': [{'id': i, 'start': s, 'end': e, 'text': text, 'probability': .9}
                                     for i, s, e, text in ((1,.5,.8,'First.'),(2,1.,1.3,'Extra.'),(3,2.,2.3,'Second.'),(4,3.,3.3,'Third.'))],
                           'segments': [{'id': 1, 'start': .5, 'end': 1.3, 'text': 'First. Extra.'},
                                        {'id': 2, 'start': 2., 'end': 3.3, 'text': 'Second. Third.'}]}
        self.brief = make_brief(self.cfg, {'must_keep_word_ids': [1, 3]})
        self.spec = {'chapters': [
            {'id': 'ending', 'title': 'Result', 'goal_ids': ['goal-1'], 'spans': [
                {'id': 's3', 'start_word_id': 3, 'end_word_id': 4, 'reason': 'Lead with result'}]},
            {'id': 'opening', 'title': 'Setup', 'goal_ids': ['goal-1'], 'spans': [
                {'id': 's1', 'start_word_id': 1, 'end_word_id': 1, 'reason': 'Keep premise'}]}],
            'omissions': [{'word_ids': [2], 'reason': 'Repeated aside', 'goal_ids': ['goal-1']}]}

    def plan(self):
        return build_story_plan(self.cfg, self.transcript, self.brief, self.spec)

    def test_pack_preserves_source_anchors_without_inventing_chapters(self):
        packed = pack_transcript(self.transcript, self.brief)
        self.assertEqual(packed['words'][1]['id'], 2)
        self.assertEqual(packed['chapter_candidates'], [])
        self.assertEqual(packed['phrases'][0]['word_ids'], [1, 2])

    def test_ordered_story_and_subtitles(self):
        plan = self.plan()
        self.assertGreater(validate_plan(plan)[0][0], validate_plan(plan)[1][0])
        self.assertEqual([cue['id'] for cue in remap_subtitles(plan)], [3, 4, 1])
        self.assertEqual(plan['omitted_word_ids'], [2])
        self.assertAlmostEqual(derive_edit(plan)['duration'], sum(e-s for s,e in validate_plan(plan)))
        target = Path(self.tmp.name) / 'captions.srt'
        write_srt(plan, target)
        self.assertLess(target.read_text().find('Second.'), target.read_text().find('First.'))

    def test_omission_protection_duplicate_partial_fade_and_alignment(self):
        plan = self.plan()
        for mutation in (
            lambda p: p.update(omitted_word_ids=[]),
            lambda p: p['omissions'][0].update(reason=''),
            lambda p: p['sequence'].append(copy.deepcopy(p['sequence'][0])),
            lambda p: p['sequence'][0].update(start=2.1),
            lambda p: p['sequence'][0].update(fade_in_seconds=.2),
        ):
            candidate = copy.deepcopy(plan)
            mutation(candidate)
            with self.assertRaises(ValueError):
                validate_plan(candidate)
        candidate = copy.deepcopy(plan)
        candidate['protected_ranges'] = [[.9, 1.1]]
        with self.assertRaisesRegex(ValueError, 'Protected range'):
            validate_plan(candidate)
        aligned = [(s, e+.01) for s,e in validate_plan(plan)]
        self.assertEqual(len(remap_subtitles(plan, keep=aligned)), 3)
        aligned[1] = (aligned[1][0], 1.05)
        with self.assertRaises(ValueError):
            remap_subtitles(plan, keep=aligned)

    def test_approval_and_revision_are_immutable(self):
        plan = self.plan()
        approved = approve_story(plan, 'human:owner', 'Listened to rough cut')
        self.assertEqual(plan['status'], 'review_required')
        self.assertEqual(approved['status'], 'reviewed_selection')
        revised = revise_story(approved, [{'op': 'reorder', 'ids': ['s1', 's3'],
                                           'reason': 'Setup first', 'goal_ids': ['goal-1']}],
                               'agent:codex', 'Propose clearer opening')
        self.assertEqual(revised['status'], 'review_required')
        self.assertEqual(approved['sequence'][0]['id'], 's3')
        self.assertEqual(revised['sequence'][0]['id'], 's1')
        self.assertEqual(revised['revisions'][-1]['actor'], 'agent:codex')
        with self.assertRaises(ValueError):
            approve_story(plan, '', 'note')

    def test_restore_and_remove_span(self):
        brief = copy.deepcopy(self.brief)
        brief['must_keep_word_ids'] = []
        plan = build_story_plan(self.cfg, self.transcript, brief, self.spec)
        removed = revise_story(plan, [{'op':'remove','id':'s1','reason':'Shorten','goal_ids':['goal-1']}],
                               'agent:codex', 'Alternative')
        self.assertEqual(removed['omitted_word_ids'], [1, 2])
        restored = revise_story(removed, [{'op':'restore','id':'s1','reason':'Context','goal_ids':['goal-1']}],
                                'human:owner', 'Bring context back')
        self.assertEqual(restored['omitted_word_ids'], [2])

    def test_retime_span_updates_exact_omission_evidence(self):
        brief = copy.deepcopy(self.brief)
        brief['must_keep_word_ids'] = []
        plan = build_story_plan(self.cfg, self.transcript, brief, self.spec)
        revised = revise_story(plan, [{'op': 'retime', 'id': 's3', 'start_word_id': 4,
                                       'end_word_id': 4, 'reason': 'Trim repetition',
                                       'goal_ids': ['goal-1']}], 'agent:codex', 'Shorter ending')
        self.assertEqual(revised['omitted_word_ids'], [2, 3])
        self.assertEqual({i for o in revised['omissions'] for i in o['word_ids']}, {2, 3})

    def test_v2_cut_revision_keeps_existing_validation(self):
        plan = build_plan(self.cfg, self.transcript)
        revised = revise_pause_plan(plan, [{'op': 'add_speech', 'start': 1., 'end': 1.3,
                                            'removed_word_ids': [2], 'reason': 'Repeated'}],
                                    'human:owner', 'Remove aside')
        self.assertEqual([c['id'] for c in remap_subtitles(revised)], [1, 3, 4])
        self.assertEqual(len(plan['cuts']), len(build_plan(self.cfg, self.transcript)['cuts']))


if __name__ == '__main__':
    unittest.main()
