"""Structure comparisons disclose source choices without implying approval."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

from video_harness.common import read, write
from video_harness.comparison import comparison_evidence, comparison_page
from video_harness.render_cache import digest
from video_harness.retime_mapping import remap_visual_mapping
from video_harness.time_mapping import compile_retime


def visual_mapping(ranges, *, fps='10'):
    sequence = []
    output = 0
    for identity, asset, first, end in ranges:
        length = end - first
        sequence.append({'id': identity, 'asset_id': asset,
                         'source_path': f'/private/{asset}.mp4',
                         'source_sha256': 'sourcehash' if asset == 'asset' else 'secondhash',
                         'source_fps': fps, 'output_fps': fps,
                         'source_first_frame': first, 'source_end_frame_exclusive': end,
                         'output_first_frame': output, 'output_end_frame_exclusive': output + length})
        output += length
    return {'version': 4, 'edit_basis': 'visual', 'fps': fps,
            'duration': output / int(fps), 'frame_count': output,
            'has_source_audio': True, 'audio': 'source audio', 'sequence': sequence}


class StructureComparisonTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = {'sha256': 'sourcehash'}
        self.ranges = [('a', 'asset', 0, 4), ('b', 'asset', 6, 10)]
        self.baseline = self.render('baseline', visual_mapping(self.ranges), natural=True)

    def render(self, name, mapping, *, natural=False, assets=None, **overrides):
        folder = self.root / name
        folder.mkdir()
        config = {'assets': assets if assets is not None else
                  [{'asset_id': 'asset', 'sha256': 'sourcehash'}],
                  'audio': {'normalize': False}, 'input_color': 'rec709',
                  'style': 'natural', 'editing_pattern': {
                      'id': 'natural' if natural else 'playful_short',
                      'music': 'off', 'sfx': 'off', 'visual_assets': 'off', 'beat_sync': 'off'},
                  'visual_pipeline_version': 1}
        config.update(overrides)
        write(folder / 'project.json', config)
        write(folder / 'frame-mapping.json', mapping)
        return {'id': name, 'path': str(folder),
                'project': {'path': str(folder / 'project.json')},
                'plan': {'sha256': name + '-sealed-plan'},
                'files': {'mapping': {'path': str(folder / 'frame-mapping.json')},
                          'video': {'sha256': name + '-video-sha'}}, 'preview': False}

    def test_accepts_reordering_and_preserves_ordered_ranges(self):
        candidate = self.render('reordered', visual_mapping([
            ('new-b', 'asset', 6, 10), ('new-a', 'asset', 0, 4)]))
        result = comparison_evidence([self.baseline, candidate], self.source, mode='structure')
        self.assertEqual((result['version'], result['mode']), (3, 'structure'))
        self.assertEqual(result['candidates'][1]['plan_sha256'], 'reordered-sealed-plan')
        self.assertEqual(result['candidates'][1]['original_mapping_sha256'],
                         digest(visual_mapping([('new-b', 'asset', 6, 10),
                                                ('new-a', 'asset', 0, 4)])))
        spans = result['candidates'][1]['structure']
        self.assertEqual([(s['id'], s['source_first_frame'], s['source_end_frame_exclusive'])
                          for s in spans], [('new-b', 6, 10), ('new-a', 0, 4)])
        self.assertEqual(result['candidates'][1]['source_span_changes']['added'], [])
        self.assertEqual(result['candidates'][1]['source_span_changes']['removed'], [])
        self.assertTrue(result['candidates'][1]['source_span_changes']['same_range_multiplicity'])

    def test_discloses_omitted_shifted_and_duplicate_ranges_as_multiset(self):
        candidate = self.render('changed', visual_mapping([
            ('shift', 'asset', 7, 11), ('repeat-one', 'asset', 0, 4),
            ('repeat-two', 'asset', 0, 4)]))
        rows = comparison_evidence([self.baseline, candidate], self.source,
                                   mode='structure')['candidates']
        changes = rows[1]['source_span_changes']
        self.assertEqual(changes['baseline_render_id'], 'baseline')
        self.assertEqual((len(changes['added']), len(changes['removed'])), (2, 1))
        self.assertEqual([(s['source_first_frame'], s['source_end_frame_exclusive'])
                          for s in changes['added']], [(7, 11), (0, 4)])
        self.assertEqual([(s['source_first_frame'], s['source_end_frame_exclusive'])
                          for s in changes['removed']], [(6, 10)])
        self.assertFalse(changes['same_range_multiplicity'])
        self.assertEqual([s['source_first_frame'] for s in rows[1]['structure']], [7, 0, 0])
        self.assertEqual(rows[1]['source_coverage']['original_selected_frames'], 12)

    def test_rejects_asset_sha_mismatch_and_source_pool_changes(self):
        mismatch = visual_mapping(self.ranges)
        mismatch['sequence'][0]['source_sha256'] = 'tampered'
        candidate = self.render('sha-mismatch', mismatch)
        with self.assertRaisesRegex(ValueError, 'source SHA differs'):
            comparison_evidence([self.baseline, candidate], self.source, mode='structure')

        extra = self.render('extra-source', visual_mapping([
            ('new', 'other', 0, 4)]), assets=[
                {'asset_id': 'asset', 'sha256': 'sourcehash'},
                {'asset_id': 'other', 'sha256': 'secondhash'}])
        with self.assertRaisesRegex(ValueError, 'source asset is missing'):
            comparison_evidence([self.baseline, extra], self.source, mode='structure')

    def test_rejects_changed_color_audio_fps_preview_and_missing_plan(self):
        ordinary = visual_mapping(self.ranges)
        color = self.render('color', ordinary, style='cinematic')
        with self.assertRaisesRegex(ValueError, 'color, base audio'):
            comparison_evidence([self.baseline, color], self.source, mode='structure')
        audio = self.render('audio', ordinary, audio={'normalize': True})
        with self.assertRaisesRegex(ValueError, 'base audio settings'):
            comparison_evidence([self.baseline, audio], self.source, mode='structure')
        fps = self.render('fps', visual_mapping(self.ranges, fps='20'))
        with self.assertRaisesRegex(ValueError, 'source pool, edit basis'):
            comparison_evidence([self.baseline, fps], self.source, mode='structure')
        preview = self.render('preview', ordinary)
        preview['preview'] = True
        with self.assertRaisesRegex(ValueError, 'preview mode'):
            comparison_evidence([self.baseline, preview], self.source, mode='structure')
        missing_plan = self.render('missing-plan', ordinary)
        missing_plan.pop('plan')
        with self.assertRaisesRegex(ValueError, 'sealed render plans'):
            comparison_evidence([self.baseline, missing_plan], self.source, mode='structure')

    def test_retimed_reorder_retains_original_spans_and_verifies_binding(self):
        original = visual_mapping([('b', 'asset', 6, 10), ('a', 'asset', 0, 4)])
        operation = {'id': 'hold', 'kind': 'freeze', 'source_frame': 4,
                     'output_frames': 3, 'reason': 'Observed pause'}
        compiled = compile_retime(8, '10', [operation])
        setting = {'version': 1, 'input_mapping_sha256': digest(original),
                   'proposal': {'request': {'operations': [operation]}, 'mapping': compiled}}
        candidate = self.render('retimed', remap_visual_mapping(original, compiled), retime=setting)
        folder = Path(candidate['path'])
        write(folder / 'pre-retime-mapping.json', original)
        result = comparison_evidence([self.baseline, candidate], self.source, mode='structure')
        row = result['candidates'][1]
        self.assertEqual(row['retime_operations'], [operation])
        self.assertEqual(row['source_coverage']['repeated_output_frames'], 3)
        self.assertEqual([s['source_first_frame'] for s in row['structure']], [6, 0])
        self.assertTrue(row['source_span_changes']['same_range_multiplicity'])

        project_path = folder / 'project.json'
        config = read(project_path)
        original_config = deepcopy(config)
        config['retime']['proposal']['mapping']['frame_map'][0] = 1
        project_path.write_text(json.dumps(config))
        with self.assertRaisesRegex(ValueError, 'compiled mapping|requested operations'):
            comparison_evidence([self.baseline, candidate], self.source, mode='structure')
        project_path.write_text(json.dumps(original_config))
        stale = read(folder / 'pre-retime-mapping.json')
        stale['sequence'][0]['source_first_frame'] = 5
        (folder / 'pre-retime-mapping.json').write_text(json.dumps(stale))
        with self.assertRaisesRegex(ValueError, 'original mapping binding'):
            comparison_evidence([self.baseline, candidate], self.source, mode='structure')

    def test_requires_natural_baseline_and_keeps_default_modes_strict(self):
        changed = self.render('changed-default', visual_mapping([
            ('a', 'asset', 0, 4), ('b', 'asset', 7, 11)]))
        for mode in ('effects', 'timing'):
            with self.subTest(mode=mode), self.assertRaisesRegex(ValueError,
                                                                  'source frames|original source coverage'):
                comparison_evidence([self.baseline, changed], self.source, mode=mode)
        unnatural = self.render('unnatural', visual_mapping(self.ranges))
        with self.assertRaisesRegex(ValueError, 'natural no-addition baseline'):
            comparison_evidence([unnatural, changed], self.source, mode='structure')

    def test_speech_order_uses_keep_ranges_and_checks_source_sha(self):
        def speech(ids, keeps, sha='sourcehash'):
            return {'source': {'sha256': sha}, 'keep': keeps,
                    'duration': 1., 'xml': {'frame_duration': '1/30s'},
                    'sequence_ids': ids, 'sequence': [{'id': i} for i in ids]}
        base = self.render('speech-base', speech(['opening', 'closing'],
                           [[0., .5], [.6, 1.1]]), natural=True)
        reordered = self.render('speech-reordered', speech(['closing', 'opening'],
                                [[.6, 1.1], [0., .5]]))
        result = comparison_evidence([base, reordered], self.source, mode='structure')
        self.assertEqual([span['id'] for span in result['candidates'][1]['structure']],
                         ['closing', 'opening'])
        self.assertTrue(result['candidates'][1]['source_span_changes']['same_range_multiplicity'])
        bad_source = self.render('speech-bad-source', speech(['closing', 'opening'],
                                 [[.6, 1.1], [0., .5]], sha='wrong'))
        with self.assertRaisesRegex(ValueError, 'speech mapping source SHA'):
            comparison_evidence([base, bad_source], self.source, mode='structure')

    def test_speech_accepts_float_residue_but_rejects_fractional_frame(self):
        def speech(duration):
            return {'source': {'sha256': 'sourcehash'},
                    'keep': [[0., .6], [.6, 1.2]], 'duration': duration,
                    'xml': {'frame_duration': '1/30s'},
                    'sequence_ids': ['a', 'b'],
                    'sequence': [{'id': 'a'}, {'id': 'b'}]}
        base = self.render('float-base', speech(1.2), natural=True)
        residue = self.render('float-residue', speech(1.2000000000000002))
        self.assertEqual(comparison_evidence([base, residue], self.source,
                         mode='structure')['candidates'][1]['original_duration_seconds'], 1.2)
        fractional = self.render('fractional', speech(1.21))
        with self.assertRaisesRegex(ValueError, 'frame dimensions differ'):
            comparison_evidence([base, fractional], self.source, mode='structure')

    def test_page_discloses_order_with_safe_text_and_independent_controls(self):
        candidate = self.render('page-candidate', visual_mapping([
            ('b', 'asset', 7, 11), ('a', 'asset', 0, 4), ('repeat', 'asset', 0, 4)]))
        rows = comparison_evidence([self.baseline, candidate], self.source,
                                   mode='structure')['candidates']
        for row, label in zip(rows, ['Base <script>', 'Candidate']):
            row['label'] = label
            row['video'] = '/tmp/clip?<script>.mp4'
            row['sha256'] = row['video_sha256']
        page = comparison_page(rows, mode='structure')
        self.assertEqual(page.count('<video controls'), 2)
        self.assertNotIn('videos.slice(1)', page)
        self.assertIn('videos[choice].currentTime', page)
        self.assertIn('render_sha256:rows[choice].sha256', page)
        self.assertIn('adopted:false,final_review:false', page)
        self.assertIn('0.600–1.000 秒', page)
        self.assertIn('0.000–0.400 秒', page)
        self.assertIn('追加した範囲', page)
        self.assertIn('除去した範囲', page)
        self.assertIn('7–11 フレーム、10 fps、終了を含まない', page)
        self.assertIn('6–10 フレーム、10 fps、終了を含まない', page)
        self.assertIn('追加 2、除去 1', page)
        self.assertIn('&lt;script&gt;', page)
        self.assertNotIn('<h2>Base <script>', page)
        self.assertNotIn('/private/asset.mp4', page)


if __name__ == '__main__':
    unittest.main()
