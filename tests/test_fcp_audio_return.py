"""Synthetic FCP return readback of generated pre-normalization gain automation."""
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest
import xml.etree.ElementTree as ET

from tests.test_production_import import ProductionImportTests
from video_harness.audio_mix import render_mix
from video_harness.cues import validate_cues
from video_harness.production_fcp import export_production_xml
from video_harness.production_import import import_production_xml


class FcpAudioReturnTests(unittest.TestCase):
    def fixture(self, root, *, visual=False, fractional=False):
        base, speech, production, _ = ProductionImportTests().fixture(root)
        production = deepcopy(production)
        if fractional:
            production['cues'][0]['output_start'] = .25001
            production['cues'][0]['output_end'] = 1.25001
        if visual:
            from PIL import Image
            import hashlib
            art = root / 'overlay.png'
            Image.new('RGBA', (120, 40), (255, 0, 0, 255)).save(art)
            production['assets'].append({'asset_id': 'art', 'kind': 'image',
                'path': str(art), 'sha256': hashlib.sha256(art.read_bytes()).hexdigest()})
            production['cues'].append({'id': 'illustration', 'asset_id': 'art', 'role': 'image',
                'output_start': .25, 'output_end': 1.25, 'position': 'top', 'opacity': .35})
        production['cues'] = validate_cues(production['cues'], production['assets'], 2)
        mixed = root / 'measured-mix.wav'
        gains = root / 'audio-envelopes'
        render_mix(speech, [cue for cue in production['cues'] if cue['role'] in {'music', 'sfx'}], production['assets'], mixed, 2,
                   gain_output=gains)
        reference = root / 'measured.fcpxml'
        export_production_xml(base, production, None, reference, 'editable',
            gain_inputs={'folder': gains, 'speech': speech, 'mixed': mixed})
        return production, reference

    def returned(self, reference, root):
        output = root / 'returned.fcpxml'
        tree = ProductionImportTests().returned_copy(reference, output)
        return output, tree

    def test_unchanged_measured_xml_and_visual_revision(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            production, reference = self.fixture(root, visual=True)
            output, tree = self.returned(reference, root)
            report = import_production_xml(reference, output, production, 'codex',
                                           'Read back generated automation')
            self.assertEqual(report['status'], 'review_required', report)
            self.assertEqual(report['changes'], [])
            self.assertEqual({cue['id']: cue for cue in report['cue_plan']['cues']},
                             {cue['id']: cue for cue in production['cues']})
            self.assertEqual(report['actor'], 'codex')
            self.assertEqual(report['gui_playback'], 'unverified')
            visual = next(node for node in tree.findall('.//asset-clip/asset-clip')
                          if node.get('srcEnable') == 'video')
            visual.set('duration', '3/4s')
            tree.write(output)
            revised = import_production_xml(reference, output, production, 'human',
                                            'Review shorter illustration')
            self.assertEqual(revised['status'], 'review_required', revised)
            revised_by_id = {cue['id']: cue for cue in revised['cue_plan']['cues']}
            self.assertEqual(revised_by_id['opening'], next(cue for cue in production['cues'] if cue['id'] == 'opening'))
            self.assertEqual(revised_by_id['illustration']['output_end'], 1.0)
            self.assertEqual(revised['actor'], 'human')

    def test_sample_rounded_xml_preserves_fractional_audio_cue_intent(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            production, reference = self.fixture(root, fractional=True)
            output, _ = self.returned(reference, root)
            report = import_production_xml(reference, output, production, 'codex',
                                           'Preserve source cue timing after readback')
            self.assertEqual(report['status'], 'review_required', report)
            self.assertEqual(report['changes'], [])
            cue = next(cue for cue in report['cue_plan']['cues'] if cue['id'] == 'opening')
            self.assertEqual(cue['output_start'], .25001)
            self.assertEqual(cue['output_end'], 1.25001)

    def test_changed_measured_audio_and_dialogue_are_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            production, reference = self.fixture(root)
            for change in ('delete_point', 'gain', 'time', 'param_value', 'cue_range', 'dialogue_guard',
                           'dialogue_role', 'dialogue_source', 'primary_audio',
                           'orphan_animation'):
                with self.subTest(change=change):
                    output, tree = self.returned(reference, root)
                    clips = tree.findall('.//asset-clip/asset-clip')
                    cue = next(node for node in clips if node.get('audioRole') == 'music')
                    dialogue = next(node for node in clips if node.get('audioRole') == 'dialogue')
                    frames = cue.findall('./adjust-volume/param/keyframeAnimation/keyframe')
                    self.assertGreater(len(frames), 1)
                    if change == 'delete_point':
                        cue.find('./adjust-volume/param/keyframeAnimation').remove(frames[-1])
                    elif change == 'gain':
                        frames[0].set('value', '-3dB')
                    elif change == 'time':
                        frames[-1].set('time', '1/10s')
                    elif change == 'param_value':
                        cue.find('./adjust-volume/param').set('value', '-20dB')
                    elif change == 'cue_range':
                        cue.set('duration', '3/4s')
                    elif change == 'dialogue_guard':
                        dialogue.find('adjust-volume').set('amount', '-2dB')
                    elif change == 'dialogue_role':
                        dialogue.set('audioRole', 'music')
                    elif change == 'dialogue_source':
                        dialogue.set('ref', cue.get('ref'))
                    elif change == 'primary_audio':
                        tree.find('./library/event/project/sequence/spine/asset-clip').set('srcEnable', 'all')
                    else:
                        ET.SubElement(tree.find('.//sequence'), 'keyframeAnimation')
                    tree.write(output)
                    report = import_production_xml(reference, output, production,
                                                   'codex', f'Reject {change}')
                    self.assertEqual(report['status'], 'rejected', (change, report))
                    self.assertIsNone(report['cue_plan'])
