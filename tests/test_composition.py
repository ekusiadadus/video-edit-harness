import unittest
from video_harness.composition import resolve_guides,check_composition

class CompositionTests(unittest.TestCase):
 def mapping(self):return {'fps':'10','duration':'2','sequence':[]}
 def guide(self,kind='subject'):
  return {'id':'face','kind':kind,'rect':[.1,.1,.3,.3],'output_start':'0','output_end':'2','reason':'Observed subject area'}
 def test_guide_validation_and_mapping(self):
  g=self.guide();r=resolve_guides([g],self.mapping())
  self.assertEqual(r['guides'][0]['rect'],[.1,.1,.3,.3])
  for change in ({'rect':[0,0,2,1]},{'output_start':'.05'},{'output_end':'3'}):
   with self.assertRaises(ValueError):resolve_guides([{**g,**change}],self.mapping())
 def test_real_text_bounds_and_time_overlap(self):
  composition=resolve_guides([self.guide('caption')],self.mapping())
  e={'id':'word','type':'keyword_title','output_start':'0','output_end':'1','strength':1,'parameters':{'motion':'fade'}}
  with self.assertRaisesRegex(ValueError,'intersects'):
   check_composition([e],composition,[{'event_id':'word','bounds':[.2,.2,.4,.4]}])
  r=check_composition([e],composition,[{'event_id':'word','bounds':[.5,.5,.7,.7]}])
  self.assertEqual(len(r['checks']),1)
 def test_zoom_does_not_cut_declared_subject(self):
  composition=resolve_guides([self.guide()],self.mapping())
  e={'id':'zoom','type':'smooth_zoom','output_start':'0','output_end':'1','strength':1,
     'parameters':{'anchor_x':1,'anchor_y':1,'max_scale':1.5}}
  with self.assertRaisesRegex(ValueError,'crops'):
   check_composition([e],composition)
  e['parameters']['max_scale']=1.05
  self.assertEqual(len(check_composition([e],composition)['checks']),1)
