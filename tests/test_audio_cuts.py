"""Focused source-handle behavior; no transcription or listening inference."""
import copy
from pathlib import Path
import struct
import tempfile
import unittest
import wave

from video_harness.audio_cuts import (captions_srt, map_audio_output,
    prepare_audio_cuts, render_audio_cuts, verify_audio_cuts)
from video_harness.common import fingerprint


def _wav(path, samples):
    with wave.open(str(path), 'wb') as stream:
        stream.setnchannels(1)
        stream.setsampwidth(2)
        stream.setframerate(48000)
        stream.writeframes(struct.pack('<'+'h'*len(samples), *samples))


class AudioCutsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.source = root/'source.wav'
        # Four seconds; distinguish each second by constant sample amplitude.
        _wav(self.source, [value for value in (1000, 2000, 3000, 4000) for _ in range(48000)])
        identity = fingerprint(self.source)
        self.cfg = {'assets': [{'asset_id': 'a', 'path': str(self.source), 'sha256': identity['sha256']}],
                    'edit_basis': 'visual'}
        self.mapping = {'version': 4, 'edit_basis': 'visual', 'fps': '10', 'duration': 2.0,
                        'sequence': [
                            {'id': 'first', 'asset_id': 'a', 'source_path': str(self.source),
                             'source_sha256': identity['sha256'], 'source_fps': '10',
                             'source_first_frame': 0, 'source_end_frame_exclusive': 10,
                             'output_first_frame': 0, 'output_end_frame_exclusive': 10},
                            {'id': 'second', 'asset_id': 'a', 'source_path': str(self.source),
                             'source_sha256': identity['sha256'], 'source_fps': '10',
                             'source_first_frame': 20, 'source_end_frame_exclusive': 30,
                             'output_first_frame': 10, 'output_end_frame_exclusive': 20}]}
        self.plan = {'sequence': [{'id': 'first'}, {'id': 'second'}]}
        self.event = {'id': 'j1', 'kind': 'j_cut', 'before_sequence_id': 'second',
                      'duration_frames': 5, 'reason': 'Observed transition rhythm',
                      'handle_observation': 'Local listening: source handle contains steady tone.',
                      'replacement_observation': 'Local listening: outgoing tail contains a different steady tone.',
                      'handle_audio_kind':'nonspoken', 'handle_word_ids': [], 'repeat_word_ids': []}

    def _setting(self):
        return prepare_audio_cuts(self.mapping, self.plan, self.cfg,
                                  {'events': [self.event]}, 'codex', 'Explicit local candidate')

    def test_j_handle_compiles_partition_and_stale_mapping_rejected(self):
        setting = self._setting()
        compiled = verify_audio_cuts(self.mapping, self.plan, self.cfg, setting)
        self.assertEqual(compiled['total_samples'], 96000)
        self.assertEqual(compiled['events'][0]['source_first_sample'], 72000)
        self.assertEqual(compiled['events'][0]['output_first_sample'], 24000)
        self.assertEqual([r['event_id'] for r in compiled['audio_map']], [None, 'j1', None])
        self.assertEqual(map_audio_output(compiled, .6, .7)[0]['source_start'], 1.6)
        self.assertEqual(captions_srt(compiled), '')
        stale = copy.deepcopy(self.mapping)
        stale['note'] = 'changed'
        with self.assertRaisesRegex(ValueError, 'mapping changed'):
            verify_audio_cuts(stale, self.plan, self.cfg, setting)

    def test_l_handle_and_overlap_rejection(self):
        event = {**self.event, 'kind': 'l_cut', 'id': 'l1'}
        compiled = prepare_audio_cuts(self.mapping, self.plan, self.cfg,
                                      {'events': [event]}, 'codex', 'Candidate')['compiled']
        self.assertEqual(compiled['events'][0]['source_first_sample'], 48000)
        self.assertEqual(compiled['events'][0]['output_first_sample'], 48000)
        duplicate = {**self.event, 'id': 'j2'}
        with self.assertRaisesRegex(ValueError, 'overlap'):
            prepare_audio_cuts(self.mapping, self.plan, self.cfg,
                               {'events': [self.event, duplicate]}, 'codex', 'Candidate')

    def test_untranscribed_voice_and_protected_replacement_are_rejected(self):
        event = {**self.event, 'handle_audio_kind': 'speech'}
        with self.assertRaisesRegex(ValueError, 'actual transcript'):
            prepare_audio_cuts(self.mapping, self.plan, self.cfg,
                              {'events':[event]}, 'automation', 'Synthetic declaration')
        protected = {**self.plan, 'protected_ranges':[{'start':.6,'end':.7}]}
        with self.assertRaisesRegex(ValueError, 'explicitly protected'):
            prepare_audio_cuts(self.mapping, protected, self.cfg,
                              {'events':[self.event]}, 'automation', 'Synthetic protection')
        invalid = {**self.event, 'handle_word_ids':[True]}
        with self.assertRaisesRegex(ValueError, 'Invalid word ID'):
            prepare_audio_cuts(self.mapping, self.plan, self.cfg,
                              {'events':[invalid]}, 'automation', 'Synthetic invalid ID')

    def test_pcm_replaces_only_handle_and_preserves_other_samples(self):
        compiled = self._setting()['compiled']
        root = Path(self.tmp.name)
        baseline, output = root/'base.wav', root/'out.wav'
        _wav(baseline, [111]*48000+[333]*48000)
        evidence = render_audio_cuts(baseline, compiled, output)
        self.assertEqual(evidence['total_samples'], 96000)
        with wave.open(str(output), 'rb') as stream:
            values = struct.unpack('<'+'h'*stream.getnframes(), stream.readframes(stream.getnframes()))
        self.assertEqual(values[23999], 111)
        self.assertEqual(values[24000], 2000)
        self.assertEqual(values[47999], 2000)
        self.assertEqual(values[48000], 333)

    def test_source_hash_and_visual_word_claim_rejected(self):
        altered = copy.deepcopy(self.mapping)
        altered['sequence'][1]['source_sha256'] = '0'*64
        with self.assertRaisesRegex(ValueError, 'source mapping changed'):
            prepare_audio_cuts(altered, self.plan, self.cfg, {'events': [self.event]},
                               'codex', 'Candidate')
        claimed = {**self.event, 'handle_word_ids': ['not-observed']}
        with self.assertRaisesRegex(ValueError, 'word IDs'):
            prepare_audio_cuts(self.mapping, self.plan, self.cfg, {'events': [claimed]},
                               'codex', 'Candidate')

    def test_speech_word_protection_and_complete_handle_words(self):
        identity = fingerprint(self.source)
        cfg = {'source': str(self.source)}
        mapping = {'source': identity, 'duration': 2.0, 'keep': [[0.0, 1.0], [2.0, 3.0]],
                   'sequence_ids': ['first', 'second'],
                   'sequence': [{'id': 'first', 'source_start': 0.0, 'source_end': 1.0,
                                 'output_start': 0.0, 'output_end': 1.0},
                                {'id': 'second', 'source_start': 2.0, 'source_end': 3.0,
                                 'output_start': 1.0, 'output_end': 2.0}],
                   'xml': {'frame_duration': '1/10s'}}
        plan = {'version': 3, 'source': identity, 'sequence': [{'id': 'first'}, {'id': 'second'}],
                'transcript': {'words': [
                    {'id': 'w1', 'text': 'first', 'start': .6, 'end': .8},
                    {'id': 'w2', 'text': 'handle', 'start': 1.6, 'end': 1.8},
                    {'id': 'w3', 'text': 'second', 'start': 2.2, 'end': 2.4}]}}
        event = {**self.event, 'handle_audio_kind':'speech', 'handle_word_ids': ['w2']}
        truncated = {**mapping, 'keep':mapping['keep'][:1]}
        with self.assertRaisesRegex(ValueError, 'mapping lengths differ'):
            prepare_audio_cuts(truncated, plan, cfg, {'events':[event]}, 'automation', 'Truncated guard')
        with self.assertRaisesRegex(ValueError, 'remove a known audible word'):
            prepare_audio_cuts(mapping, plan, cfg, {'events': [event]}, 'codex', 'Candidate')
        plan['transcript']['words'][0]['end'] = .4
        plan['transcript']['words'][0]['start'] = .2
        compiled = prepare_audio_cuts(mapping, plan, cfg, {'events': [event]}, 'codex', 'Candidate')['compiled']
        self.assertEqual([w['id'] for w in compiled['word_occurrences']], ['w1', 'w2', 'w3'])
        self.assertIn('handle', captions_srt(compiled))
        plan['transcript']['words'][1]['id'] = 42
        event['handle_word_ids'] = [42]
        integer = prepare_audio_cuts(mapping, plan, cfg, {'events':[event]},
                                    'automation', 'Legacy integer ID')['compiled']
        self.assertIn(42, integer['audible_word_ids'])
        partial = {**event, 'duration_frames':3}
        with self.assertRaisesRegex(ValueError, 'partial word'):
            prepare_audio_cuts(mapping, plan, cfg, {'events':[partial]}, 'automation', 'Partial guard')


if __name__ == '__main__':
    unittest.main()
