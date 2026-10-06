"""Exact source-cut and independent-playback checks for timing comparisons."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

from video_harness.common import write
from video_harness.comparison import comparison_evidence, comparison_page
from video_harness.retime_mapping import remap_visual_mapping
from video_harness.speech_retime import remap_speech_mapping
from video_harness.render_cache import digest
from video_harness.time_mapping import compile_retime


def visual_mapping():
    return {'version': 4, 'edit_basis': 'visual', 'fps': '10', 'duration': .8,
            'frame_count': 8, 'has_source_audio': True, 'audio': 'source audio',
            'sequence': [
                {'id': 'first', 'asset_id': 'asset', 'source_path': '/source.mp4',
                 'source_sha256': 'sourcehash', 'source_fps': '10', 'output_fps': '10',
                 'source_first_frame': 0, 'source_end_frame_exclusive': 4,
                 'output_first_frame': 0, 'output_end_frame_exclusive': 4},
                {'id': 'second', 'asset_id': 'asset', 'source_path': '/source.mp4',
                 'source_sha256': 'sourcehash', 'source_fps': '10', 'output_fps': '10',
                 'source_first_frame': 6, 'source_end_frame_exclusive': 10,
                 'output_first_frame': 4, 'output_end_frame_exclusive': 8}]}


class TimingComparisonTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = {'sha256': 'sourcehash'}
        self.original = visual_mapping()
        self.operation = {'id': 'hold', 'kind': 'freeze', 'source_frame': 4,
                          'output_frames': 3, 'reason': 'Pause on the second cut'}
        self.baseline = self.render('natural', self.original)
        self.timed = self.retimed(self.operation)

    def render(self, name, mapping, *, retime=None, original=None):
        folder = self.root / name
        folder.mkdir()
        config = {'assets': [{'asset_id': 'asset', 'sha256': 'sourcehash'}],
                  'audio': {'normalize': False}, 'input_color': 'rec709',
                  'style': 'natural', 'editing_pattern': {'id': 'natural' if name == 'natural' else 'playful_short',
                    'music': 'off', 'sfx': 'off', 'visual_assets': 'off', 'beat_sync': 'off'},
                  'visual_pipeline_version': 1}
        if retime is not None:
            config['retime'] = retime
        write(folder / 'project.json', config)
        write(folder / 'frame-mapping.json', mapping)
        if original is not None:
            write(folder / 'pre-retime-mapping.json', original)
        return {'id': name, 'path': str(folder), 'project': {'path': str(folder / 'project.json')},
                'files': {'mapping': {'path': str(folder / 'frame-mapping.json')},
                          'video': {'sha256': name + 'hash'}}, 'preview': False}

    def retimed(self, operation, *, original=None, name='timed'):
        original = original or self.original
        compiled = compile_retime(8, '10', [operation])
        setting = {'version': 1, 'input_mapping_sha256': digest(original),
                   'proposal': {'request': {'operations': [operation]}, 'mapping': compiled}}
        mapping = remap_visual_mapping(original, compiled)
        return self.render(name, mapping, retime=setting, original=original)

    def test_accepts_same_original_cut_coverage_and_reports_timing(self):
        result = comparison_evidence([self.baseline, self.timed], self.source, mode='timing')
        self.assertEqual((result['version'], result['mode']), (2, 'timing'))
        self.assertEqual(result['conditions']['original_mapping_sha256'], digest(self.original))
        self.assertEqual(result['candidates'][1]['retime_operations'], [self.operation])
        self.assertEqual(result['candidates'][1]['duration_seconds'], 1.1)
        self.assertEqual(result['candidates'][1]['source_coverage']['repeated_output_frames'], 3)
        self.assertIn('Equal output timestamps do not', result['timeline_explanation'])

    def test_rejects_changed_cut_coverage_even_with_same_source_hash(self):
        changed = deepcopy(self.original)
        changed['sequence'][1]['source_first_frame'] = 5
        changed['sequence'][1]['source_end_frame_exclusive'] = 9
        alternative = self.retimed(self.operation, original=changed, name='alternative')
        with self.assertRaisesRegex(ValueError, 'original source coverage'):
            comparison_evidence([self.baseline, alternative], self.source, mode='timing')

    def test_rejects_tampered_compiled_and_output_mapping(self):
        folder = Path(self.timed['path'])
        config_path = folder / 'project.json'
        from video_harness.common import read
        config = read(config_path)
        config['retime']['proposal']['mapping']['frame_map'][0] = 1
        config_path.write_text(json.dumps(config))
        with self.assertRaisesRegex(ValueError, 'compiled mapping|requested operations'):
            comparison_evidence([self.baseline, self.timed], self.source, mode='timing')
        config['retime']['proposal']['mapping']['frame_map'][0] = 0
        config_path.write_text(json.dumps(config))
        mapping_path = folder / 'frame-mapping.json'
        mapping = read(mapping_path)
        mapping['retime']['frames'][0]['source_frame'] = 7
        mapping_path.write_text(json.dumps(mapping))
        with self.assertRaisesRegex(ValueError, 'output mapping'):
            comparison_evidence([self.baseline, self.timed], self.source, mode='timing')

    def test_rejects_style_and_preview_changes(self):
        from video_harness.common import read
        config_path = Path(self.timed['project']['path'])
        config = read(config_path)
        config['style'] = 'cinematic'
        config_path.write_text(json.dumps(config))
        with self.assertRaisesRegex(ValueError, 'color, base audio'):
            comparison_evidence([self.baseline, self.timed], self.source, mode='timing')
        config['style'] = 'natural'
        config_path.write_text(json.dumps(config))
        self.timed['preview'] = True
        with self.assertRaisesRegex(ValueError, 'preview mode'):
            comparison_evidence([self.baseline, self.timed], self.source, mode='timing')

    def test_allows_and_discloses_added_production_on_timed_candidate(self):
        from video_harness.common import read
        config_path = Path(self.timed['project']['path'])
        config = read(config_path)
        config['editing_pattern']['music'] = 'selected'
        config['cue_plan'] = {'candidate': 'licensed music plan'}
        config_path.write_text(json.dumps(config))
        result = comparison_evidence([self.baseline, self.timed], self.source, mode='timing')
        changes = result['candidates'][1]['production_changes']
        self.assertEqual(changes['cue_plan'], config['cue_plan'])
        self.assertEqual(changes['editing_pattern'], 'playful_short')

    def test_full_length_page_uses_independent_native_controls_and_sha_choice(self):
        rows = [{'label': 'Natural', 'video': 'file:///base.mp4', 'render_id': 'base', 'sha256': 'abc',
                 'duration_seconds': .8},
                {'label': 'Hold', 'video': 'file:///hold.mp4', 'render_id': 'hold', 'sha256': 'def',
                 'duration_seconds': 1.1, 'retime_operations': [self.operation],
                 'source_coverage': {'omitted_original_timeline_frames': 0,
                                     'repeated_output_frames': 3}}]
        page = comparison_page(rows, mode='timing')
        self.assertEqual(page.count('<video controls'), 2)
        self.assertNotIn('Math.min(...videos.map', page)
        self.assertNotIn('videos.slice(1)', page)
        self.assertIn('videos[choice].currentTime', page)
        self.assertIn('render_sha256:rows[choice].sha256', page)
        self.assertIn('表示時刻は案の間で対応しません', page)
        self.assertIn('長さ: 1.1 秒', page)
        self.assertIn('4 フレームを 3 フレーム停止: Pause on the second cut', page)
        self.assertIn('3 フレーム反復', page)

    def test_speech_original_uses_xml_frame_duration_and_keeps(self):
        original = {'source': {'sha256': 'sourcehash'}, 'keep': [[0., .5], [.6, 1.1]],
                    'duration': 1., 'xml': {'frame_duration': '1/30s'},
                    'sequence_ids': ['opening', 'closing'],
                    'sequence': [{'id': 'opening'}, {'id': 'closing'}]}
        operation = {'id': 'pause', 'kind': 'freeze', 'source_frame': 15,
                     'output_frames': 2, 'reason': 'Observed pause'}
        compiled = compile_retime(30, '30', [operation])
        setting = {'version': 2, 'input_mapping_sha256': digest(original),
                   'proposal': {'request': {'operations': [operation]}, 'mapping': compiled}}
        baseline = self.render('speech_natural', original)
        candidate = self.render('speech_timed', remap_speech_mapping(original, compiled),
                                retime=setting, original=original)
        # Speech baseline also uses a natural pattern even though its fixture ID differs.
        from video_harness.common import read
        config_path = Path(baseline['project']['path'])
        config = read(config_path)
        config['editing_pattern']['id'] = 'natural'
        config_path.write_text(json.dumps(config))
        result = comparison_evidence([baseline, candidate], self.source, mode='timing')
        self.assertEqual(result['candidates'][0]['original_duration_seconds'], 1.)
        self.assertAlmostEqual(result['candidates'][1]['duration_seconds'], 32 / 30)


if __name__ == '__main__':
    unittest.main()
