"""Caption identities follow observed cuts, frame retime, and audio samples."""

from copy import deepcopy
from pathlib import Path
import tempfile
import unittest

from video_harness.caption_groups import caption_stream_sha256, group_reviewed_captions
from video_harness.caption_timing import caption_timing, write_caption_evidence, verify_caption_evidence
from video_harness.common import fingerprint, read
from video_harness.edl import build_plan, write_srt


def spec(stream, groups):
    return {'version': 1, 'word_stream_sha256': stream['word_stream_sha256'],
            'language': 'en', 'protected_phrases': [],
            'groups': [{'id': f'caption-{i}', 'word_refs': [
                {'word_id': stream['words'][n].get('id', stream['words'][n].get('word_id')),
                 'occurrence_index': stream['words'][n]['occurrence_index']} for n in indices],
                'reason': 'Observed phrase boundary'} for i, indices in enumerate(groups)],
            'reading': {'minimum_seconds': .5, 'maximum_units_per_second': 4}}


class CaptionTimingTests(unittest.TestCase):
    def test_original_mapping_and_legacy_srt_are_preserved(self):
        with tempfile.TemporaryDirectory() as folder:
            out = Path(folder); source = out/'source.mov'; source.write_bytes(b'fixture')
            transcript = {'version': 1, 'source': fingerprint(source), 'duration': 2.,
                          'segments': [], 'words': [
                              {'id': 'a', 'start': .1, 'end': .3, 'text': 'First', 'probability': 1.},
                              {'id': 'b', 'start': 1.1, 'end': 1.3, 'text': 'Last', 'probability': 1.}]}
            plan = build_plan({'source': str(source)}, transcript)
            mapping = {'keep': [[0., 2.]], 'duration': 2.}
            write_srt(plan, out/'legacy.srt', keep=mapping['keep'])
            report = write_caption_evidence(out, plan, mapping)
            self.assertEqual((out/'legacy.srt').read_bytes(), (out/'subtitles.srt').read_bytes())
            self.assertEqual(report['grouping_method'], 'legacy_automatic_proposal')
            self.assertEqual(report['subtitles_sha256'], fingerprint(out/'subtitles.srt')['sha256'])
            self.assertEqual(read(out/'caption-evidence.json')['word_stream_sha256'], report['word_stream_sha256'])
            verify_caption_evidence(report, report['subtitles_sha256'])
            bad = deepcopy(report); bad['grouping']['captions'][0]['text'] = 'Different words'
            with self.assertRaisesRegex(ValueError, 'subtitles'):
                verify_caption_evidence(bad, report['subtitles_sha256'])
            reviewed_out = out/'reviewed'; reviewed_out.mkdir()
            reviewed = write_caption_evidence(reviewed_out, plan, mapping,
                        grouping=spec(report, [[0, 1]]))
            self.assertIn('First Last', (reviewed_out/'subtitles.srt').read_text())
            self.assertEqual(reviewed['grouping_method'], 'explicit_word_groups')
            previous = (out/'subtitles.srt').read_bytes()
            with self.assertRaises(FileExistsError):
                write_caption_evidence(out, plan, mapping, grouping=spec(report, [[0, 1]]))
            self.assertEqual(previous, (out/'subtitles.srt').read_bytes())

    def test_retimed_frames_retain_integer_and_repeated_ids(self):
        retime = {'proposal': {'mapping': {'fps': '30000/1001', 'frame_map': [0, 0, 1, 2, 3, 4]},
                  'captions': [{'id': 'word:7:0', 'status': 'mapped', 'output_first_frame': 0,
                                'output_end_frame_exclusive': 2, 'text': 'Again'},
                               {'id': 'word:7:1', 'status': 'mapped', 'output_first_frame': 4,
                                'output_end_frame_exclusive': 6, 'text': 'Again'}]},
                  'word_protection': {'word_occurrences': [
                      {'word_id': 7, 'occurrence_index': 0}, {'word_id': 7, 'occurrence_index': 1}]},
                  'edit_junction_frames': [3]}
        stream = caption_timing({}, {}, retime=retime)
        self.assertEqual(stream['words'][1]['occurrence_index'], 1)
        self.assertEqual(stream['words'][1]['id'], 7)
        self.assertAlmostEqual(stream['words'][1]['start'], 4*1001/30000)
        self.assertEqual(stream['junctions'], [4*1001/30000])
        with self.assertRaisesRegex(ValueError, 'junction'):
            group_reviewed_captions(stream['words'], spec(stream, [[0, 1]]), junctions=stream['junctions'])
        changed = deepcopy(stream['words']); changed[0]['start'] += .001
        self.assertEqual(caption_stream_sha256(changed), stream['word_stream_sha256'])
        malformed = deepcopy(retime); malformed['proposal']['captions'][1]['id'] = 'word:7:0'
        with self.assertRaisesRegex(ValueError, 'occurrence'):
            caption_timing({}, {}, retime=malformed)

    def test_audio_handle_uses_actual_audible_word_samples(self):
        compiled = {'word_occurrences': [
            {'id': 'later', 'text': 'Later', 'output_first_sample': 12000, 'output_end_sample': 24000},
            {'id': 'earlier', 'text': 'Earlier', 'output_first_sample': 30000, 'output_end_sample': 36000}],
            'audio_map': [{'source_path': '/source', 'source_end_sample': 24000},
                          {'source_path': '/source', 'source_first_sample': 48000,
                           'output_first_sample': 30000}]}
        stream = caption_timing({}, {}, audio_cuts=compiled)
        self.assertEqual(stream['words'][0]['start'], .25)
        self.assertEqual(stream['junctions'], [.625])
        self.assertEqual(stream['timing_basis'], 'observed_audio_word_samples')
        with self.assertRaisesRegex(ValueError, 'joint mapping'):
            caption_timing({}, {}, retime={}, audio_cuts=compiled)


if __name__ == '__main__':
    unittest.main()
