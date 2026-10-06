"""Offline delivery tests for licensed creative additions."""
from datetime import date
from pathlib import Path
import tempfile
import unittest
import wave

from video_harness.assets import register_asset
from video_harness.common import fingerprint, read, write
from video_harness.delivery import bundle


class ProductionDeliveryTests(unittest.TestCase):
    def fixture(self, folder, *, embedded=True, mixed=False):
        private = folder / 'private-catalog'
        private.mkdir()
        asset_file = private / 'synthetic-tone.wav'
        with wave.open(str(asset_file), 'wb') as stream:
            stream.setnchannels(1)
            stream.setsampwidth(2)
            stream.setframerate(48000)
            stream.writeframes(b'\0\0' * 4800)
        evidence = private / 'license-evidence.txt'
        evidence.write_text('Synthetic fixture. Embedded and audio handoff decisions are separate.')
        day = date.today().isoformat()
        asset = register_asset(asset_file, {
            'asset_id': 'synthetic_tone', 'kind': 'music', 'creator': 'Fixture author',
            'source_url': 'https://example.org/tone', 'license_url': 'https://example.org/license',
            'acquired_on': day, 'verified_on': day, 'evidence_path': str(evidence),
            'credit': 'Fixture author: synthetic tone', 'cost': 0, 'currency': 'JPY',
            'content_id': 'none', 'rights': {'status': 'verified', 'commercial': True,
                'advertising': False, 'modification': True, 'destinations': ['youtube'],
                'regions': [], 'attribution_required': True, 'embedded_use': embedded,
                'mixed_audio_handoff': mixed, 'raw_asset_handoff': False}})
        render_dir = folder / 'render'
        render_dir.mkdir()
        files = {}
        for label, name in [('video', 'video.mp4'), ('audio', 'audio-only.mp3'),
                            ('xml', 'timeline.fcpxml'), ('subtitles', 'subtitles.srt'),
                            ('lut', 'look.cube'), ('mapping', 'frame-mapping.json'),
                            ('plan', 'plan.json')]:
            path = render_dir / name
            path.write_bytes((label + ' synthetic fixture').encode())
            files[label] = fingerprint(path)
        production = {'version': 1, 'assets': [asset],
                      'policy': {'destinations': ['youtube'], 'usage': 'monetized',
                                 'budget': 0, 'currency': 'JPY', 'attribution': 'allowed'},
                      'cues': [{'asset_id': asset['asset_id'], 'role': 'music'}]}
        write(render_dir / 'production.json', production)
        files['production'] = fingerprint(render_dir / 'production.json')
        render = {'id': 'synthetic-render', 'path': str(render_dir), 'files': files,
                  'plan': files['plan'], 'project': {'path': 'synthetic-project', 'sha256': 'x'},
                  'preview': False}
        return render, production, asset, private

    def test_mp4_omits_separated_audio_and_xml_when_handoff_denied(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            render, _, asset, private = self.fixture(folder, mixed=False)
            destination = folder / 'delivery'
            manifest = read(bundle(render, {'path': 'brief'}, 'mp4', destination, accepted=True))
            self.assertIn('video', manifest['files'])
            self.assertNotIn('audio', manifest['files'])
            self.assertNotIn('xml', manifest['files'])
            self.assertFalse((destination / 'audio-only.mp3').exists())
            self.assertFalse((destination / 'timeline.fcpxml').exists())
            self.assertFalse((destination / asset_file_name(asset)).exists())
            credits_text = (destination / 'credits.json').read_text()
            self.assertIn('Fixture author', credits_text)
            self.assertNotIn(str(private), credits_text)
            self.assertNotIn(str(asset['path']), credits_text)
            self.assertNotIn(str(asset['evidence_path']), credits_text)

    def test_embedded_denial_rejects_before_directory_creation(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            render, _, _, _ = self.fixture(folder, embedded=False)
            destination = folder / 'denied'
            with self.assertRaises(ValueError):
                bundle(render, {'path': 'brief'}, 'mp4', destination)
            self.assertFalse(destination.exists())

    def test_pending_content_id_local_review_cannot_be_packaged(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            render, production, _, _ = self.fixture(folder)
            production['policy']['content_id_check'] = 'pending_local_review'
            path = Path(render['files']['production']['path'])
            path.unlink()
            write(path, production)
            render['files']['production'] = fingerprint(path)
            for target in ('mp4', 'fcp'):
                destination = folder / target
                with self.assertRaisesRegex(ValueError, 'Local review only'):
                    bundle(render, {}, target, destination, accepted=True)
                self.assertFalse(destination.exists())

    def test_production_evidence_tamper_rejects_before_directory_creation(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            render, _, _, _ = self.fixture(folder)
            Path(render['files']['production']['path']).write_text('{}')
            destination = folder / 'tampered'
            with self.assertRaisesRegex(ValueError, 'Production evidence changed'):
                bundle(render, {'path': 'brief'}, 'mp4', destination)
            self.assertFalse(destination.exists())


def asset_file_name(asset):
    return Path(asset['path']).name


if __name__ == '__main__':
    unittest.main()
