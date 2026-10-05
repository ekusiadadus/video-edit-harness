import unittest
from video_harness.cli import parser,candidate_profiles
class CLIProfiles(unittest.TestCase):
 def test_preview_keeps_configured_style(self):
  args=parser().parse_args(['preview','projects/indoor_sample.json']);variants,_,_,_=candidate_profiles({'use_case':'indoor_talk','style':'monochrome'},args,{})
  self.assertEqual(variants[0][1]['style'],'monochrome');self.assertTrue(any(r['style']=='natural' for _,r in variants))
 def test_explicit_style_list_exact(self):
  args=parser().parse_args(['preview','project.json','--styles','natural,soft_film']);v,_,_,_=candidate_profiles({'style':'monochrome'},args,{})
  self.assertEqual([r['style'] for _,r in v],['natural','soft_film'])
 def test_legacy_tone(self):
  args=parser().parse_args(['render','project.json','--tone','soft_warm']);v,_,legacy,_=candidate_profiles({},args,{})
  self.assertEqual(legacy,'soft_warm');self.assertEqual(v[0][1],{'legacy_tone':'soft_warm'})
 def test_frozen_baseline_not_resolved_again(self):
  import tempfile,json
  from pathlib import Path
  from unittest.mock import patch
  from video_harness.profiles import resolve
  r=resolve({},'outdoor_night','soft_film')
  with tempfile.TemporaryDirectory() as tmp:
   p=Path(tmp)/'baseline.json';p.write_text(json.dumps({'decision':'accept','review':{'decision':'accept'},'resolved':r}))
   args=parser().parse_args(['render','project.json','--baseline',str(p)])
   with patch('video_harness.cli.get',side_effect=AssertionError('must not read mutable catalog')):
    v,_,_,_=candidate_profiles({},args,{})
   self.assertEqual(v[0][1],r)
 def test_legacy_adjustments_not_silently_ignored(self):
  args=parser().parse_args(['render','project.json','--tone','soft_warm','--exposure-stops','.5'])
  with self.assertRaises(ValueError):candidate_profiles({},args,{'exposure_stops':.5})
