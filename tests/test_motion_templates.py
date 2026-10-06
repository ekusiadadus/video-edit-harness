"""Pure recipe compilation to existing, reviewable effect operations."""

from copy import deepcopy
from fractions import Fraction
from pathlib import Path
from unittest import TestCase

from video_harness.doctor import FONT_PATHS
from video_harness.motion_templates import catalog, compile_template
from video_harness.video_effects import revise_effects


MAPPING = {'version': 4, 'edit_basis': 'visual', 'fps': '30', 'duration': 2,
           'frame_count': 60, 'sequence': []}


def request(template='beat_focus', **changes):
    row = {'version': 1, 'id': 'intro', 'template': template,
           'output_start': '1/5', 'output_end': '4/5', 'strength': .6,
           'reason': 'Manual emphasis', 'reduced_motion': False, 'parameters': {}}
    row.update(changes)
    return row


class MotionTemplateTests(TestCase):
    def test_beat_focus_normal_reduced_and_no_mutation(self):
        original = request(parameters={'anchor_x': .4, 'max_scale': 1.09,
                                       'minimum_saturation': .7})
        before = deepcopy(original)
        operations = compile_template(original, MAPPING)
        self.assertEqual(original, before)
        self.assertEqual([op['event']['id'] for op in operations],
                         ['intro-zoom', 'intro-saturation'])
        self.assertEqual([op['event']['type'] for op in operations],
                         ['smooth_zoom', 'saturation_pulse'])
        self.assertTrue(all(op['action'] == 'add' and op['event']['effect_version'] == 1
                            for op in operations))
        self.assertEqual(operations[0]['event']['parameters']['max_scale'], 1.09)
        self.assertEqual(operations[1]['event']['parameters']['minimum_saturation'], .7)
        self.assertEqual(revise_effects(None, MAPPING, operations)['events'][0]['id'],
                         'intro-saturation')  # canonical order is time/type/id
        reduced = compile_template({**original, 'reduced_motion': True}, MAPPING)
        self.assertEqual([op['event']['id'] for op in reduced], ['intro-saturation'])
        self.assertEqual(reduced[0]['event']['parameters']['minimum_saturation'], .95)
        self.assertEqual(catalog()['templates']['beat_focus']['reduced_motion'],
                         ['saturation_pulse'])

    def test_reveal_window_and_reduced_motion(self):
        font = next((path for path in FONT_PATHS if Path(path).is_file()), None)
        if font is None:
            self.skipTest('No installed font available for keyword_title validation')
        specified = request('reveal_callout', parameters={'text': 'Reveal', 'font_path': font},
                            output_start='1/5', output_end='3/5')
        operations = compile_template(specified, MAPPING)
        self.assertEqual([op['event']['type'] for op in operations],
                         ['smooth_zoom', 'keyword_title'])
        self.assertEqual([op['event']['id'] for op in operations], ['intro-zoom', 'intro-title'])
        self.assertEqual(operations[0]['event']['output_end'], str(Fraction(2, 5)))
        self.assertEqual(operations[1]['event']['output_start'], str(Fraction(2, 5)))
        self.assertEqual(operations[1]['event']['parameters']['motion'], 'fade')
        reduced = compile_template({**specified, 'reduced_motion': True}, MAPPING)
        self.assertEqual([op['event']['type'] for op in reduced], ['keyword_title'])
        self.assertEqual(reduced[0]['event']['output_start'], specified['output_start'])

    def test_strict_schema_bounds_and_existing_parameter_validation(self):
        cases = [
            ({**request(), 'version': True}, 'version'),
            ({**request(), 'id': '  '}, 'namespace'),
            ({**request(), 'strength': True}, 'strength'),
            ({**request(), 'strength': float('nan')}, 'strength'),
            ({**request(), 'reduced_motion': 1}, 'reduced_motion'),
            ({**request(), 'output_start': True}, 'output_start'),
            ({**request(), 'output_start': '1/7'}, 'align'),
            ({**request(), 'output_end': '61/30'}, 'existing'),
            ({**request(), 'output_end': '7/30'}, 'at least 3'),
            ({**request(), 'parameters': {'anchor_x': True}}, 'anchor_x'),
            ({**request(), 'parameters': {'minimum_saturation': float('inf')},
              'reduced_motion': True}, 'minimum_saturation'),
            ({**request(), 'parameters': {'expression': 'x'}}, 'supported'),
            ({**request(), 'unexpected': 1}, 'version-1 fields'),
            (request('reveal_callout', output_end='11/30'), 'at least 6'),
        ]
        for case, error in cases:
            with self.subTest(case=case), self.assertRaisesRegex(ValueError, error):
                compile_template(case, MAPPING)
        with self.assertRaisesRegex(ValueError, 'frame_count'):
            compile_template(request(), {**MAPPING, 'frame_count': 59})

    def test_derived_id_collision_is_rejected_by_revise_effects(self):
        operations = compile_template(request(), MAPPING)
        existing = revise_effects(None, MAPPING, [operations[0]])
        with self.assertRaisesRegex(ValueError, 'Duplicate effect id'):
            revise_effects(existing, MAPPING, operations)
