import tempfile
import unittest
from pathlib import Path

from video_harness.color import build_lut


ROWS = '\n'.join(f'{r} {g} {b}' for b in (0, 1) for g in (0, 1) for r in (0, 1))


class CustomCubeTests(unittest.TestCase):
 def setUp(self):
  self.temp = tempfile.TemporaryDirectory()
  self.addCleanup(self.temp.cleanup)
  self.root = Path(self.temp.name)
  self.cube = self.root / 'base.cube'
  self.output = self.root / 'render' / 'graded.cube'

 def build(self, headers='', rows=ROWS):
  self.cube.write_text(f'TITLE "test"\nLUT_3D_SIZE 2\n{headers}\n{rows}\n')
  return build_lut({'input_color': 'apple_log', 'apple_log_cube': str(self.cube)}, 'clean_natural', self.output)

 def test_nonunit_domain_rejected_before_output_creation(self):
  for headers in ('DOMAIN_MIN -0.1 0 0\nDOMAIN_MAX 1 1 1',
                  'DOMAIN_MIN 0 0 0\nDOMAIN_MAX 2 1 1'):
   with self.subTest(headers=headers):
    with self.assertRaisesRegex(ValueError, 'input domain'):
     self.build(headers)
    self.assertFalse(self.output.exists())
    self.assertFalse(self.output.with_suffix('.json').exists())

 def test_unit_domain_explicit_or_omitted_is_accepted(self):
  for headers in ('', 'DOMAIN_MIN 0 0 0\nDOMAIN_MAX 1 1 1'):
   with self.subTest(headers=headers):
    self.assertEqual(self.build(headers), self.output)
    self.assertIn('LUT_3D_SIZE 2', self.output.read_text())
    self.output.unlink()
    self.output.with_suffix('.json').unlink()

 def test_nonfinite_or_malformed_rows_rejected(self):
  for rows in (ROWS.replace('0 0 0', 'nan 0 0', 1), ROWS.replace('0 0 0', '0 0', 1)):
   with self.subTest(rows=rows):
    with self.assertRaisesRegex(ValueError, 'Invalid cube rows'):
     self.build(rows=rows)
    self.assertFalse(self.output.exists())

 def test_combined_1d_or_input_range_directives_rejected(self):
  for directive in ('LUT_1D_SIZE 2', 'LUT_3D_INPUT_RANGE 0 1'):
   with self.subTest(directive=directive):
    with self.assertRaisesRegex(ValueError, 'Unsupported cube directive'):
     self.build(directive)
    self.assertFalse(self.output.exists())


if __name__ == '__main__':
 unittest.main()
