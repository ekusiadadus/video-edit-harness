"""Session state tests use sealed synthetic artifacts; no media tool is invoked."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from video_harness.common import fingerprint, read, write
from video_harness.session import Session
from video_harness.transcript import load_transcript, save_transcript


class SessionFixture:
    def __init__(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.source = self.root / 'source.mov'
        self.source.write_bytes(b'synthetic source')
        self.project = self.root / 'project.json'
        write(self.project, {'name': 'Synthetic', 'source': str(self.source), 'input_color': 'rec709',
                             'evidence_kind': 'synthetic', 'editorial': {'goal': 'Explain the result'}})
        self.session = Session.start(self.project, self.root / 'session')
        transcript = {'version': 1, 'source': fingerprint(self.source), 'duration': 4.,
                      'language': 'ja', 'backend': {'name': 'openai', 'sdk_version': 'test', 'settings': {}},
                      'words': [{'id': 'w1', 'start': .3, 'end': .7, 'text': 'First', 'probability': .9},
                                {'id': 'w2', 'start': 1.3, 'end': 1.7, 'text': 'Aside', 'probability': .9},
                                {'id': 'w3', 'start': 2.3, 'end': 2.7, 'text': 'Last', 'probability': .9}],
                      'segments': [{'id': 's1', 'start': .3, 'end': 2.7, 'text': 'First Aside Last'}],
                      'semantic_text': 'First Aside Last', 'warnings': []}
        self.transcript_path = save_transcript(self.root / 'original', transcript)

    def close(self):
        self.temp.cleanup()

    def attach(self):
        return self.session.attach_transcript(self.transcript_path, actor='codex')

    def propose(self):
        spec = {'chapters': [{'id': 'result', 'title': 'Result', 'goal_ids': ['goal-1'],
                'spans': [{'id': 'later', 'start_word_id': 'w3', 'end_word_id': 'w3', 'reason': 'Lead'},
                          {'id': 'first', 'start_word_id': 'w1', 'end_word_id': 'w1', 'reason': 'Setup'}]}],
                'omissions': [{'word_ids': ['w2'], 'reason': 'Aside', 'goal_ids': ['goal-1']}]}
        return self.session.propose(spec, actor='claude_code')

    def selected(self):
        self.attach()
        self.propose()
        return self.session.approve('codex', 'Agent selected this sequence for a synthetic fixture')

    def render(self, preview=False, candidate_id=None):
        def fake_render(cfg, plan, out, is_preview):
            out.mkdir()
            payloads = {'video.mp4': b'synthetic encoded video', 'audio-only.mp3': b'synthetic audio',
                        'timeline.fcpxml': b'<fcpxml version="1.10"/>', 'subtitles.srt': b'',
                        'look.cube': b'LUT_3D_SIZE 2\n'}
            for name, data in payloads.items():
                (out / name).write_bytes(data)
            write(out / 'plan.json', plan)
            sequence = plan['sequence']
            write(out / 'frame-mapping.json', {'duration': sum(s['end'] - s['start'] for s in sequence),
                'keep': [[s['start'], s['end']] for s in sequence],
                'sequence_ids': [s['id'] for s in sequence]})
            write(out / 'result.json', {'technical_status': 'pass',
                'artifacts': {name: fingerprint(out / name)['sha256']
                              for name in (*payloads, 'plan.json', 'frame-mapping.json')}})
        with patch('video_harness.editing.render_edit', side_effect=fake_render):
            return self.session.render(preview=preview, actor='codex', candidate_id=candidate_id)


class SessionTests(unittest.TestCase):
    def setUp(self):
        self.fx = SessionFixture()
        self.addCleanup(self.fx.close)

    def test_actor_handoff_and_checkpoint_corruption(self):
        self.fx.selected()
        status = self.fx.session.status(deep=True)
        self.assertEqual(status['phase'], 'needs_render')
        self.assertEqual(status['last_actor'], 'codex')
        handoff = self.fx.session.handoff('claude_code')
        self.assertIn('Actor changes do not turn agent observations into human listening approval', handoff.read_text())
        resumed = self.fx.session.resume('codex')
        self.assertEqual(resumed['phase'], 'needs_render')
        self.assertEqual(resumed['last_actor'], 'codex')
        latest = sorted((self.fx.session.root / 'checkpoints').glob('*.json'))[-1]
        sealed = read(latest)
        sealed['state']['phase'] = 'synthetic_complete'
        latest.write_text(json.dumps(sealed))
        with self.assertRaisesRegex(ValueError, 'checkpoint changed'):
            self.fx.session.resume('claude_code')

    def test_transcript_correction_keeps_original_and_refreshes_packed_brief(self):
        original_ref = self.fx.attach()
        original = load_transcript(original_ref['path'])
        self.fx.session.set_brief({'audience': 'Japanese operators'}, 'human', 'Audience correction')
        corrected_ref = self.fx.session.correct_transcript(
            [{'word_id': 'w1', 'text': 'Corrected'}], 'human', 'Correct spelling')
        corrected = load_transcript(corrected_ref['path'])
        self.assertEqual(load_transcript(original_ref['path'])['words'][0]['text'], 'First')
        self.assertEqual(corrected['words'][0]['text'], 'Corrected')
        self.assertEqual(corrected['words'][0]['start'], original['words'][0]['start'])
        self.assertEqual(corrected['revision_history'][-1]['parent_result_sha256'], original['result_sha256'])
        state = self.fx.session._load()
        packed = read(state['packed']['path'])
        self.assertEqual(packed['words'][0]['text'], 'Corrected')
        self.assertEqual(packed['brief'], read(state['brief']['path']))
        self.fx.session.status(deep=True)

    def test_render_requires_selection_and_sealed_artifacts(self):
        self.fx.attach()
        self.fx.propose()
        with self.assertRaisesRegex(ValueError, 'Explicitly select'):
            self.fx.render()
        self.fx.session.approve('codex', 'Synthetic selection')
        render = self.fx.render()
        self.assertEqual(render['files']['video']['sha256'], fingerprint(render['files']['video']['path'])['sha256'])
        self.fx.session.status(deep=True)
        Path(render['files']['video']['path']).write_bytes(b'tampered')
        with self.assertRaises(ValueError):
            self.fx.session.status(deep=True)



if __name__ == '__main__':
    unittest.main()
