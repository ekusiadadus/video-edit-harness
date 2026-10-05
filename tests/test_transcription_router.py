import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from video_harness.transcription_router import transcribe
from video_harness.cloud_transcript import ProviderFailure


KEYS = {'OPENAI_API_KEY': 'test-key', 'AZURE_OPENAI_API_KEY': 'test-key',
        'AZURE_OPENAI_ENDPOINT': 'https://example.invalid',
        'AZURE_OPENAI_TRANSCRIPTION_DEPLOYMENT': 'semantic',
        'AZURE_OPENAI_TIMESTAMP_DEPLOYMENT': 'timing'}


class RouterTests(unittest.TestCase):
 def setUp(self):
  self.temp = tempfile.TemporaryDirectory()
  self.addCleanup(self.temp.cleanup)
  self.root = Path(self.temp.name)
  self.source = self.root / 'source.mov'
  self.source.write_bytes(b'original')
  self.cfg = {'source': str(self.source)}
  self.result = self.root / 'transcript.json'
  self.result.write_text('{}')

 def report(self):
  return json.loads((self.root / 'run' / 'routing.json').read_text())

 def test_auto_prefers_openai_and_stops_after_success(self):
  calls=[]
  def backend(cfg, provider):
   calls.append(provider)
   return self.result
  with patch.dict('os.environ', KEYS, clear=True), patch('video_harness.cloud_transcript.transcribe_cloud', side_effect=backend):
   result=transcribe(self.cfg,self.root/'run')
  self.assertEqual(result,self.result)
  self.assertEqual(calls,['openai'])
  self.assertEqual(self.report()['status'],'pass')

 def test_auto_falls_back_to_azure_after_provider_failure(self):
  calls=[]
  def backend(cfg, provider):
   calls.append(provider)
   if provider=='openai':raise ProviderFailure('synthetic request failure')
   return self.result
  with patch.dict('os.environ', KEYS, clear=True), patch('video_harness.cloud_transcript.transcribe_cloud', side_effect=backend):
   self.assertEqual(transcribe(self.cfg,self.root/'run'),self.result)
  self.assertEqual(calls,['openai','azure'])
  self.assertEqual([a['status'] for a in self.report()['attempts']],['failed','pass'])
  self.assertNotIn('synthetic request failure',json.dumps(self.report()))

 def test_local_integrity_failure_never_uploads_to_azure(self):
  calls=[]
  def backend(cfg, provider):
   calls.append(provider)
   raise ValueError('cached response changed')
  with patch.dict('os.environ', KEYS, clear=True), patch('video_harness.cloud_transcript.transcribe_cloud', side_effect=backend):
   with self.assertRaisesRegex(ValueError, 'no fallback upload'):
    transcribe(self.cfg,self.root/'run')
  self.assertEqual(calls,['openai'])
  self.assertEqual(self.report()['status'],'aborted_local_error')

 def test_explicit_azure_never_calls_openai(self):
  calls=[]
  def backend(cfg, provider):
   calls.append(provider)
   return self.result
  with patch.dict('os.environ', KEYS, clear=True), patch('video_harness.cloud_transcript.transcribe_cloud', side_effect=backend):
   transcribe(self.cfg,self.root/'run',provider='azure')
  self.assertEqual(calls,['azure'])
  self.assertEqual(self.report()['order'],['azure'])

 def test_source_change_aborts_before_fallback(self):
  calls=[]
  def backend(cfg, provider):
   calls.append(provider)
   self.source.write_bytes(b'changed')
   raise ProviderFailure('synthetic request failure')
  with patch.dict('os.environ', KEYS, clear=True), patch('video_harness.cloud_transcript.transcribe_cloud', side_effect=backend):
   with self.assertRaisesRegex(ValueError,'Source changed'):
    transcribe(self.cfg,self.root/'run')
  self.assertEqual(calls,['openai'])
  self.assertEqual(self.report()['attempts'][0]['status'],'aborted_source_changed')

 def test_unconfigured_openai_skips_to_azure_and_local_is_rejected(self):
  calls=[]
  def backend(cfg, provider):
   calls.append(provider)
   return self.result
  azure={key:value for key,value in KEYS.items() if key!='OPENAI_API_KEY'}
  with patch.dict('os.environ', azure, clear=True), patch('video_harness.cloud_transcript.transcribe_cloud', side_effect=backend):
   transcribe(self.cfg,self.root/'run')
  self.assertEqual(calls,['azure'])
  self.assertEqual(self.report()['attempts'][0]['status'],'not_configured')
  with self.assertRaisesRegex(ValueError,'no local ASR'):
   transcribe(self.cfg,self.root/'not-created',provider='local')
  self.assertFalse((self.root/'not-created').exists())


if __name__=='__main__':unittest.main()
