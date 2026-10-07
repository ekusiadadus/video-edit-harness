import subprocess
import tempfile
import unittest
from pathlib import Path
from xml.etree import ElementTree as ET

from video_harness.fcp import export_timeline, inspect_xml


DTD = Path("/Applications/Final Cut Pro Creator Studio.app/Contents/Frameworks/Interchange.framework/Versions/A/Resources/FCPXMLv1_10.dtd")


def probe():
    return {"streams": [
        {"codec_type": "video", "avg_frame_rate": "30000/1001", "r_frame_rate": "30000/1001",
         "width": 1920, "height": 1080, "side_data_list": [{"rotation": 90}]},
        {"codec_type": "audio", "channels": 2, "sample_rate": "48000"}],
        "format": {"duration": "10.01"}}


class FCPTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.source = self.directory / 'clip & "test".mov'
        self.source.write_bytes(b"test fixture")
        self.output = self.directory / "edited.fcpxml"

    def test_mono_source_keeps_one_channel_in_stereo_project(self):
        info = probe();info['streams'][1]['channels']=1
        export_timeline(self.source,info,[(0,1)],self.output,'Mono speech')
        root=ET.parse(self.output).getroot()
        self.assertEqual(root.find('./resources/asset').get('audioChannels'),'1')
        self.assertEqual(root.find('.//project/sequence').get('audioLayout'),'stereo')
        self.assertEqual(root.find('.//project/sequence').get('audioRate'),'48k')

    def test_export_frame_mapping_audio_and_dtd(self):
        result = export_timeline(self.source, probe(), [(0.01, 1.51), (3.02, 4.01)], self.output, 'Cut & "Review"')
        self.assertEqual((result["width"], result["height"]), (1080, 1920))
        root = ET.parse(self.output).getroot()
        self.assertEqual(root.find("./library/event").get("name"), 'Cut & "Review"')
        clips = root.findall("./library/event/project/sequence/spine/asset-clip")
        self.assertEqual([(c.get("offset"), c.get("start"), c.get("duration")) for c in clips],
                         [("0s", "1001/30000s", "11011/7500s"),
                          ("11011/7500s", "91091/30000s", "29029/30000s")])
        self.assertEqual(root.find("./resources/asset").get("hasAudio"), "1")
        sequence = root.find("./library/event/project/sequence")
        project_format = root.find(f"./resources/format[@id='{sequence.get('format')}']")
        asset_format = root.find(f"./resources/format[@id='{root.find('./resources/asset').get('format')}']")
        self.assertEqual(project_format.get('colorSpace'), '1-1-1 (Rec. 709)')
        self.assertIsNone(asset_format.get('colorSpace'))
        self.assertEqual(project_format.get('frameDuration'), asset_format.get('frameDuration'))
        self.assertNotEqual(sequence.get('format'), root.find('./resources/asset').get('format'))
        self.assertIn("%26", root.find("./resources/asset/media-rep").get("src"))
        if DTD.exists():
            dtd = self.directory / "FCPXMLv1_10.dtd"
            dtd.write_bytes(DTD.read_bytes())
            process = subprocess.run(["xmllint", "--noout", "--dtdvalid", str(dtd), str(self.output)],
                                     capture_output=True, text=True)
            self.assertEqual(process.returncode, 0, process.stderr)

    def test_reject_invalid_intervals_and_overwrite(self):
        for intervals in ([], [(2, 2)], [(2, 1)], [(0, 11)], [(0, 2), (1, 3)], [(2, 3), (1, 2)], [(0, .01)]):
            with self.subTest(intervals=intervals), self.assertRaises(ValueError):
                export_timeline(self.source, probe(), intervals, self.output, "test")
            self.assertFalse(self.output.exists())
        export_timeline(self.source, probe(), [(0, 1)], self.output, "test")
        old = self.output.read_bytes()
        with self.assertRaises(FileExistsError):
            export_timeline(self.source, probe(), [(0, 2)], self.output, "test")
        self.assertEqual(self.output.read_bytes(), old)

    def test_reject_vfr_or_missing_source(self):
        altered = probe()
        altered["streams"][0]["avg_frame_rate"] = "24/1"
        with self.assertRaisesRegex(ValueError, "variable frame rate"):
            export_timeline(self.source, altered, [(0, 1)], self.output, "test")
        with self.assertRaises(FileNotFoundError):
            export_timeline(self.directory / "missing.mov", probe(), [(0, 1)], self.output, "test")

    def test_generated_full_range_recovers_rounded_down_tail_and_checks_mapping(self):
        from video_harness.fcp import export_full_timeline
        from fractions import Fraction
        for count, rate in ((245, Fraction(24)), (11, Fraction(30000,1001))):
            with self.subTest(count=count, rate=rate):
                observed = probe()
                end = Fraction(count,1)/rate
                observed['streams'][0].update(r_frame_rate=str(rate), avg_frame_rate=str(rate),
                    nb_frames=str(count), duration=f'{float(end):.6f}')
                result = export_full_timeline(self.source, observed, count, str(rate), self.output, 'Whole')
                self.assertEqual(Fraction(result['duration'].removesuffix('s')),end)
                self.assertEqual(Fraction(ET.parse(self.output).find('.//asset-clip').get('duration').removesuffix('s')),end)
                self.output.unlink()
                with self.assertRaisesRegex(ValueError,'mapping'):
                    export_full_timeline(self.source,observed,count+1,str(rate),self.output,'Bad count')
                with self.assertRaisesRegex(ValueError,'mapping'):
                    export_full_timeline(self.source,observed,count,str(rate+1),self.output,'Bad FPS')
                self.assertFalse(self.output.exists())
        observed['streams'][0]['duration']='1'
        with self.assertRaisesRegex(ValueError,'duration'):
            export_full_timeline(self.source,observed,count,str(rate),self.output,'Bad duration')

    def test_iphone_nominal_rate_and_full_source_tail(self):
        iphone = probe()
        iphone["streams"][0].update(avg_frame_rate="253800/8461", r_frame_rate="30/1",
                                    duration="7.131667", nb_frames="214")
        iphone["format"]["duration"] = "7.131667"
        result = export_timeline(self.source, iphone, [(0, 7.131667)], self.output, "Full")
        self.assertEqual(result["frame_duration"], "1/30s")
        self.assertEqual(result["duration"], "107/15s")
        root = ET.parse(self.output).getroot()
        self.assertEqual(root.find("./resources/format").get("frameDuration"), "1/30s")
        self.assertEqual(root.find("./resources/asset").get("duration"), "107/15s")
        self.assertEqual(root.find("./library/event/project/sequence/spine/asset-clip").get("duration"), "107/15s")
        if DTD.exists():
            dtd = self.directory / "FCPXMLv1_10.dtd"
            dtd.write_bytes(DTD.read_bytes())
            result = subprocess.run(["xmllint", "--noout", "--dtdvalid", str(dtd), str(self.output)],
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_ordinary_trim_end_stays_conservative_and_nonzero_start_rejected(self):
        iphone = probe()
        iphone["streams"][0].update(avg_frame_rate="253800/8461", r_frame_rate="30/1",
                                    duration="7.131667", nb_frames="214")
        export_timeline(self.source, iphone, [(0, 7.12)], self.output, "Trim")
        clip = ET.parse(self.output).find("./library/event/project/sequence/spine/asset-clip")
        self.assertEqual(clip.get("duration"), "71/10s")
        self.output.unlink()
        iphone["streams"][0]["start_time"] = "0.02"
        with self.assertRaisesRegex(ValueError, "start_time"):
            export_timeline(self.source, iphone, [(0, 1)], self.output, "Bad")
        self.assertFalse(self.output.exists())

    def test_inspect_existing_project_and_complex_structures(self):
        path = self.directory / "complex.fcpxml"
        path.write_text('<fcpxml version="1.10"><resources><asset id="a"><media-rep kind="original-media" src="file:///absent.mov"/></asset><asset id="music" hasAudio="1" hasVideo="0"><media-rep kind="original-media" src="file:///music.wav"/></asset></resources><project name="p"><sequence><spine><title name="Hi"/><caption role="captions.en">Words</caption><audio name="Music"/><asset-clip ref="music" audioRole="music" lane="-1"/><asset-clip ref="a"><timeMap/></asset-clip></spine></sequence></project></fcpxml>')
        report = inspect_xml(path)
        self.assertEqual(len(report["titles"]), 1)
        self.assertEqual(len(report["audio_clips"]), 2)
        self.assertEqual(report["audio_clips"][1]["audioRole"], "music")
        self.assertEqual(report["audio_clips"][1]["lane"], "-1")
        self.assertEqual(report["captions"][0]["text"], "Words")
        self.assertEqual(len(report["speed_effects"]), 1)
        self.assertFalse(report["media_links"][0]["exists"])
        self.assertIn("unsupported or complex structure: timeMap", report["warnings"])


if __name__ == "__main__":
    unittest.main()
