"""Actual MP4 decoding plus external-return provenance and resume boundaries."""
from pathlib import Path
import subprocess
import tempfile
import unittest
import io
import json
from contextlib import redirect_stdout
from unittest.mock import patch

from tests.test_session import SessionFixture
from video_harness.common import fingerprint, read
from video_harness.native_finishing import inspect_native_result, validate_native_receipt


class NativeResultTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.media = tempfile.TemporaryDirectory()
        cls.folder = Path(cls.media.name)
        for name, audio in [('tone', 'sine=frequency=440:sample_rate=48000'),
                            ('silent', 'anullsrc=r=48000:cl=stereo'), ('no-audio', None)]:
            command = ['ffmpeg', '-v', 'error', '-nostdin', '-f', 'lavfi', '-i',
                       'color=c=blue:s=96x96:r=24']
            if audio:
                command += ['-f', 'lavfi', '-i', audio]
            command += ['-t', '0.5', '-c:v', 'libx264', '-pix_fmt', 'yuv420p']
            if audio:
                command += ['-c:a', 'aac']
            command += [str(cls.folder / (name + '.mp4'))]
            subprocess.run(command, check=True, capture_output=True)

    @classmethod
    def tearDownClass(cls):
        cls.media.cleanup()

    def setUp(self):
        self.fx = SessionFixture()
        self.addCleanup(self.fx.close)
        self.fx.selected()
        self.render = self.fx.render(preview=False)
        self.request = {'platform': 'tiktok', 'usage': 'personal', 'region': 'JP',
                        'music': {'reference_url': 'https://www.tiktok.com/music/fixture-123',
                                  'start_offset': 0, 'library': 'general'},
                        'effects': [{'id': 'accent', 'reference_url': 'https://www.tiktok.com/effect/fixture-123',
                                     'start': 0, 'end': 0.2, 'reason': 'Synthetic accent'}]}
        self.proposal = self.fx.session.native_finish(self.render['id'], self.request,
                                                      'codex', 'Synthetic external finishing test')

    def receipt(self, name='tone'):
        return {'base_video_sha256': self.render['files']['video']['sha256'],
                'result_video_sha256': fingerprint(self.folder / (name + '.mp4'))['sha256'],
                'method': 'studio_ui',
                'reference_url': 'https://ads.tiktok.com/creative/creativestudio/edit?tempId=fixture',
                'reported_music_applied': True, 'reported_effect_ids': ['accent'],
                'note': 'Synthetic declaration; not native execution proof'}

    def test_audible_result_is_retained_without_adoption_or_native_claims(self):
        before = self.fx.session._load()
        item = self.fx.session.native_result(self.proposal['id'], self.folder / 'tone.mp4',
            self.receipt(), 'codex', 'Retain synthetic external result')
        report = read(item['files']['report']['path'])
        self.assertEqual(item['status'], 'awaiting_native_result_review')
        self.assertFalse(report['audio']['near_silent'])
        self.assertEqual(report['decode'], 'pass')
        for flag in ('music_identity_verified', 'native_effects_verified', 'source_relationship_verified',
                     'timeline_mapping_inherited', 'human_visual_review', 'human_listening_review',
                     'cross_platform_rights_verified', 'native_api_response_verified', 'published'):
            self.assertFalse(report[flag], flag)
        self.assertTrue(report['reported_execution']['reported_music_applied'])
        self.assertAlmostEqual(report['duration_delta'], report['duration'] - report['base_duration'])
        after = self.fx.session._load()
        for key in ('project', 'plan', 'renders', 'reviews', 'candidates', 'completion'):
            self.assertEqual(before.get(key), after.get(key), key)
        self.assertEqual(Path(item['files']['video']['path']).read_bytes(), (self.folder / 'tone.mp4').read_bytes())
        self.fx.session.resume()
        self.assertEqual(self.fx.session.status(deep=True)['native_results'][0]['id'], item['id'])
        Path(item['files']['video']['path']).write_bytes(b'changed output')
        with self.assertRaisesRegex(ValueError, 'artifact changed'):
            self.fx.session.resume()

    def test_silent_and_missing_audio_do_not_satisfy_requested_music(self):
        for name in ('silent', 'no-audio'):
            with self.subTest(name=name):
                item = self.fx.session.native_result(self.proposal['id'], self.folder / (name + '.mp4'),
                    self.receipt(name), 'codex', 'Inspect missing requested music')
                report = read(item['files']['report']['path'])
                self.assertEqual(report['status'], 'requested_music_not_demonstrated')
                self.assertEqual(report['decode'], 'pass')
                self.assertFalse(report['music_identity_verified'])

    def test_legacy_proposal_sha_and_silent_natural_return(self):
        request = {**self.request, 'music': None, 'effects': []}
        proposal = self.fx.session.native_finish(self.render['id'], request, 'codex', 'Silent natural fixture')
        state = self.fx.session._load()
        del state['native_finishing'][-1]['id']
        self.fx.session._save(state, 'synthetic_legacy_proposal', 'codex')
        receipt = {**self.receipt('silent'), 'reported_music_applied': False, 'reported_effect_ids': []}
        item = self.fx.session.native_result(proposal['artifact']['sha256'], self.folder / 'silent.mp4',
            receipt, 'codex', 'Read a legacy proposal without requiring music')
        self.assertEqual(item['status'], 'awaiting_native_result_review')

    def test_receipt_mismatch_unknown_effect_and_auth_query_reject_before_state_changes(self):
        base = read(self.proposal['artifact']['path'])
        result = fingerprint(self.folder / 'tone.mp4')
        before = self.fx.session._load()
        for change in ({'base_video_sha256': '0' * 64}, {'result_video_sha256': '0' * 64},
                       {'reported_effect_ids': ['unknown']}, {'reported_effect_ids': ['accent', 'accent']},
                       {'reported_music_applied': 1}, {'method': 'display_api'},
                       {'reference_url': 'https://ads.tiktok.com/callback?code=synthetic-secret'}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                validate_native_receipt(base, result, {**self.receipt(), **change})
        with self.assertRaisesRegex(ValueError, 'SHA mismatch'):
            self.fx.session.native_result(self.proposal['id'], self.folder / 'silent.mp4',
                self.receipt(), 'codex', 'Reject a wrong output binding')
        with self.assertRaisesRegex(ValueError, 'proposal ID'):
            self.fx.session.native_result(None, self.folder / 'tone.mp4',
                self.receipt(), 'codex', 'Reject an unspecified proposal')
        self.assertEqual(before, self.fx.session._load())

    def test_corrupt_media_cannot_register_a_result(self):
        broken = self.fx.root / 'broken.mp4'
        broken.write_bytes(b'not an MP4')
        receipt = {**self.receipt(), 'result_video_sha256': fingerprint(broken)['sha256']}
        before = self.fx.session._load()
        with self.assertRaises(subprocess.CalledProcessError):
            self.fx.session.native_result(self.proposal['id'], broken, receipt,
                                          'codex', 'Reject undecodable return')
        self.assertEqual(before, self.fx.session._load())

    def test_inspection_refuses_network_playlist_and_existing_evidence_folder(self):
        playlist = self.fx.root / 'playlist.mp4'
        playlist.write_text('#EXTM3U\n#EXTINF:1,\nhttps://example.invalid/secret.ts\n')
        with self.assertRaises(subprocess.CalledProcessError):
            inspect_native_result(playlist, self.fx.root / 'playlist-inspection')
        output = self.fx.root / 'existing'
        output.mkdir()
        with self.assertRaises(FileExistsError):
            inspect_native_result(self.folder / 'tone.mp4', output)

    def test_changed_output_during_inspection_is_rejected(self):
        from video_harness.native_finishing import fingerprint as real_fingerprint
        calls = []
        def changing(path):
            value = real_fingerprint(path)
            if Path(path).resolve() == (self.folder / 'tone.mp4').resolve():
                calls.append(path)
                if len(calls) > 1:
                    return {**value, 'sha256': '0' * 64}
            return value
        with patch('video_harness.native_finishing.fingerprint', side_effect=changing):
            with self.assertRaisesRegex(ValueError, 'changed during inspection'):
                inspect_native_result(self.folder / 'tone.mp4', self.fx.root / 'changed-inspection')

    def test_session_cli_imports_the_returned_file(self):
        from video_harness.workflow_cli import main
        receipt_path = self.fx.root / 'receipt.json'
        receipt_path.write_text(json.dumps(self.receipt()))
        with redirect_stdout(io.StringIO()) as output:
            main(['native-result', str(self.fx.session.root), self.proposal['id'],
                  '--video-file', str(self.folder / 'tone.mp4'), '--receipt-file', str(receipt_path),
                  '--actor', 'codex', '--note', 'Exercise actual CLI result import'])
        item = json.loads(output.getvalue())
        self.assertEqual(item['status'], 'awaiting_native_result_review')
        self.assertEqual(self.fx.session.status(deep=True)['native_results'][0]['id'], item['id'])
