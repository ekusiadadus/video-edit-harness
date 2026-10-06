"""Session production import custody using sealed synthetic render artifacts."""

import unittest
from pathlib import Path
from unittest.mock import patch

from tests.test_session import SessionFixture
from video_harness.common import fingerprint, read, write
from video_harness.render_cache import digest
from video_harness.workflow_cli import parser


class SessionProductionImportTests(unittest.TestCase):
    def setUp(self):
        self.fx = SessionFixture()
        self.addCleanup(self.fx.close)
        self.session = self.fx.session
        self.fx.selected()

    @staticmethod
    def fake_render(cfg, plan, out, preview):
        out.mkdir()
        payloads = {'video.mp4': b'synthetic encoded video', 'audio-only.mp3': b'synthetic audio',
                    'timeline.fcpxml': b'<fcpxml version="1.10"/>',
                    'production-timeline.fcpxml': b'<fcpxml version="1.10"/>',
                    'subtitles.srt': b'', 'look.cube': b'LUT_3D_SIZE 2\n'}
        for name, value in payloads.items():
            (out / name).write_bytes(value)
        write(out / 'plan.json', plan)
        mapping = {'duration': 2, 'sequence': []}
        write(out / 'frame-mapping.json', mapping)
        write(out / 'production.json', {'version': 1, 'assets': [], 'cues': [],
                                        'mapping_sha256': digest(mapping)})
        write(out / 'fcp-production.json', {'mode': 'editable',
              'xml': str(out / 'production-timeline.fcpxml')})
        write(out / 'result.json', {'technical_status': 'pass',
              'artifacts': {name: fingerprint(out / name)['sha256']
                            for name in (*payloads, 'plan.json', 'frame-mapping.json',
                                         'production.json', 'fcp-production.json')}})

    def render(self, preview=False):
        with patch('video_harness.editing.render_edit', side_effect=self.fake_render), \
             patch('video_harness.production.verify_production', side_effect=lambda value: value):
            return self.session.render(preview=preview, actor='codex')

    def test_import_proposal_is_sealed_and_requires_explicit_adoption(self):
        render = self.render()
        returned = self.fx.root / 'returned.fcpxml'
        returned.write_text('<fcpxml version="1.10"/>')
        state_before = self.session._load()
        cue_plan = {'version': 1, 'mapping_sha256':
                    read(render['files']['production']['path'])['mapping_sha256'],
                    'cues': [{'id': 'music', 'asset_id': 'fixture', 'role': 'music',
                              'output_start': 0, 'output_end': 1,
                              'source_start': 0, 'source_end': 1}]}
        with patch('video_harness.production.verify_production', side_effect=lambda value: value), \
             patch('video_harness.production_import.import_production_xml',
                   return_value={'status': 'review_required', 'cue_plan': cue_plan,
                                 'changes': [{'cue_id': 'music'}], 'reasons': []}):
            item = self.session.import_production_fcp(render['id'], returned,
                                                       'codex', 'Compare returned music placement')
        self.assertEqual(item['status'], 'review_required')
        self.assertEqual(len(item['next_steps']), 4)
        changes = read(item['candidate_changes']['path'])
        self.assertEqual(changes, {'cue_plan': cue_plan})
        state_after = self.session._load()
        self.assertEqual(state_before['project'], state_after['project'])
        self.assertEqual(state_before['plan'], state_after['plan'])
        self.assertEqual(state_before['reviews'], state_after['reviews'])
        self.assertEqual(state_before['phase'], state_after['phase'])
        self.assertEqual(state_after['production_imports'][-1]['report'], item['report'])
        report = read(item['report']['path'])
        self.assertEqual(report['render_sha256'], render['files']['video']['sha256'])
        self.assertFalse(report['adopted'])
        self.assertEqual(fingerprint(item['xml']['path'])['sha256'], fingerprint(returned)['sha256'])

    def test_rejection_keeps_xml_and_report(self):
        render = self.render()
        returned = self.fx.root / 'unsupported.fcpxml'
        returned.write_text('<fcpxml version="1.10"><filter-audio/></fcpxml>')
        with patch('video_harness.production.verify_production', side_effect=lambda value: value), \
             patch('video_harness.production_import.import_production_xml',
                   return_value={'status': 'rejected', 'cue_plan': None,
                                 'changes': [], 'reasons': ['unsupported effect']}):
            item = self.session.import_production_fcp(render['id'], returned,
                                                       'codex', 'Inspect unsupported effect')
        self.assertEqual(item['status'], 'rejected')
        self.assertIsNone(item['candidate_changes'])
        self.assertTrue(Path(item['xml']['path']).is_file())
        self.assertIn('unsupported effect', read(item['report']['path'])['reasons'])

    def test_preview_rejected_and_cli_route_present(self):
        render = self.render(preview=True)
        returned = self.fx.root / 'returned.fcpxml'
        returned.write_text('<fcpxml version="1.10"/>')
        with patch('video_harness.production.verify_production', side_effect=lambda value: value):
            with self.assertRaisesRegex(ValueError, 'full render'):
                self.session.import_production_fcp(render['id'], returned, 'codex', 'Check preview')
        args = parser().parse_args(['import-production-fcp', str(self.session.root),
                                    'render-1', str(returned), '--actor', 'codex',
                                    '--note', 'Inspect returned edit'])
        self.assertEqual(args.action, 'import-production-fcp')
        self.assertEqual(args.render_id, 'render-1')


if __name__ == '__main__':
    unittest.main()
