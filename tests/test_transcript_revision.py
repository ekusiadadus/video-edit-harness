import tempfile
import unittest
from pathlib import Path

from video_harness.common import fingerprint
from video_harness.edl import build_plan, remap_subtitles
from video_harness.transcript import load_transcript, save_transcript
from video_harness.transcript_revision import revise_transcript


class TranscriptRevisionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.source = self.root / 'source.mov'
        self.source.write_bytes(b'source')
        data = {'version': 1, 'source': fingerprint(self.source), 'duration': 2.,
                'language': 'ja', 'backend': {'name': 'openai', 'sdk_version': 'test', 'settings': {}},
                'words': [{'id': 'w1', 'start': .1, 'end': .5, 'text': '旧名', 'probability': .9},
                          {'id': 'w2', 'start': .6, 'end': 1., 'text': 'です。', 'probability': .8}],
                'segments': [{'id': 's1', 'start': .1, 'end': 1., 'text': '旧名です。'}],
                'semantic_text': '旧名です。', 'warnings': []}
        self.input = save_transcript(self.root / 'original', data)

    def test_correction_flows_to_plan_and_subtitle_without_changing_anchors(self):
        original = load_transcript(self.input)
        corrected_path = revise_transcript(self.input, self.root / 'corrected',
                                           [{'word_id': 'w1', 'text': '新名'}],
                                           'human:owner', 'Correct name')
        corrected = load_transcript(corrected_path)
        self.assertEqual(corrected['words'][0]['text'], '新名')
        self.assertEqual(corrected['words'][0]['start'], original['words'][0]['start'])
        self.assertEqual(corrected['segments'][0]['text'], '新名です。')
        self.assertEqual(corrected['semantic_text'], '新名です。')
        self.assertEqual(corrected['revision_history'][-1]['parent_result_sha256'], original['result_sha256'])
        plan = build_plan({'source': str(self.source)}, corrected)
        self.assertEqual(remap_subtitles(plan)[0]['text'], '新名')
        self.assertEqual(load_transcript(self.input)['words'][0]['text'], '旧名')

    def test_parent_tamper_and_ambiguous_correction_rejected(self):
        self.input.with_name('transcript.txt').write_text('tampered')
        with self.assertRaises(ValueError):
            revise_transcript(self.input, self.root / 'bad', [{'word_id': 'w1', 'text': '新名'}], 'human', 'note')
        self.assertFalse((self.root / 'bad' / 'transcript.json').exists())
        self.input.with_name('transcript.txt').write_text('')

    def test_duplicate_or_unknown_ids_rejected(self):
        with self.assertRaises(ValueError):
            revise_transcript(self.input, self.root / 'bad', [{'word_id': 'missing', 'text': '新名'}], 'human', 'note')
        with self.assertRaises(ValueError):
            revise_transcript(self.input, self.root / 'bad', [{'word_id': 'w1', 'text': '新名'},
                                                              {'word_id': 'w1', 'text': '別名'}], 'human', 'note')


if __name__ == '__main__':
    unittest.main()
