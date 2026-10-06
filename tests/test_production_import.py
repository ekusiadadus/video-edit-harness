import hashlib
import shutil
import subprocess
import tempfile
import unittest
import wave
import xml.etree.ElementTree as ET
from pathlib import Path

from video_harness.common import probe
from video_harness.fcp import export_timeline
from video_harness.production_fcp import DTD_PATHS, export_production_xml
from video_harness.production_import import import_production_xml


def requires_apple_dtd(version):
    available = shutil.which('xmllint') and any(
        path.with_name(f'FCPXMLv{version.replace(".", "_")}.dtd').is_file()
        for path in DTD_PATHS)
    return unittest.skipUnless(available, f'Installed Apple FCPXML {version} DTD required')


class ProductionImportTests(unittest.TestCase):
    def fixture(self, root):
        video = root / 'source.mp4'
        subprocess.run(['ffmpeg', '-v', 'error', '-nostdin', '-y', '-f', 'lavfi',
                        '-i', 'color=c=black:s=160x90:r=30:d=4', '-f', 'lavfi',
                        '-i', 'sine=frequency=440:sample_rate=48000:duration=4',
                        '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-c:a', 'aac',
                        '-shortest', str(video)], check=True)
        base = root / 'base.fcpxml'
        export_timeline(video, probe(video), [(1, 2), (3, 4)], base, 'Fixture')
        music = root / 'music.wav'
        mixed = root / 'mixed.wav'
        for path, seconds in ((music, 1), (mixed, 2)):
            with wave.open(str(path), 'wb') as stream:
                stream.setparams((2, 2, 48000, 0, 'NONE', 'not compressed'))
                stream.writeframes(b'\x00\x00\x00\x00' * 48000 * seconds)
        asset = {'asset_id': 'music1', 'kind': 'music', 'path': str(music),
                 'sha256': hashlib.sha256(music.read_bytes()).hexdigest()}
        production = {'mapping_sha256': 'a' * 64, 'assets': [asset], 'cues': [
            {'id': 'opening', 'asset_id': 'music1', 'role': 'music',
             'output_start': .25, 'output_end': 1.25, 'source_start': 0,
             'source_end': 1, 'gain_db': -6, 'fade_in': .1,
             'fade_out': .1, 'loop': False, 'duck': True,
             'beat_anchor': .5}]}
        reference = root / 'editable.fcpxml'
        export_production_xml(base, production, mixed, reference, 'editable')
        return base, mixed, production, reference

    def returned_copy(self, reference, output):
        tree = ET.parse(reference)
        root = tree.getroot()
        media = output.parent / 'media'
        media.mkdir(exist_ok=True)
        remap = {}
        for index, item in enumerate(root.findall('./resources/asset'), 1):
            old = item.get('id')
            new = f'renamed{index}'
            remap[old] = new
            uri = item.find('media-rep').get('src')
            source = Path(uri.removeprefix('file://'))
            target = media / f'{new}{source.suffix}'
            shutil.copyfile(source, target)
            item.set('id', new)
            item.set('name', f'Display Name {index}')
            item.find('media-rep').set('src', f'./media/{target.name}')
            ET.SubElement(item, 'metadata')
        for clip in root.findall('.//asset-clip'):
            clip.set('ref', remap[clip.get('ref')])
            clip.set('name', 'FCP renamed this clip')
        tree.write(output)
        return tree

    def test_semantic_resource_match_and_supported_cue_revision(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _, _, production, reference = self.fixture(root)
            output = root / 'returned.fcpxml'
            tree = self.returned_copy(reference, output)
            connected = tree.find('.//asset-clip/asset-clip')
            connected.set('offset', '3/2s')  # first parent source start 1s => output .5s
            connected.find('adjust-volume').set('amount', '-8dB')
            tree.find('.//marker').set('start', '8/5s')  # output .6s
            tree.write(output)
            report = import_production_xml(reference, output, production,
                                           'codex', 'Inspect copied FCP edit')
            self.assertEqual(report['status'], 'review_required', report['reasons'])
            self.assertEqual(report['cue_plan']['mapping_sha256'], 'a' * 64)
            cue = report['cue_plan']['cues'][0]
            self.assertEqual(cue['output_start'], .5)
            self.assertEqual(cue['output_end'], 1.5)
            self.assertEqual(cue['gain_db'], -8)
            self.assertEqual(cue['beat_anchor'], .6)
            self.assertEqual(report['gui_playback'], 'unverified')

    def test_rejects_missing_layer_source_cut_and_unknown_effect(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _, _, production, reference = self.fixture(root)
            output = root / 'returned.fcpxml'
            tree = self.returned_copy(reference, output)
            clip = tree.find('.//asset-clip/asset-clip')
            parent = next(node for node in tree.iter() if clip in list(node))
            parent.remove(clip)
            tree.write(output)
            report = import_production_xml(reference, output, production, 'codex', 'Check missing layer')
            self.assertEqual(report['status'], 'rejected')
            self.assertIn('lost or gained', report['reasons'][0])
            tree = self.returned_copy(reference, output)
            tree.findall('./library/event/project/sequence/spine/asset-clip')[1].set('start', '5/2s')
            tree.write(output)
            report = import_production_xml(reference, output, production, 'codex', 'Check source cut')
            self.assertEqual(report['status'], 'rejected')
            self.assertIn('source cuts', report['reasons'][0])
            tree = self.returned_copy(reference, output)
            tree.find('.//asset-clip/asset-clip').append(ET.Element('filter-audio'))
            tree.write(output)
            report = import_production_xml(reference, output, production, 'codex', 'Check effect')
            self.assertEqual(report['status'], 'rejected')
            self.assertTrue('unsupported FCPXML structure' in report['reasons'][0] or
                            'DTD invalid' in report['reasons'][0])

    def test_mix_is_read_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            base, mixed, production, _ = self.fixture(root)
            reference = root / 'mix.fcpxml'
            export_production_xml(base, production, mixed, reference, 'mix')
            returned = root / 'mix-returned.fcpxml'
            tree = self.returned_copy(reference, returned)
            ET.SubElement(tree.find('.//asset-clip/asset-clip'), 'adjust-volume', amount='-3dB')
            tree.write(returned)
            report = import_production_xml(reference, returned, production,
                                           'human', 'Compare mastered audio placement')
            self.assertEqual(report['status'], 'comparison_only', report['reasons'])
            self.assertIsNone(report['cue_plan'])
            self.assertTrue(report['changes'])
            self.assertIn('no original word', report['scope'])

    @requires_apple_dtd('1.14')
    def test_fcp_114_inert_export_fields_and_missing_start_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _, mixed, production, _ = self.fixture(root)
            source = root / 'source.mp4'
            base = root / 'zero-base.fcpxml'
            export_timeline(source, probe(source), [(0, 2)], base, 'Fixture')
            reference = root / 'mix.fcpxml'
            export_production_xml(base, production, mixed, reference, 'mix')
            returned = root / 'returned.fcpxmld'
            returned.mkdir()
            output = returned / 'Info.fcpxml'
            tree = self.returned_copy(reference, output)
            xml = tree.getroot()
            xml.set('version', '1.14')
            rep = xml.find('./resources/asset/media-rep')
            ET.SubElement(rep, 'bookmark').text = 'AAAA'
            library = xml.find('library')
            collection = ET.SubElement(library, 'smart-collection', name='Fixture', match='any')
            ET.SubElement(collection, 'match-media', rule='is', type='videoOnly')
            for clip in xml.findall('.//asset-clip'):
                if clip.get('start') == '0s':
                    clip.attrib.pop('start')
                clip.insert(0, ET.Element('adjust-colorConform', enabled='1',
                                          autoOrManual='manual', conformType='conformNone',
                                          peakNitsOfPQSource='1000', peakNitsOfSDRToPQSource='203'))
            connected = xml.find('.//asset-clip/asset-clip')
            connected.attrib.pop('srcEnable')
            tree.write(output)
            report = import_production_xml(reference, returned, production,
                                           'codex', 'Inspect current FCP version')
            self.assertEqual(report['status'], 'comparison_only', report['reasons'])

            # FCP may omit this attribute on re-export. For a source with
            # audio it changes playback semantics, so never infer video-only.
            xml.find('./library/event/project/sequence/spine/asset-clip').attrib.pop('srcEnable')
            tree.write(output)
            report = import_production_xml(reference, returned, production,
                                           'codex', 'Reject possible doubled audio')
            self.assertEqual(report['status'], 'rejected')
            self.assertIn('source cuts or frame mapping changed', report['reasons'][0])

    @requires_apple_dtd('1.14')
    def test_fcp_114_nonidentity_color_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _, mixed, production, _ = self.fixture(root)
            source = root / 'source.mp4'
            base = root / 'zero-base.fcpxml'
            export_timeline(source, probe(source), [(0, 2)], base, 'Fixture')
            reference = root / 'mix.fcpxml'
            export_production_xml(base, production, mixed, reference, 'mix')
            output = root / 'returned.fcpxml'
            tree = self.returned_copy(reference, output)
            xml = tree.getroot()
            xml.set('version', '1.14')
            xml.find('./library/event/project/sequence/spine/asset-clip').insert(0,
                ET.Element('adjust-colorConform', enabled='1', autoOrManual='manual',
                           conformType='conformHLGtoSDR', peakNitsOfPQSource='1000',
                           peakNitsOfSDRToPQSource='203'))
            tree.write(output)
            report = import_production_xml(reference, output, production,
                                           'codex', 'Reject changed color')
            self.assertEqual(report['status'], 'rejected')
            self.assertIn('non-identity color', report['reasons'][0])

    @requires_apple_dtd('1.12')
    @requires_apple_dtd('1.13')
    @requires_apple_dtd('1.14')
    def test_current_fcp_versions_use_matching_installed_dtd(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _, mixed, production, _ = self.fixture(root)
            base = root / 'zero-base.fcpxml'
            export_timeline(root / 'source.mp4', probe(root / 'source.mp4'),
                            [(0, 2)], base, 'Fixture')
            reference = root / 'mix.fcpxml'
            export_production_xml(base, production, mixed, reference, 'mix')
            for version in ('1.12', '1.13', '1.14'):
                with self.subTest(version=version):
                    output = root / f'returned-{version}.fcpxml'
                    tree = self.returned_copy(reference, output)
                    tree.getroot().set('version', version)
                    tree.write(output)
                    report = import_production_xml(reference, output, production,
                                                   'codex', 'Check installed DTD version')
                    self.assertEqual(report['status'], 'comparison_only', report['reasons'])


if __name__ == '__main__':
    unittest.main()
