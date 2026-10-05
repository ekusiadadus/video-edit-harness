import unittest
from video_harness.pacing import silence_intervals,candidates,keep_intervals
class PacingTests(unittest.TestCase):
 def test_open_ending(self):
  self.assertEqual(silence_intervals('silence_start: 1.2\nsilence_end: 2.4\nsilence_start: 5',6),[(1.2,2.4),(5,6)])
 def test_padding_and_default_review(self):
  c=candidates([(1,2)],{'pacing':{'keep_after':.18,'keep_before':.16,'minimum_cut':.2}})[0]
  self.assertEqual((c['start'],c['end'],c['enabled']),(1.18,1.84,False))
 def test_review_and_mapping(self):
  plan={'duration':10,'cuts':[{'start':2,'end':3,'enabled':False},{'start':5,'end':7,'enabled':True}]}
  self.assertEqual(keep_intervals(plan),[(0,5),(7,10)])
 def test_overlapping_rejected(self):
  with self.assertRaises(ValueError):keep_intervals({'duration':10,'cuts':[{'start':2,'end':5,'enabled':True},{'start':4,'end':6,'enabled':True}]})
 def test_nonfinite_rejected(self):
  with self.assertRaises(ValueError):keep_intervals({'duration':10,'cuts':[{'start':float('nan'),'end':6,'enabled':True}]})
