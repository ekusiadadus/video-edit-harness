import hashlib
import tempfile
import unittest
import wave
from pathlib import Path
from PIL import Image

from video_harness.cues import plan_cues, validate_cues


class CueTests(unittest.TestCase):
    def test_frame_duration_float_is_valid_but_excess_string_precision_is_rejected(self):
        result = plan_cues({'id':'natural'}, [], {'duration':56/30})
        self.assertEqual(result['cues'], [])
        from video_harness.cues import _seconds
        from fractions import Fraction
        self.assertEqual(_seconds(56/30, 'duration'), Fraction(28,15))
        with self.assertRaisesRegex(ValueError,'invalid duration'):
            _seconds('1.00000000001', 'duration')

    def test_music_cue_uses_context_rank_instead_of_asset_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            sung = self.asset(folder, 'a_sung', 'music')
            quiet = self.asset(folder, 'z_quiet', 'music')
            sung['characteristics'] = {'vocals': {'value': 'present', 'evidence': 'listened'},
                                       'energy': {'value': 'high', 'evidence': 'listened'}}
            quiet['characteristics'] = {'vocals': {'value': 'none', 'evidence': 'listened'},
                                        'energy': {'value': 'low', 'evidence': 'listened'}}
            result = plan_cues({'id': 'gentle_vlog'}, [sung, quiet], {'duration': 10},
                               asset_selection_request={'energy': 'low', 'vocals': 'none'})
            self.assertEqual({cue['asset_id'] for cue in result['cues']}, {'z_quiet'})

    def asset(self, folder, asset_id, kind, *, tags=(), owned=False):
        if kind == 'image':
            path = folder / f'{asset_id}.png'
            Image.new('RGB', (16, 16), 'blue').save(path)
        else:
            path = folder / f'{asset_id}.wav'
            with wave.open(str(path), 'wb') as stream:
                stream.setparams((2, 2, 48000, 0, 'NONE', 'not compressed'))
                stream.writeframes(b'\x00\x00\x00\x00' * (48000 * 2))
        return {'asset_id': asset_id, 'path': str(path), 'kind': kind,
                'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
                'tags': list(tags), 'owned_by_user': owned}

    def test_sparse_pattern_and_stale_hash(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'music.wav'
            with wave.open(str(path), 'wb') as stream:
                stream.setparams((2, 2, 48000, 0, 'NONE', 'not compressed'))
                stream.writeframes(b'\x00\x00\x00\x00' * 48000)
            record = {'asset_id': 'music1', 'path': str(path), 'kind': 'music',
                      'sha256': hashlib.sha256(path.read_bytes()).hexdigest(), 'duration': 1}
            self.assertEqual(plan_cues('natural', [record], {'duration': 10})['cues'], [])
            result = plan_cues({'id': 'gentle_vlog'}, [record], {'duration': 10})
            self.assertEqual(len(result['cues']), 2)
            self.assertTrue(all(item['loop'] for item in result['cues']))
            path.write_bytes(b'changed')
            with self.assertRaisesRegex(ValueError, 'SHA-256 mismatch'):
                validate_cues(result['cues'], [record], 10)

    def test_rejects_overshoot_and_unknown_fields(self):
        cue = {'id': 'title', 'asset_id': None, 'role': 'title', 'text': 'Hello',
               'output_start': 0, 'output_end': 2}
        self.assertEqual(len(validate_cues([cue], {}, 2)), 1)
        with self.assertRaisesRegex(ValueError, 'unknown cue fields'):
            validate_cues([{**cue, 'extra': True}], {}, 2)
        with self.assertRaisesRegex(ValueError, 'range'):
            validate_cues([{**cue, 'output_end': 3}], {}, 2)

    def test_explicit_music_policy_overrides_style_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            record = self.asset(Path(tmp), 'music1', 'music')
            mapping = {'duration': 10}
            continuous = plan_cues({'id': 'gentle_vlog', 'music': 'continuous',
                                    'visual_assets': 'off'}, [record], mapping)
            self.assertEqual(len(continuous['cues']), 1)
            self.assertEqual(continuous['cues'][0]['output_end'], '10')
            selected = plan_cues({'id': 'gentle_vlog', 'music': 'selected',
                                  'visual_assets': 'off'}, [record], mapping)
            self.assertEqual(selected['cues'], [])
            self.assertTrue(any('explicit cue plan' in item for item in selected['pending']))

    def test_chapter_requires_actual_mapping_boundary(self):
        with tempfile.TemporaryDirectory() as tmp:
            record = self.asset(Path(tmp), 'music1', 'music')
            pattern = {'id': 'cinematic_story', 'music': 'chapter', 'sfx': 'off', 'visual_assets': 'off'}
            missing = plan_cues(pattern, [record], {'duration': 10})
            self.assertEqual(missing['cues'], [])
            self.assertTrue(any('actual chapter boundaries' in item for item in missing['pending']))
            mapping = {'duration': 10, 'sequence': [
                {'id': 'a', 'chapter_id': 'intro', 'output_start': 0, 'output_end': 5},
                {'id': 'b', 'chapter_id': 'body', 'output_start': 5, 'output_end': 10}]}
            result = plan_cues(pattern, [record], mapping)
            self.assertEqual(len(result['cues']), 1)
            self.assertEqual(result['cues'][0]['output_start'], '5')

    def test_sparse_sfx_and_explicit_visual_anchor(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            sound = self.asset(folder, 'sfx1', 'sfx')
            picture = self.asset(folder, 'image1', 'image', tags=['sequence:b'], owned=True)
            mapping = {'duration': 10, 'sequence': [
                {'id': 'a', 'chapter_id': 'intro', 'output_start': 0, 'output_end': 5},
                {'id': 'b', 'chapter_id': 'body', 'output_start': 5, 'output_end': 10}]}
            pattern = {'id': 'clear_explainer', 'music': 'off', 'sfx': 'accent',
                       'visual_assets': 'own_only'}
            result = plan_cues(pattern, [sound, picture], mapping)
            self.assertEqual([cue['role'] for cue in result['cues']], ['sfx', 'image'])
            self.assertEqual(result['cues'][0]['output_start'], '5')
            picture['owned_by_user'] = False
            no_picture = plan_cues(pattern, [sound, picture], mapping)
            self.assertEqual([cue['role'] for cue in no_picture['cues']], ['sfx'])
            self.assertTrue(any('Visual assets need explicit' in item for item in no_picture['pending']))
            picture['owned_by_user'] = True
            picture['tags'] = ['chapter:body']
            repeated = {'duration': 15, 'sequence': [
                {'id': 'a', 'chapter_id': 'intro', 'output_start': 0, 'output_end': 5},
                {'id': 'b', 'chapter_id': 'body', 'output_start': 5, 'output_end': 10},
                {'id': 'c', 'chapter_id': 'body', 'output_start': 10, 'output_end': 15}]}
            anchored = plan_cues(pattern, [sound, picture], repeated)
            self.assertEqual(len([cue for cue in anchored['cues'] if cue['role'] == 'image']), 1)
