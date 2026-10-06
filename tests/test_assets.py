from datetime import date
from pathlib import Path
import tempfile
import unittest
import wave

from video_harness.assets import register_asset, validate_asset, select_assets, rank_assets


def fixture(folder):
    path = folder / 'tone.wav'
    with wave.open(str(path), 'wb') as stream:
        stream.setnchannels(1)
        stream.setsampwidth(2)
        stream.setframerate(48000)
        stream.writeframes(b'\0\0' * 4800)
    evidence = folder / 'license.txt'
    evidence.write_text('Synthetic fixture license evidence')
    rights = {'status': 'verified', 'commercial': True, 'advertising': False, 'modification': True,
              'destinations': ['youtube', 'instagram'], 'regions': [], 'attribution_required': True,
              'embedded_use': True, 'mixed_audio_handoff': False, 'raw_asset_handoff': False}
    meta = {'asset_id': 'tone1', 'kind': 'music', 'creator': 'Creator', 'source_url': 'https://example.org/tone',
            'acquired_on': date.today().isoformat(), 'license_url': 'https://example.org/license',
            'verified_on': date.today().isoformat(), 'credit': 'Creator / Tone', 'rights': rights,
            'cost': 0, 'currency': 'JPY', 'content_id': 'none', 'tags': ['calm', 'instrumental'],
            'evidence_path': str(evidence)}
    policy = {'budget': 0, 'currency': 'JPY', 'destinations': ['youtube', 'instagram'],
              'usage': 'monetized', 'attribution': 'allowed', 'network': 'off'}
    return path, meta, policy


