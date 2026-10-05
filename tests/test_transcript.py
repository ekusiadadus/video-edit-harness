import json
import tempfile
import unittest
from pathlib import Path

from video_harness.common import fingerprint
from video_harness.transcript import load_transcript,save_transcript,validate_transcript


class TranscriptTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory()
  self.addCleanup(self.temp.cleanup)
  self.root=Path(self.temp.name)
  self.source=self.root/'source.mov'
  self.source.write_bytes(b'synthetic source identity')
  self.data={
   'version':1,'source':fingerprint(self.source),'duration':4.0,'language':'ja',
   'backend':{'name':'openai','sdk_version':'2.0.0','settings':{'model':'whisper-1'}},
   'words':[{'id':'w000001','start':.5,'end':.8,'text':'こんにちは','probability':0.9},
            {'id':'w000002','start':.8,'end':1.1,'text':'。','probability':0.0}],
   'segments':[{'id':'s000001','start':.5,'end':1.1,'text':'こんにちは。'}],
   'warnings':[],'semantic_text':'A greeting.'}

 def test_save_load_and_readable_integrity(self):
  path=save_transcript(self.root/'result',self.data)
  actual=load_transcript(path,self.source)
  self.assertEqual(actual['version'],1)
  self.assertEqual(actual['semantic_text'],'A greeting.')
  self.assertEqual(actual['status'],'review_required')
  self.assertIn('こんにちは',path.with_name('transcript.txt').read_text())
  self.assertEqual(validate_transcript(actual),actual)
  with self.assertRaises(FileExistsError):save_transcript(self.root/'result',self.data)

 def test_json_or_review_text_tampering_rejected(self):
  path=save_transcript(self.root/'result',self.data)
  original=path.read_text()
  altered=json.loads(original);altered['semantic_text']='tampered';path.write_text(json.dumps(altered))
  with self.assertRaisesRegex(ValueError,'hash mismatch'):load_transcript(path)
  path.write_text(original)
  path.with_name('transcript.txt').write_text('tampered')
  with self.assertRaisesRegex(ValueError,'review text missing or changed'):load_transcript(path)

 def test_source_change_rejected(self):
  path=save_transcript(self.root/'result',self.data)
  self.source.write_bytes(b'new source')
  with self.assertRaisesRegex(ValueError,'source changed'):load_transcript(path,self.source)

 def test_invalid_word_order_and_probability_rejected(self):
  self.data['words'][1]['start']=.7
  with self.assertRaisesRegex(ValueError,'words timing'):save_transcript(self.root/'overlap',self.data)
  self.data['words'][1]['start']=.8
  self.data['words'][1]['probability']=float('nan')
  with self.assertRaisesRegex(ValueError,'probability'):save_transcript(self.root/'nan',self.data)

 def test_word_bounds_match_edit_plan_contract(self):
  for start,end in [(0.7999995,1.1),(0.8,4.005)]:
   self.data['words'][1].update(start=start,end=end)
   with self.assertRaisesRegex(ValueError,'words timing'):save_transcript(self.root/'bad-edge',self.data)

 def test_azure_and_overlapping_segments_allowed(self):
  self.data['backend']={'name':'azure','version':'1.0','settings':{'locale':'ja-JP'}}
  self.data['segments'].append({'id':'s000002','start':1.0,'end':1.5,'text':'continued'})
  path=save_transcript(self.root/'azure',self.data)
  self.assertEqual(load_transcript(path)['backend']['name'],'azure')


if __name__=='__main__':unittest.main()
