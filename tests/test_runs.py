import tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from video_harness import runs
from video_harness.common import write
class RunTests(unittest.TestCase):
 def test_failed_run_has_result_and_releases_lock(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);source=root/'source';source.write_bytes(b'source');cfg={'source':str(source)}
   with patch.object(runs,'ROOT',root),patch.object(runs,'code_hash',return_value='code'),patch.object(runs.subprocess,'check_output',return_value='tool version\n'):
    with self.assertRaises(ValueError):
     with runs.evidence_run(cfg,'test',root/'output/fail',{}):raise ValueError('expected failure')
    self.assertEqual(runs.read(root/'output/fail/result.json')['technical_status'],'failed')
    with runs.evidence_run(cfg,'test',root/'output/pass',{}):pass
    self.assertEqual(runs.read(root/'output/pass/result.json')['technical_status'],'pass')
 def test_drift_is_failure(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);source=root/'source';source.write_bytes(b'source')
   with patch.object(runs,'ROOT',root),patch.object(runs,'code_hash',return_value='code'),patch.object(runs.subprocess,'check_output',return_value='version\n'):
    with self.assertRaises(ValueError):
     with runs.evidence_run({'source':str(source)},'test',root/'output/drift',{}):source.write_bytes(b'changed')
    self.assertEqual(runs.read(root/'output/drift/result.json')['technical_status'],'failed')
 def test_adoption_requires_review_and_untampered_evidence(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);source=root/'source';source.write_bytes(b'source');out=root/'output/run'
   with patch.object(runs,'ROOT',root),patch.object(runs,'code_hash',return_value='code'),patch.object(runs.subprocess,'check_output',return_value='version\n'):
    with runs.evidence_run({'source':str(source)},'test',out,{}):
     write(out/'candidates.json',['indoor_talk--natural']);write(out/'indoor_talk--natural/resolved.json',{'use_case':'indoor_talk'});write(out/'indoor_talk--natural/evaluation.json',{'technical_status':'pass'})
    with self.assertRaises(ValueError):runs.review(out,'indoor_talk--natural','accept','note',True)
    runs.review(out,'indoor_talk--natural','accept','looks good');self.assertTrue(runs.review(out,'indoor_talk--natural','accept','baseline',True).is_file())
    (out/'indoor_talk--natural/resolved.json').write_text('{}')
    with self.assertRaises(ValueError):runs.review(out,'indoor_talk--natural','accept','note')

 def test_setup_failure_is_recorded(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);source=root/'source';source.write_bytes(b'source')
   with patch.object(runs,'ROOT',root),patch.object(runs.subprocess,'check_output',side_effect=FileNotFoundError('missing tool')):
    with self.assertRaises(FileNotFoundError):
     with runs.evidence_run({'source':str(source)},'test',root/'output/setupfail',{}):pass
    self.assertEqual(runs.read(root/'output/setupfail/result.json')['technical_status'],'failed')
    self.assertIn('run_failed',(root/'output/events.jsonl').read_text())
 def test_review_surface_is_hashed(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);source=root/'source';source.write_bytes(b'source');out=root/'output/run'
   with patch.object(runs,'ROOT',root),patch.object(runs,'code_hash',return_value='code'),patch.object(runs.subprocess,'check_output',return_value='version\n'):
    with runs.evidence_run({'source':str(source)},'test',out,{}):
     write(out/'candidates.json',['c']);write(out/'c/resolved.json',{});write(out/'c/evaluation.json',{});(out/'index.html').write_text('gallery')
    (out/'index.html').write_text('changed')
    with self.assertRaises(ValueError):runs.review(out,'c','accept','note')

 def test_render_and_decode_logs_are_required_for_review_and_adoption(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);source=root/'source';source.write_bytes(b'source');out=root/'output/run'
   with patch.object(runs,'ROOT',root),patch.object(runs,'code_hash',return_value='code'),patch.object(runs.subprocess,'check_output',return_value='version\n'):
    with runs.evidence_run({'source':str(source)},'test',out,{}):
     write(out/'candidates.json',['c']);write(out/'c/resolved.json',{});write(out/'c/evaluation.json',{})
     for name in ('render.log','decode.log'):(out/'c'/name).write_text(f'{name} original')
    artifacts=runs.read(out/'result.json')['artifacts']
    for name in ('render.log','decode.log'):self.assertIn(f'c/{name}',artifacts)
    runs.review(out,'c','accept','reviewed logs')
    self.assertTrue(runs.review(out,'c','accept','adopted logs',True).is_file())
    for name in ('render.log','decode.log'):
     path=out/'c'/name;original=path.read_bytes()
     for change in ('modified','removed'):
      with self.subTest(log=name,change=change):
       if change=='modified':path.write_bytes(b'changed')
       else:path.unlink()
       with self.assertRaisesRegex(ValueError,f'Run artifact changed: c/{name}'):
        runs.review(out,'c','accept','review after change')
       with self.assertRaisesRegex(ValueError,f'Run artifact changed: c/{name}'):
        runs.review(out,'c','accept','adopt after change',True)
       path.write_bytes(original)
