from pathlib import Path
import tempfile
import unittest
import xml.etree.ElementTree as ET
import numpy as np
from unittest.mock import patch

from tests import test_production_fcp as fixtures
from video_harness.audio_mix import render_mix
from video_harness.cues import validate_cues
from video_harness.production_fcp import export_production_xml, inspect_production_xml, compare_production_reexport
from video_harness.common import fingerprint, write
from video_harness.production import prepare_fcp_handoff


class FCPAudioAutomationTests(unittest.TestCase):
    def fixture(self, root):
        base, speech, assets = fixtures.ProductionFCPTests().fixtures(root)
        cues = validate_cues([{'id': 'music', 'asset_id': 'm', 'role': 'music',
            'output_start': 0, 'output_end': 2, 'source_start': '.1', 'source_end': '.7',
            'loop': True, 'duck': True, 'fade_in': '.1', 'fade_out': '.1'}], assets, 2)
        mixed = root / 'preview.wav'
        render_mix(speech, cues, assets, mixed, 2, gain_output=root / 'gains')
        inputs = {'folder': root / 'gains', 'speech': speech, 'mixed': mixed}
        production = {'assets': assets, 'cues': cues}
        return base, production, inputs

    def test_measured_loop_keyframes_dialogue_and_readback(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            base, production, inputs = self.fixture(root)
            output = root / 'automated.fcpxml'
            evidence = export_production_xml(base, production, None, output, mode='editable', gain_inputs=inputs)
            self.assertEqual(evidence['audio_automation']['scope'], 'pre_normalization')
            self.assertEqual(evidence['audio_automation']['status'], 'pending_fcp_gui_calibration')
            self.assertEqual(len(evidence['audio_automation']['parts']), 4)
            self.assertTrue(all(part['max_absolute_gain_error'] <= 2e-5 for part in evidence['audio_automation']['parts']))
            observed = inspect_production_xml(output)
            self.assertTrue(all(clip['srcEnable'] == 'video' for clip in observed['primary']))
            dialogue = [clip for clip in observed['connected'] if clip['audioRole'] == 'dialogue']
            self.assertEqual(len(dialogue), 1)
            music = [clip for clip in observed['connected'] if clip['audioRole'] == 'music']
            self.assertEqual(len(music), 4)
            self.assertTrue(all(clip['audio_keyframes'][0]['time'] == '1/10s' for clip in music))
            self.assertTrue(compare_production_reexport(output, output)['matched'])
            self.assertEqual(evidence['dtd'], 'passed' if any(path.exists() for path in fixtures.DTD_PATHS) else 'unavailable')
            tree = ET.parse(output)
            # Explicit interpolation makes FCP discard the whole volume
            # animation, even though it passes DTD validation.
            self.assertTrue(all('interp' not in frame.attrib for frame in tree.iter('keyframe')))
            self.assertTrue(inspect_production_xml(output, expected=evidence))
            legacy = root / 'legacy-interp.fcpxml'
            for frame in tree.iter('keyframe'):
                frame.set('interp', 'linear')
            tree.write(legacy)
            self.assertTrue(inspect_production_xml(legacy))
            # Preserve exact attribute hashes; compatibility is not permission
            # to accept a changed animation against current export evidence.
            with self.assertRaisesRegex(ValueError, 'differs from expected evidence'):
                inspect_production_xml(legacy, expected=evidence)
            tree = ET.parse(output)
            volume = tree.getroot().find('.//adjust-volume/param/..')
            volume.remove(volume.find('param'))
            missing = root / 'missing-automation.fcpxml'
            tree.write(missing)
            with self.assertRaisesRegex(ValueError, 'differs from expected evidence'):
                inspect_production_xml(missing, expected=evidence)

    def test_measured_loop_cannot_extend_beyond_source_eof(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            base, speech, assets = fixtures.ProductionFCPTests().fixtures(root)
            cues = validate_cues([{'id': 'music', 'asset_id': 'm', 'role': 'music',
                'output_start': 0, 'output_end': 2, 'source_start': '.1',
                'source_end': '1.00003', 'loop': True}], assets, 2)
            mixed = root / 'preview.wav'
            render_mix(speech, cues, assets, mixed, 2, gain_output=root / 'gains')
            with self.assertRaisesRegex(ValueError, 'exceeds source media duration'):
                export_production_xml(base, {'assets': assets, 'cues': cues}, None,
                    root / 'eof.fcpxml', mode='editable',
                    gain_inputs={'folder': root / 'gains', 'speech': speech, 'mixed': mixed})

    def test_overlapping_cue_and_loops_match_by_ranges_not_xml_order(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            base, production, inputs = self.fixture(root)
            production['cues'] = validate_cues(production['cues'] + [{
                'id': 'accent', 'asset_id': 'm', 'role': 'music',
                'output_start': '.2', 'output_end': '.6',
                'source_start': 0, 'source_end': '.4'}], production['assets'], 2)
            mixed = root / 'overlap.wav'
            render_mix(inputs['speech'], production['cues'], production['assets'], mixed, 2,
                gain_output=root / 'overlap-gains')
            result = export_production_xml(base, production, None, root / 'overlap.fcpxml',
                mode='editable', gain_inputs={'folder': root / 'overlap-gains',
                    'speech': inputs['speech'], 'mixed': mixed})
            self.assertEqual(len(result['audio_automation']['parts']), 5)

    def test_stale_mix_wrong_mode_and_unknown_automation_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            base, production, inputs = self.fixture(root)
            with self.assertRaisesRegex(ValueError, 'editable mode'):
                export_production_xml(base, production, None, root / 'wrong.fcpxml', gain_inputs=inputs)
            output = root / 'automated.fcpxml'
            export_production_xml(base, production, None, output, mode='editable', gain_inputs=inputs)
            tree = ET.parse(output)
            tree.getroot().find('.//keyframe').set('curve', 'smooth')
            changed = root / 'changed.fcpxml'
            tree.write(changed)
            with self.assertRaisesRegex(ValueError, 'keyframe attributes'):
                inspect_production_xml(changed)
            tree = ET.parse(output)
            animation = tree.getroot().find('.//keyframeAnimation')
            tree.getroot().find('resources').append(animation)
            tree.write(changed)
            with self.assertRaisesRegex(ValueError, 'outside connected audio'):
                inspect_production_xml(changed)
            with inputs['mixed'].open('ab') as stream:
                stream.write(b'changed')
            with self.assertRaisesRegex(ValueError, 'mixed WAV is stale'):
                export_production_xml(base, production, None, root / 'stale.fcpxml', mode='editable', gain_inputs=inputs)

    def test_explicit_handoff_uses_current_render_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            base, production, inputs = self.fixture(root)
            base.rename(root / 'timeline.fcpxml')
            inputs['folder'].rename(root / 'audio-envelopes')
            write(root / 'audio-gain-evidence.json', {
                'version': 1, 'scope': 'pre_normalization',
                'manifest': fingerprint(root / 'audio-envelopes' / 'manifest.json'),
                'speech': fingerprint(inputs['speech']), 'mixed_input': fingerprint(inputs['mixed'])})
            # These synthetic assets do not carry licenses; this test checks
            # handoff wiring, while rights validation has separate tests.
            with patch('video_harness.production.verify_production'):
                result = prepare_fcp_handoff({'fcp_handoff': 'editable',
                    'fcp_audio_automation': 'measured'}, production, root)
            self.assertEqual(result['audio_automation']['scope'], 'pre_normalization')
            self.assertEqual(result['rights_operation'], 'raw_asset_handoff')
            with self.assertRaisesRegex(ValueError, 'explicit editable'):
                prepare_fcp_handoff({'fcp_audio_automation': 'measured'}, production, root)

    def test_session_revision_and_candidate_retain_opt_in(self):
        from tests.test_session import SessionFixture
        from video_harness.common import read
        fixture = SessionFixture()
        self.addCleanup(fixture.close)
        fixture.selected()
        settings = {'fcp_handoff': 'editable', 'fcp_audio_automation': 'measured'}
        candidate = fixture.session.create_candidate(settings, 'codex', 'Compare measured audio')
        self.assertEqual(read(candidate['project']['path'])['fcp_audio_automation'], 'measured')
        revised = fixture.session.update_project(settings, 'codex', 'Retain measured audio')
        self.assertEqual(read(revised['path'])['fcp_audio_automation'], 'measured')
        with self.assertRaisesRegex(ValueError, 'explicit editable'):
            fixture.session.update_project({'fcp_handoff': 'mix'}, 'codex', 'Invalid combination')

    def test_scalar_normalization_is_applied_but_dynamic_change_is_disclosed(self):
        from tests.test_audio_normalization import pcm16, float32_wav
        from video_harness.audio_mix import _decode
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            base, speech, assets = fixtures.ProductionFCPTests().fixtures(root)
            t = np.arange(96000) / 48000
            pcm16(speech, np.column_stack((.1 * np.sin(2 * np.pi * 220 * t),
                                           .1 * np.cos(2 * np.pi * 330 * t))))
            cues = validate_cues([{'id': 'music', 'asset_id': 'm', 'role': 'music',
                'output_start': 0, 'output_end': 2, 'source_start': 0, 'source_end': 1,
                'loop': True}], assets, 2)
            mixed = root / 'preview.wav'
            render_mix(speech, cues, assets, mixed, 2, gain_output=root / 'gains')
            source = _decode(mixed)
            normalized = root / 'normalized.wav'
            float32_wav(normalized, source * 2)
            inputs = {'folder': root / 'gains', 'speech': speech, 'mixed': mixed, 'normalized': normalized}
            production = {'assets': assets, 'cues': cues}
            scalar = export_production_xml(base, production, None, root / 'scalar.fcpxml',
                mode='editable', gain_inputs=inputs)
            self.assertEqual(scalar['audio_automation']['scope'], 'scalar_normalized')
            self.assertAlmostEqual(scalar['audio_automation']['common_gain'], 2, places=6)
            dialogue = next(row for row in inspect_production_xml(root / 'scalar.fcpxml')['connected']
                            if row['audioRole'] == 'dialogue')
            self.assertAlmostEqual(float(dialogue['gain'][:-2]), 20 * np.log10(2), places=6)
            dynamic = source.copy()
            dynamic[48000:] *= .5
            float32_wav(normalized, dynamic)
            fallback = export_production_xml(base, production, None, root / 'dynamic.fcpxml',
                mode='editable', gain_inputs=inputs)
            self.assertEqual(fallback['audio_automation']['scope'], 'pre_normalization')
            self.assertEqual(fallback['audio_automation']['normalization']['status'], 'non_scalar')
            self.assertEqual(fallback['audio_automation']['common_gain'], 1)
