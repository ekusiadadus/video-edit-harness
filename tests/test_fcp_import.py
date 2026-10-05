import tempfile
import unittest
from pathlib import Path
from xml.etree import ElementTree as ET

from video_harness.common import fingerprint
from video_harness.editorial import build_story_plan, make_brief
from video_harness.fcp import export_timeline
from video_harness.fcp_import import import_fcpxml


class FCPImportTests(unittest.TestCase):
    def test_ordered_export_and_flat_import(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / 'source.mov'
            source.write_bytes(b'source')
            cfg = {'source': str(source), 'editorial': {'goal': 'Tell story'}}
            words = [{'id': i, 'start': s, 'end': e, 'text': str(i), 'probability': .9}
                     for i, s, e in [(1,.5,.8),(2,1.5,1.8),(3,2.5,2.8)]]
            transcript = {'version': 1, 'source': fingerprint(source), 'duration': 4.,
                          'words': words, 'segments': []}
            brief = make_brief(cfg)
            spec = {'chapters': [{'id': 'story', 'title': 'Story', 'goal_ids': ['goal-1'],
                    'spans': [{'id': 'later', 'start_word_id': 3, 'end_word_id': 3, 'reason': 'Lead'},
                              {'id': 'earlier', 'start_word_id': 1, 'end_word_id': 1, 'reason': 'Setup'}]}],
                    'omissions': [{'word_ids': [2], 'reason': 'Aside', 'goal_ids': ['goal-1']}]}
            plan = build_story_plan(cfg, transcript, brief, spec)
            info = {'streams': [{'codec_type': 'video', 'r_frame_rate': '30/1',
                    'avg_frame_rate': '30/1', 'width': 320, 'height': 180, 'duration': '4'}],
                    'format': {'duration': '4'}}
            xml = root / 'edit.fcpxml'
            with self.assertRaisesRegex(ValueError, 'unordered'):
                export_timeline(source, info, [(2, 3), (0, 1)], xml, 'Edit')
            export_timeline(source, info, [(2, 3), (0, 1)], xml, 'Edit', ordered=True)
            plan['sequence'][0].update(start=2., end=3.)
            plan['sequence'][1].update(start=0., end=1.)
            imported, report = import_fcpxml(plan, xml, 'agent:codex', 'FCP edit roundtrip')
            self.assertEqual(report['status'], 'imported')
            self.assertEqual([s['start'] for s in imported['sequence']], [2., 0.])
            self.assertEqual(imported['status'], 'review_required')
            self.assertEqual(imported['fcp_import']['imported_by'], 'agent:codex')
            tree = ET.parse(xml)
            tree.find('.//asset-clip').append(ET.Element('timeMap'))
            tree.write(xml)
            imported, report = import_fcpxml(plan, xml, 'agent:codex', 'Try retime')
            self.assertIsNone(imported)
            self.assertIn('Retime', report['reasons'][0])


if __name__ == '__main__':
    unittest.main()
