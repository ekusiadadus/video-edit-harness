"""Synthetic media integration; no transcription or human acceptance claim."""

from pathlib import Path
import subprocess
import tempfile
import unittest

from video_harness.common import fingerprint, read, write
from video_harness.edl import build_plan
from video_harness.session import Session
from video_harness.transcript import save_transcript


class SessionCaptionGroupTests(unittest.TestCase):
    def test_group_candidate_render_retime_and_sealed_evidence(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); source = root/'source.mp4'
            subprocess.run(['ffmpeg', '-v', 'error', '-nostdin', '-n', '-f', 'lavfi', '-i',
                'color=c=gray:s=128x128:r=30:d=2', '-f', 'lavfi', '-i',
                'sine=frequency=440:sample_rate=48000:duration=2', '-c:v', 'libx264',
                '-pix_fmt', 'yuv420p', '-c:a', 'aac', str(source)], check=True)
            cfg = {'name': 'Synthetic semantic captions', 'source': str(source), 'input_color': 'rec709',
                   'audio': {'target_lufs': -16, 'true_peak_db': -1.5, 'loudness_range': 11},
                   'evidence_kind': 'synthetic', 'editing_pattern': {'id': 'playful_short',
                   'music': 'off', 'sfx': 'off', 'visual_assets': 'off', 'beat_sync': 'off'}}
            write(root/'project.json', cfg)
            transcript = {'version': 1, 'source': fingerprint(source), 'duration': 2., 'language': 'ja',
                          'backend': {'name': 'openai', 'sdk_version': 'synthetic', 'settings': {}},
                          'words': [{'id': i, 'start': start, 'end': end, 'text': text, 'probability': 1.}
                            for i, (start, end, text) in enumerate([
                                (.2, .3, '120'), (.3, .4, 'fps'), (.4, .5, 'では'), (.5, .65, 'ありません。'),
                                (1.2, 1.4, '設定を'), (1.4, 1.6, '確認します。')])],
                          'segments': [], 'semantic_text': '120 fpsではありません。設定を確認します。', 'warnings': []}
            transcript_path = save_transcript(root/'transcript', transcript)
            session = Session.start(root/'project.json', root/'session')
            session.attach_transcript(transcript_path, actor='automation')
            write(root/'plan.json', build_plan(cfg, read(transcript_path)))
            session.propose(plan_path=root/'plan.json', actor='automation')
            session.approve('automation', 'Synthetic source selection')
            original = session.render(preview=False, actor='automation')
            before = session._load()['project']
            stream = session.caption_source(original['id'])
            spec = {'version': 1, 'word_stream_sha256': stream['word_stream_sha256'],
                    'language': 'ja', 'protected_phrases': ['120 fps', 'ではありません。'],
                    'reading': {'minimum_seconds': .8, 'maximum_units_per_second': 12},
                    'groups': [{'id': name, 'word_refs': [{'word_id': i, 'occurrence_index': 0} for i in indices],
                                'reason': 'Keep the observed negation and instruction together'}
                               for name, indices in [('negation', range(4)), ('instruction', range(4, 6))]]}
            proposed = session.propose_caption_groups(original['id'], spec, 'automation', 'Synthetic phrase proposal')
            self.assertFalse(proposed['adopted'])
            self.assertEqual(session._load()['project'], before)
            self.assertTrue(proposed['caption_proposal']['diagnostics'])
            candidate = session.render(preview=False, actor='automation', candidate_id=proposed['candidate']['id'])
            text = Path(candidate['files']['subtitles']['path']).read_text()
            self.assertIn('120 fpsではありません。', text)
            evidence = read(candidate['files']['captions']['path'])
            self.assertEqual(evidence['grouping_method'], 'explicit_word_groups')
            self.assertEqual(evidence['subtitles_sha256'], candidate['files']['subtitles']['sha256'])
            self.assertEqual(len(evidence['grouping']['captions']), 2)
            self.assertEqual(original['files']['video']['sha256'], candidate['files']['video']['sha256'])
            from video_harness.delivery import bundle
            delivered = read(bundle(candidate, read(session._load()['brief']['path']), 'mp4', root/'delivery'))
            self.assertEqual(delivered['files']['captions']['sha256'], candidate['files']['captions']['sha256'])
            self.assertEqual(delivered['status'], 'needs_review')
            request = {'operations': [{'id': 'pause', 'kind': 'freeze', 'source_frame': 25,
                       'output_frames': 3, 'reason': 'Synthetic nonspoken pause'}],
                       'nonspoken_intervals': [{'first_frame': 24, 'end_frame_exclusive': 27,
                                              'reason': 'Observed synthetic annotation interval'}]}
            held = session.propose_retime(candidate['id'], request, 'automation', 'Synthetic timing proposal')
            retimed = session.render(preview=False, actor='automation', candidate_id=held['candidate']['id'])
            changed = read(retimed['files']['captions']['path'])
            self.assertEqual(changed['word_stream_sha256'], stream['word_stream_sha256'])
            self.assertEqual(changed['timing_basis'], 'retimed_observed_word_frames')
            self.assertAlmostEqual(changed['grouping']['captions'][1]['start'], 1.3)
            self.assertEqual(changed['grouping']['captions'][0]['word_refs'], evidence['grouping']['captions'][0]['word_refs'])
            self.assertEqual(session._load()['project'], before)
            with Path(original['files']['captions']['path']).open('a') as f:
                f.write('tampered')
            with self.assertRaises(ValueError):
                session.caption_source(original['id'])


if __name__ == '__main__':
    unittest.main()
