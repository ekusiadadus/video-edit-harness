"""Synthetic render integration for pre-normalization audio gain provenance."""
from copy import deepcopy
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from tests.test_production import ProductionTests
from tests.test_visual_editing import VisualEditingTests
from video_harness.audio_envelopes import load_audio_envelopes
from video_harness.common import fingerprint, read
from video_harness.edl import build_plan
from video_harness.editing import render_edit
from video_harness.session import Session
from video_harness.visual_editing import render_visual_edit


@unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'FFmpeg required')
class AudioGainPipelineTests(unittest.TestCase):
    def assert_gain_binding(self, folder, speech, mixed):
        evidence = read(folder / 'audio-gain-evidence.json')
        manifest, curves = load_audio_envelopes(
            folder / 'audio-envelopes', expected_speech=speech, expected_mixed_wav=mixed)
        self.assertEqual(evidence['scope'], 'pre_normalization')
        self.assertEqual(evidence['manifest'], fingerprint(folder / 'audio-envelopes' / 'manifest.json'))
        self.assertEqual(evidence['manifest_sha256'], manifest['manifest_sha256'])
        self.assertEqual(evidence['speech'], fingerprint(speech))
        self.assertEqual(evidence['mixed_input'], fingerprint(mixed))
        self.assertEqual(evidence['normalized_input'], fingerprint(folder / 'audio-normalized-input.wav'))
        normalization = read(folder / 'audio-normalization-evidence.json')
        self.assertIn(normalization['status'], {'verified_scalar', 'non_scalar'})
        self.assertEqual(normalization['input']['sha256'], fingerprint(mixed)['sha256'])
        self.assertEqual(normalization['output']['sha256'], evidence['normalized_input']['sha256'])
        self.assertEqual(set(curves), {row['cue']['id'] for row in manifest['cues']})
        return manifest

    def test_speech_mix_cache_hit_retains_bound_gain(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cfg = ProductionTests().fixture(root)
            source = root / 'source.mp4'
            subprocess.run(['ffmpeg', '-v', 'error', '-nostdin', '-n',
                '-f', 'lavfi', '-i', 'color=c=gray:s=128x128:r=30:d=2',
                '-f', 'lavfi', '-i', 'sine=frequency=440:sample_rate=48000:duration=2',
                '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-c:a', 'aac', str(source)], check=True)
            cfg.update(source=str(source), name='Synthetic gain fixture', input_color='rec709',
                       evidence_kind='synthetic', render_cache_root=str(root / 'cache'),
                       audio={'normalize': True, 'target_lufs': -16, 'true_peak_db': -1.5,
                              'loudness_range': 7})
            transcript = {'version': 1, 'source': fingerprint(source), 'duration': 2,
                          'words': [{'id': 'fixture-word', 'start': .2, 'end': 1.8,
                                     'text': 'Fixture', 'probability': 1.0}], 'segments': []}
            plan = build_plan(cfg, transcript, [])
            first = render_edit(cfg, plan, root / 'first', True)
            second = render_edit(cfg, plan, root / 'second', True)
            for folder in (first, second):
                manifest = self.assert_gain_binding(folder, folder / 'audio-mixer-speech.wav',
                                                    folder / 'audio-mixer-input.wav')
                self.assertTrue(manifest['cues'])
                self.assertEqual(read(folder / 'result.json')['technical_status'], 'pass')
            self.assertTrue(read(second / 'audio-gain-evidence.json')['cache_event']['reused'])
            self.assertEqual(fingerprint(first / 'audio-envelopes' / 'manifest.json')['sha256'],
                             fingerprint(second / 'audio-envelopes' / 'manifest.json')['sha256'])
            gain_array = next((second / 'audio-envelopes').glob('cue-*.npy'))
            with gain_array.open('ab') as stream:
                stream.write(b'tampered')
            with self.assertRaisesRegex(ValueError, 'fingerprint mismatch'):
                load_audio_envelopes(second / 'audio-envelopes')

    def test_visual_mix_and_session_file_binding(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fixture = VisualEditingTests()
            cfg, edl = fixture.fixture(root, source_audio=True)
            music_cfg = ProductionTests().fixture(root)
            cfg['assets'].extend(deepcopy(music_cfg['assets']))
            cfg['editing_pattern'] = {'id': 'gentle_vlog'}
            folder = render_visual_edit(cfg, edl, root / 'visual', preview=True)
            manifest = self.assert_gain_binding(folder, folder / 'environment.wav',
                                                folder / 'creative-mix.wav')
            self.assertTrue(manifest['cues'])
            self.assertEqual(read(folder / 'result.json')['technical_status'], 'pass')
            # Registration records the exact evidence file alongside the render.
            session = Session.__new__(Session)
            session._verify_render = lambda item: None
            state = {'brief': {'fixture': True}, 'renders': [],
                     'plan': 'fixture-plan', 'project': 'fixture-project'}
            operation = {'id': 'fixture-render', 'path': str(folder), 'preview': True,
                         'plan': 'fixture-plan', 'project': 'fixture-project',
                         'started_at': 'fixture-start'}
            item = session._register_render(state, operation)
            self.assertEqual(item['files']['audio_gain_evidence'],
                             fingerprint(folder / 'audio-gain-evidence.json'))
            self.assertEqual(item['files']['audio_normalization_evidence'],
                             fingerprint(folder / 'audio-normalization-evidence.json'))
