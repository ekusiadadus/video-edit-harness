import copy
import tempfile
import unittest
from pathlib import Path

from video_harness.common import fingerprint
from video_harness.edl import build_plan, derive_edit, group_captions, remap_subtitles, validate_plan, write_srt


class EditPlanTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.source = Path(self.tmp.name) / 'source.mov'
        self.source.write_bytes(b'original media')
        self.cfg = {'source': str(self.source)}
        self.transcript = {
            'version': 1, 'source': fingerprint(self.source), 'duration': 5.0,
            'words': [
                {'id': 1, 'start': 0.5, 'end': 1.0, 'text': 'Hello.', 'probability': 0.9},
                {'id': 2, 'start': 2.0, 'end': 2.5, 'text': 'There', 'probability': 0.9},
                {'id': 3, 'start': 3.5, 'end': 4.0, 'text': 'again', 'probability': 0.9},
            ],
            'segments': [
                {'id': 1, 'start': 0.5, 'end': 1.0, 'text': 'Hello.'},
                {'id': 2, 'start': 2.0, 'end': 4.0, 'text': 'There again'},
            ],
        }

    def plan(self, silences=((1.1, 1.9), (2.6, 3.4))):
        return build_plan(self.cfg, self.transcript, silences)

    def test_transcript_only_candidates_disabled_and_full_keep(self):
        plan = build_plan(self.cfg, self.transcript)
        self.assertTrue(plan['warnings'])
        self.assertTrue(plan['cuts'])
        self.assertTrue(all(not cut['enabled'] for cut in plan['cuts']))
        self.assertEqual(validate_plan(plan), [(0.0, 5.0)])
        self.assertEqual(derive_edit(plan)['removed_seconds'], 0)
        self.assertEqual(len(remap_subtitles(plan)), 3)

    def test_acoustic_candidates_are_disabled_and_respect_boundary_margin(self):
        plan = self.plan()
        self.assertEqual(len(plan['cuts']), 2)
        self.assertAlmostEqual(plan['cuts'][0]['start'] - 1.0 + 2.0 - plan['cuts'][0]['end'], 0.5)
        self.assertEqual(plan['cuts'][0]['kind'], 'pause')
        self.assertEqual(plan['cuts'][0]['previous_words'], ['Hello.'])

    def test_enabled_pause_requires_review_and_cannot_overlap_speech_or_padding(self):
        plan = self.plan()
        plan['cuts'][0]['enabled'] = True
        with self.assertRaisesRegex(ValueError, 'review note'):
            validate_plan(plan)
        plan['cuts'][0]['review_note'] = 'Listened to the pause'
        self.assertEqual(len(validate_plan(plan)), 2)
        plan['cuts'][0]['start'] = 0.95
        with self.assertRaisesRegex(ValueError, 'padded word'):
            validate_plan(plan)
        plan['cuts'][0]['start'] = 1.04
        with self.assertRaisesRegex(ValueError, 'padded word'):
            validate_plan(plan)

    def test_transcript_gap_alone_cannot_be_enabled(self):
        plan = build_plan(self.cfg, self.transcript)
        plan['cuts'][0]['enabled'] = True
        plan['cuts'][0]['review_note'] = 'Looks quiet'
        with self.assertRaisesRegex(ValueError, 'acoustic silence'):
            validate_plan(plan)

    def test_protected_range_blocks_candidate_and_later_edit(self):
        cfg = copy.deepcopy(self.cfg)
        cfg['editorial'] = {'protected_ranges': [[1.2, 1.4]]}
        plan = build_plan(cfg, self.transcript, [(1.1, 1.9)])
        self.assertEqual(plan['cuts'], [])
        plan = self.plan()
        plan['protected_ranges'] = [[1.2, 1.4]]
        with self.assertRaisesRegex(ValueError, 'protected range'):
            validate_plan(plan)

    def test_subtitle_remap_and_frame_aligned_override(self):
        plan = self.plan()
        cut = plan['cuts'][0]
        cut['enabled'] = True
        cut['review_note'] = 'Listened and approved'
        edit = derive_edit(plan)
        self.assertEqual(edit['keep'], [(0.0, cut['start']), (cut['end'], 5.0)])
        cues = remap_subtitles(plan)
        self.assertAlmostEqual(cues[1]['start'], 2.0 - (cut['end'] - cut['start']))
        aligned = [(0.0, cut['start'] + 0.01), (cut['end'] - 0.01, 5.0)]
        self.assertAlmostEqual(remap_subtitles(plan, keep=aligned)[1]['start'],
                               2.0 - (aligned[1][0] - aligned[0][1]))
        target = Path(self.tmp.name) / 'captions.srt'
        write_srt(plan, target, keep=aligned)
        self.assertIn('Hello.', target.read_text())
        self.assertIn('-->', target.read_text())

    def test_aligned_keep_may_extend_one_frame_past_reported_duration(self):
        plan = self.plan()
        aligned = [(0.0, 5.02)]
        self.assertEqual(len(remap_subtitles(plan, keep=aligned)), 3)
        target = Path(self.tmp.name) / 'aligned.srt'
        write_srt(plan, target, keep=aligned)
        self.assertTrue(target.is_file())
        with self.assertRaisesRegex(ValueError, 'aligned keep'):
            remap_subtitles(plan, keep=[(0.0, 5.06)])

    def test_group_captions_joins_japanese_and_latin_and_bounds_phrases(self):
        cues = [
            {'start': 0.0, 'end': 0.3, 'text': '今日は'},
            {'start': 0.31, 'end': 0.6, 'text': '晴れ'},
            {'start': 0.61, 'end': 0.9, 'text': 'です。'},
            {'start': 1.0, 'end': 1.2, 'text': 'Hello'},
            {'start': 1.21, 'end': 1.4, 'text': 'world'},
            {'start': 2.1, 'end': 2.3, 'text': 'again'},
        ]
        grouped = group_captions(cues)
        self.assertEqual([cue['text'] for cue in grouped], ['今日は晴れです。', 'Hello world', 'again'])
        self.assertTrue(all(cue['end'] - cue['start'] <= 4.0 for cue in grouped))
        self.assertEqual([cue['text'] for cue in group_captions(cues[:2], junctions=[0.3])], ['今日は', '晴れ'])

    def test_speech_deletion_requires_explicit_word_ids_and_review_note(self):
        plan = self.plan(silences=())
        speech = {'id': 1, 'start': 2.0, 'end': 2.5, 'enabled': True,
                  'kind': 'speech', 'review_note': 'Explicitly remove this word',
                  'removed_word_ids': [2]}
        plan['cuts'] = [speech]
        self.assertEqual([cue['id'] for cue in remap_subtitles(plan)], [1, 3])
        speech['removed_word_ids'] = []
        with self.assertRaisesRegex(ValueError, 'removed word ids'):
            validate_plan(plan)
        speech['removed_word_ids'] = [2]
        speech['start'] = 2.1
        with self.assertRaisesRegex(ValueError, 'part of a word'):
            validate_plan(plan)

    def test_source_drift_and_transcript_mutation_rejected(self):
        plan = self.plan()
        plan['transcript']['words'][0]['text'] = 'tampered'
        with self.assertRaisesRegex(ValueError, 'evidence changed'):
            validate_plan(plan)
        plan = self.plan()
        self.source.write_bytes(b'changed media')
        with self.assertRaisesRegex(ValueError, 'Source changed'):
            validate_plan(plan, verify_source=True)

    def test_invalid_disabled_cuts_and_duplicate_ids_rejected(self):
        plan = self.plan()
        plan['cuts'][0]['start'] = float('nan')
        with self.assertRaisesRegex(ValueError, 'Invalid cut'):
            validate_plan(plan)
        plan = self.plan()
        plan['cuts'][1]['id'] = plan['cuts'][0]['id']
        with self.assertRaisesRegex(ValueError, 'duplicate cut id'):
            validate_plan(plan)


if __name__ == '__main__':
    unittest.main()
