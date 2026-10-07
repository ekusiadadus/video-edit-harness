import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from xml.etree import ElementTree as ET

from video_harness.fcp import export_timeline
from video_harness.fcp_check import compare_roundtrip, validate_dtd


class FCPRoundtripTests(unittest.TestCase):
    def test_compare_ids_timecode_and_changed_source_range(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / 'source.mov'
            source.write_bytes(b'fixture')
            info = {'streams': [{'codec_type': 'video', 'r_frame_rate': '30/1', 'avg_frame_rate': '30/1',
                                'width': 320, 'height': 180, 'duration': '4'}], 'format': {'duration': '4'}}
            reference = root / 'reference.fcpxml'
            export_timeline(source, info, [(0, 1), (2, 4)], reference, 'Reviewed Edit')
            returned = root / 'returned.fcpxml'
            tree = ET.parse(reference)
            asset = tree.find('./resources/asset')
            asset.set('id', 'new-id')
            asset.set('start', '3600s')
            sequence = tree.find('./library/event/project/sequence')
            sequence.set('tcStart', '7200s')
            for clip in sequence.find('spine'):
                clip.set('ref', 'new-id')
                clip.set('offset', f"{7200 + int(clip.get('offset')[:-1])}s")
                clip.set('start', f"{3600 + int(clip.get('start')[:-1])}s")
            tree.write(returned)
            with patch('video_harness.fcp_check.validate_dtd', return_value={'status': 'pass'}):
                result = compare_roundtrip(reference, returned, root / 'match')
                self.assertEqual(result['status'], 'pass')
                self.assertEqual(result['gui_playback'], 'not_verified')
                sequence.find('spine')[1].set('start', '3603s')
                tree.write(returned)
                result = compare_roundtrip(reference, returned, root / 'mismatch')
                self.assertEqual(result['status'], 'failed')
                self.assertIn('Clip 2: start differs', result['differences'])

    def test_relocated_media_requires_exact_bytes_and_keeps_timing_guards(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);source=root/'source.mov';source.write_bytes(b'original media fixture')
            copied=root/'managed-copy.mov';copied.write_bytes(source.read_bytes())
            info={'streams':[{'codec_type':'video','r_frame_rate':'30/1','avg_frame_rate':'30/1',
                              'width':320,'height':180,'duration':'2'}],'format':{'duration':'2'}}
            reference=root/'reference.fcpxml';returned=root/'returned.fcpxml'
            export_timeline(source,info,[(0,2)],reference,'Relocation')
            tree=ET.parse(reference);tree.find('./resources/asset/media-rep').set('src',copied.as_uri());tree.write(returned)
            with patch('video_harness.fcp_check.validate_dtd',return_value={'status':'pass'}):
                self.assertEqual(compare_roundtrip(reference,returned,root/'strict')['status'],'failed')
                result=compare_roundtrip(reference,returned,root/'copied',allow_media_relocation=True)
                self.assertEqual(result['status'],'pass')
                self.assertTrue(result['media_evidence'][0]['exact_bytes_equal'])
                self.assertEqual(result['effect_fidelity'],'not_verified')
                clip=tree.find('.//spine/asset-clip');clip.set('start','1/30s');tree.write(returned)
                result=compare_roundtrip(reference,returned,root/'timing',allow_media_relocation=True)
                self.assertIn('Clip 1: start differs',result['differences'])
                clip.set('start','0s');tree.write(returned)
                copied.write_bytes(b'changed media fixture!')
                result=compare_roundtrip(reference,returned,root/'changed',allow_media_relocation=True)
                self.assertEqual(result['status'],'failed')
                self.assertIn('Clip 1: source bytes differ',result['differences'])
                copied.unlink()
                self.assertEqual(compare_roundtrip(reference,returned,root/'missing',allow_media_relocation=True)['status'],'failed')

    def test_dtd_path_with_spaces_uses_file_uri(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);dtd=root/'Final Cut Pro.app'/'FCPXMLv1_10.dtd';dtd.parent.mkdir();dtd.write_text('fixture')
            xml=root/'timeline.fcpxml';xml.write_text('<fcpxml version="1.10"/>')
            with patch('video_harness.fcp_check.Path.glob',return_value=iter([dtd])), patch('video_harness.fcp_check.run') as run:
                self.assertEqual(validate_dtd(xml,root/'check.log')['status'],'pass')
                self.assertEqual(run.call_args.args[0][3],dtd.resolve().as_uri())

    def test_complex_timeline_is_not_claimed_verified(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            file = root / 'complex.fcpxml'
            file.write_text('<fcpxml version="1.10"><library><event><project name="a"><sequence duration="1s"><spine><gap/></spine></sequence></project></event></library></fcpxml>')
            with patch('video_harness.fcp_check.validate_dtd', return_value={'status': 'pass'}):
                self.assertEqual(compare_roundtrip(file, file, root / 'result')['status'], 'failed')


if __name__ == '__main__':
    unittest.main()
