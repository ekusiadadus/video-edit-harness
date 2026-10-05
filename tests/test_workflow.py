import unittest
from unittest.mock import patch
from test_session import SessionFixture
from video_harness.assessment import compare
from video_harness.workflow_cli import parser, dispatch
from video_harness.common import read, write


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.fx=SessionFixture()
        self.addCleanup(self.fx.close)

    def test_cli_shared_actors_context_and_assessment(self):
        self.fx.selected()
        args=parser().parse_args(['resume',str(self.fx.session.root),'--actor','claude_code'])
        self.assertEqual(dispatch(args)['last_actor'],'claude_code')
        args=parser().parse_args(['context',str(self.fx.session.root),'--start','0','--end','1','--words'])
        result=dispatch(args)
        self.assertEqual([w['id'] for w in result['words']],['w1'])
        evaluation=self.fx.session.evaluate()
        self.assertIsNone(evaluation['api_cost'])
        self.assertEqual(evaluation['actors'],['claude_code','codex'])
        self.assertTrue(evaluation['synthetic'])
        self.assertEqual(len(evaluation['resumes']),1)

    def test_comparison_requires_same_brief_and_source(self):
        self.fx.selected()
        rows=compare([self.fx.session,self.fx.session])
        self.assertTrue(rows['same_source_and_brief'])
        other=SessionFixture()
        self.addCleanup(other.close)
        other.selected()
        with self.assertRaisesRegex(ValueError,'same source'):
            compare([self.fx.session,other.session])

    def test_readable_transcript_sidecar_tamper_blocks_resume(self):
        self.fx.attach()
        path=self.fx.session._load()['transcript']['path']
        from pathlib import Path
        Path(path).with_name('transcript.txt').write_text('changed')
        with self.assertRaisesRegex(ValueError,'review text'):
            self.fx.session.resume('claude_code')

    def test_downloaded_feedback_requires_revision_identity(self):
        self.fx.selected()
        render=self.fx.render()
        file=self.fx.root/'feedback.json'
        write(file,{'render_id':render['id'],'start':0,'action':'comment','note':'test'})
        args=parser().parse_args(['feedback',str(self.fx.session.root),'--data-file',str(file)])
        with self.assertRaisesRegex(ValueError,'SHA256'):
            dispatch(args)

    def test_cloud_transcription_attaches_sealed_result_in_same_session(self):
        with patch('video_harness.transcription_router.transcribe',return_value=self.fx.transcript_path) as cloud:
            args=parser().parse_args(['transcribe',str(self.fx.session.root),'--actor','claude_code'])
            ref=dispatch(args)
        self.assertEqual(cloud.call_args.kwargs['provider'],'auto')
        self.assertEqual(read(ref['path'])['source'],self.fx.session._load()['source'])
        self.assertEqual(self.fx.session.status()['phase'],'needs_plan')
        self.assertEqual(self.fx.session.status()['last_actor'],'claude_code')

    def test_feedback_identity_matches_source_mapping(self):
        self.fx.selected()
        render=self.fx.render()
        with self.assertRaisesRegex(ValueError,'sequence ID'):
            self.fx.session.add_feedback(render['id'],0,None,'comment','Contradictory ID','human',sequence_id='first')
        with self.assertRaisesRegex(ValueError,'cut ID'):
            self.fx.session.add_feedback(render['id'],0,None,'comment','Unknown cut','human',cut_id=99)
        accepted=self.fx.session.add_feedback(render['id'],0,None,'comment','Mapped ID','human',sequence_id='later')
        self.assertEqual(accepted['sequence_id'],'later')

    def test_assessment_never_compares_stale_render_to_new_brief(self):
        self.fx.selected()
        self.fx.render()
        current=self.fx.session.evaluate()
        self.assertTrue(current['latest_render_matches_current_inputs'])
        self.fx.session.set_brief({'target_duration_seconds':600},'human','New target')
        stale=self.fx.session.evaluate()
        self.assertFalse(stale['latest_render_matches_current_inputs'])
        self.assertIsNone(stale['rendered_duration_seconds'])
        self.assertIsNone(stale['duration_difference_seconds'])
        self.assertIsNotNone(stale['latest_render_duration_seconds'])
        self.assertIsNone(stale['latest_render_brief']['target_duration_seconds'])

    def test_dead_operation_can_be_resumed_without_acceptance(self):
        self.fx.selected()
        state=self.fx.session._load()
        state['operation']={'kind':'render','pid':12345,'path':str(self.fx.root/'absent')}
        state['phase']='rendering'
        with self.fx.session._lock():
            self.fx.session._save(state,'synthetic_interruption','codex')
        with patch('video_harness.session.os.kill',side_effect=ProcessLookupError):
            result=self.fx.session.resume('claude_code')
        self.assertEqual(result['phase'],'operation_interrupted')
        self.assertIsNone(result['operation'])
        self.assertEqual(result['next_action'],'Render the current plan/project; unchanged verified stages can be reused.')

if __name__=='__main__':
    unittest.main()
