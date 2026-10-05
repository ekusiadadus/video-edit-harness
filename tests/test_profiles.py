import unittest,numpy as np
from copy import deepcopy
from video_harness.profiles import catalog,resolve
from video_harness.color import apply_style
from video_harness.evaluate import frame_metrics,validate_regions
from video_harness.regions import region_filter
class ProfileTests(unittest.TestCase):
 def test_every_composition_finite(self):
  x=np.random.default_rng(2).uniform(0,1,(500,3))
  for case in catalog('use_cases'):
   for style in catalog('styles'):
    r=resolve({},case,style);y=apply_style(x,r);self.assertTrue(np.isfinite(y).all());self.assertEqual(y.shape,x.shape)
 def test_intensity_zero_and_natural_identity(self):
  x=np.random.default_rng(3).uniform(0,1,(100,3))
  np.testing.assert_allclose(x,apply_style(x,resolve({},'indoor_talk','natural')),atol=1e-12)
  np.testing.assert_allclose(x,apply_style(x,resolve({},'indoor_talk','cinematic_teal',0)),atol=1e-12)
 def test_brightness_contrast_are_active(self):
  x=np.array([[.2]*3,[.4]*3,[.7]*3]);bright=apply_style(x,resolve({},overrides={'exposure_stops':.5}));self.assertTrue((bright>x).all())
  contrast=apply_style(x,resolve({},overrides={'contrast':1.2}));self.assertLess(contrast[0,0],x[0,0]);self.assertGreater(contrast[2,0],x[2,0])
 def test_monochrome_blend(self):
  x=np.array([[.7,.3,.1]]);y=apply_style(x,resolve({},style='monochrome',intensity=1));np.testing.assert_allclose(y[0],np.repeat(y[0,0],3),atol=1e-12)
  half=apply_style(x,resolve({},style='monochrome',intensity=.5));self.assertGreater(np.ptp(half),0)
 def test_invalid_settings(self):
  for values in [{'intensity':1.2},{'intensity':float('nan')},{'overrides':{'exposure_stops':float('inf')}},{'overrides':{'typo':1}},{'use_case':'../tones/clean_natural'}]:
   with self.assertRaises(ValueError):resolve({},**values)
 def test_regions_measured_and_validated(self):
  a=np.zeros((10,10,3),dtype=np.uint8);a[:,:5]=204;a[:,5:]=51
  m=frame_metrics(a,{'subject':[0,0,.5,1],'background':[.5,0,.5,1]});self.assertAlmostEqual(m['background_minus_subject_pct'],-60)
  with self.assertRaises(ValueError):validate_regions({'subject':[.8,0,.5,1]})
  self.assertIn('geq',region_filter({'region_corrections':[{'name':'subject','rect':[0,0,.5,1],'luma_delta_pct':6}]}))