class AssetTests(unittest.TestCase):
    def test_context_ranking_rights_unknown_and_duration(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            _, template, policy = fixture(folder)

            def make(asset_id, seconds, characteristics, *, permitted=True):
                path = folder / f'{asset_id}.wav'
                with wave.open(str(path), 'wb') as stream:
                    stream.setparams((1, 2, 48000, 0, 'NONE', 'not compressed'))
                    stream.writeframes(b'\0\0' * (seconds * 48000))
                meta = {**template, 'asset_id': asset_id, 'characteristics': characteristics,
                        'rights': {**template['rights'], 'commercial': permitted}}
                return register_asset(path, meta)

            def observed(**values):
                return {key: {'value': value, 'evidence': 'manual listening by editor'}
                        for key, value in values.items()}

            unknown = make('a_unknown', 8, {})
            sung = make('b_sung', 8, observed(vocals='present', density='high', energy='high'))
            instrumental = make('z_instrumental', 8, observed(vocals='none', density='low', energy='low'))
            short = make('c_short', 1, observed(vocals='none', density='low', energy='low'))
            denied = make('d_denied', 8, observed(vocals='none', density='low', energy='low'), permitted=False)
            request = {'kind': 'music', 'vocals': 'none', 'energy': 'low',
                       'duration': 5, 'dialogue_present': True}
            report = rank_assets([unknown, sung, short, denied, instrumental], request, policy)
            self.assertEqual([row['asset_id'] for row in report['candidates']],
                             ['z_instrumental', 'c_short', 'a_unknown'])
            self.assertIn('vocals', report['candidates'][2]['unknown'])
            self.assertFalse(report['candidates'][2]['inferred'])
            self.assertEqual(report['no_addition']['asset_id'], None)
            self.assertTrue(any(row['asset_id'] == 'd_denied' and 'Commercial' in row['reason']
                                for row in report['excluded']))
            self.assertTrue(any(row['asset_id'] == 'b_sung' and 'outside comparison' in row['reason']
                                for row in report['excluded']))

    def test_characteristics_need_evidence(self):
        with tempfile.TemporaryDirectory() as temp:
            path, meta, _ = fixture(Path(temp))
            meta['characteristics'] = {'vocals': {'value': 'none', 'evidence': ''}}
            with self.assertRaisesRegex(ValueError, 'evidence'):
                register_asset(path, meta)

    def test_registration_selection_and_changed_bytes(self):
        with tempfile.TemporaryDirectory() as temp:
            path, meta, policy = fixture(Path(temp))
            record = register_asset(path, meta)
            self.assertFalse(record['owned_by_user'])
            self.assertEqual(validate_asset(record, policy)['sha256'], record['sha256'])
            selected = select_assets([record], {'kind': 'music', 'tags': ['calm']}, policy)
            self.assertIn('calm', selected[0]['selection_reason'])
            path.write_bytes(path.read_bytes() + b'x')
            with self.assertRaisesRegex(ValueError, 'changed'):
                validate_asset(record, policy)

    def test_independent_rights_and_fail_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            path, meta, policy = fixture(Path(temp))
            record = register_asset(path, meta)
            for operation in ('mixed_audio_handoff', 'raw_asset_handoff'):
                with self.assertRaises(ValueError):
                    validate_asset(record, policy, operation)
            for alteration in ({'attribution': 'forbidden'}, {'destinations': ['tiktok']}, {'advertising': True}):
                with self.assertRaises(ValueError):
                    validate_asset(record, {**policy, **alteration})
            record['content_id'] = 'unknown'
            with self.assertRaises(ValueError):
                validate_asset(record, policy)
            meta['rights']['modification'] = False
            unmodifiable = register_asset(path, meta)
            with self.assertRaisesRegex(ValueError, 'modification rights'):
                validate_asset(unmodifiable, policy)

    def test_unknown_content_id_is_only_for_pending_local_embedded_review(self):
        with tempfile.TemporaryDirectory() as temp:
            path, meta, policy = fixture(Path(temp))
            meta['content_id'] = 'unknown'
            # Grant every handoff right so these refusals isolate Content ID.
            meta['rights']['mixed_audio_handoff'] = True
            meta['rights']['raw_asset_handoff'] = True
            record = register_asset(path, meta)
            with self.assertRaisesRegex(ValueError, 'Content ID state is unknown'):
                validate_asset(record, policy)
            local_policy = {**policy, 'content_id_check': 'pending_local_review'}
            checked = validate_asset(record, local_policy, 'embedded_use')
            self.assertEqual(checked['content_id'], 'unknown')
            for operation in ('mixed_audio_handoff', 'raw_asset_handoff'):
                with self.subTest(operation=operation):
                    with self.assertRaisesRegex(ValueError, 'Content ID state is unknown'):
                        validate_asset(record, local_policy, operation)
            meta['content_id'] = 'registered'
            registered = register_asset(path, meta)
            with self.assertRaisesRegex(ValueError, 'Content ID evidence is missing'):
                validate_asset(registered, local_policy, 'embedded_use')

    def test_rights_evidence_is_bound_to_record(self):
        with tempfile.TemporaryDirectory() as temp:
            path, meta, policy = fixture(Path(temp))
            record = register_asset(path, meta)
            Path(meta['evidence_path']).write_text('Changed license')
            with self.assertRaisesRegex(ValueError, 'evidence changed'):
                validate_asset(record, policy)
            Path(meta['evidence_path']).write_text('Synthetic fixture license evidence')
            record['rights']['raw_asset_handoff'] = True
            with self.assertRaisesRegex(ValueError, 'record changed'):
                validate_asset(record, policy, 'raw_asset_handoff')

    def test_media_and_ownership_evidence(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            path, meta, _ = fixture(folder)
            path.write_text('<html>not media</html>')
            with self.assertRaises(ValueError):
                register_asset(path, meta)
            path.write_bytes(b'RIFF' + b'\0' * 4 + b'WAVE')
            meta['owned_by_user'] = True
            with self.assertRaisesRegex(ValueError, 'Media probe failed'):
                register_asset(path, meta)
            with wave.open(str(path), 'wb') as stream:
                stream.setnchannels(1)
                stream.setsampwidth(2)
                stream.setframerate(48000)
                stream.writeframes(b'\0\0' * 4800)
            with self.assertRaisesRegex(ValueError, 'ownership'):
                register_asset(path, meta)
            evidence = folder / 'ownership.txt'
            evidence.write_text('User-provided ownership record')
            meta['ownership_evidence_path'] = str(evidence)
            self.assertTrue(register_asset(path, meta)['owned_by_user'])
            del meta['rights']['embedded_use']
            with self.assertRaises(ValueError):
                register_asset(path, meta)


if __name__ == '__main__':
    unittest.main()
