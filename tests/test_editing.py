import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from video_harness.common import write, read
from video_harness.editing import revise_plan, audition, export_edit
from video_harness.edl import build_plan
from video_harness.common import fingerprint


class EditingTests(unittest.TestCase):
    def fixture(self, root):
        source = root / 'source.mov'
        source.write_bytes(b'source')
        cfg = {'source': str(source), 'editorial': {}}
        transcript = {'version': 1, 'source': fingerprint(source), 'duration': 4,
                      'words': [{'id': 'w1', 'start': 0, 'end': 1, 'text': '前', 'probability': .9},
                                {'id': 'w2', 'start': 3, 'end': 4, 'text': '後', 'probability': .9}],
                      'segments': []}
        return cfg, build_plan(cfg, transcript, [(1, 3)])

    def test_revision_is_explicit_and_preserves_original(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _, plan = self.fixture(root)
            original, revised = root / 'plan.json', root / 'reviewed.json'
            write(original, plan)
            revise_plan(original, revised, enable=[1], note='前後を聞いて確認')
            self.assertFalse(read(original)['cuts'][0]['enabled'])
            self.assertTrue(read(revised)['cuts'][0]['enabled'])
            self.assertEqual(read(revised)['parent_plan'], fingerprint(original))
            with self.assertRaisesRegex(ValueError, 'Unknown'):
                revise_plan(original, root / 'bad.json', enable=[99], note='check')

    def test_export_recovers_only_small_container_tail(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            cfg,plan=self.fixture(root)
            cfg['name']='test'
            info={'streams':[{'codec_type':'video','duration':'3.99','avg_frame_rate':'30/1'}], 'format':{'duration':'4'}}
            with patch('video_harness.editing.probe',return_value=info), patch('video_harness.editing.export_timeline',side_effect=RuntimeError('stop after mapping')) as export:
                with self.assertRaisesRegex(RuntimeError,'stop after mapping'):export_edit(cfg,plan,root)
                self.assertEqual(export.call_args.args[2][-1][1],3.99)
            info['streams'][0]['duration']='3.8'
            with patch('video_harness.editing.probe',return_value=info):
                with self.assertRaisesRegex(ValueError,'beyond source video'):export_edit(cfg,plan,root)

    def test_auditions_do_not_enable_candidate(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cfg, plan = self.fixture(root)
            with patch('video_harness.editing.run') as call:
                items = audition(cfg, plan, root / 'junctions')
                self.assertEqual(call.call_count, 4)
            self.assertFalse(plan['cuts'][0]['enabled'])
            self.assertFalse(items[0]['enabled'])
            self.assertEqual(read(root / 'junctions/junctions.json')['total_candidates'], 1)


if __name__ == '__main__':
    unittest.main()
