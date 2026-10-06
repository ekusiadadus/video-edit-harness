import io
import json
from importlib.util import find_spec
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from video_harness.tracking import validate_track, track_video
from video_harness.tracking_cli import main


def artifact():
    return {'version': 1, 'algorithm': 'lk-affine-v1',
            'source': {'path': '/tmp/source.mp4', 'sha256': 'a'*64, 'bytes': 8},
            'fps': '24', 'start_frame': 0, 'end_frame_exclusive': 3,
            'review_required': True,
            'rows': [
                {'frame': 0, 'box': [.2, .2, .6, .7], 'state': 'manual', 'quality': {'feature_count': 10}},
                {'frame': 1, 'box': [.21, .2, .61, .7], 'state': 'tracked',
                 'quality': {'feature_count': 10, 'inlier_fraction': .8, 'appearance_mae': .1}},
                {'frame': 2, 'box': None, 'state': 'lost', 'quality': {'feature_count': 3, 'reason': 'insufficient_optical_flow'}}]}


class TrackingValidationTests(unittest.TestCase):
    def test_loss_remains_visible_and_unusable(self):
        doc = artifact()
        self.assertEqual(validate_track(doc)['lost_frames'], [2])
        validate_track(doc, first_frame=0, end_frame=2)
        with self.assertRaisesRegex(ValueError, 'lost frames'):
            validate_track(doc, first_frame=1, end_frame=3)
        with self.assertRaises(ValueError):
            validate_track(doc, first_frame=0)

    def test_schema_and_reacquisition_rejected(self):
        for change in ('gap', 'review', 'reacquisition', 'metric', 'fractional_frame'):
            doc = artifact()
            if change == 'gap':
                doc['rows'].pop(1)
            elif change == 'review':
                doc['review_required'] = False
            elif change == 'reacquisition':
                doc['rows'][0] = {'frame': 0, 'box': None, 'state': 'lost', 'quality': {'feature_count': 0, 'reason': 'occlusion'}}
            elif change == 'metric':
                doc['rows'][1]['quality']['inlier_fraction'] = float('nan')
            else:
                doc['rows'][0]['frame'] = 0.0
            with self.subTest(change=change), self.assertRaises(ValueError):
                validate_track(doc)

    def test_changed_source_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory)/'source.mp4'
            source.write_bytes(b'changed!')
            with self.assertRaisesRegex(ValueError, 'fingerprint'):
                validate_track(artifact(), source=source)

    def test_cli_forwards_real_source_frame_corrections(self):
        with tempfile.TemporaryDirectory() as directory:
            corrections = Path(directory)/'corrections.json'
            corrections.write_text('{"12":[0.1,0.2,0.6,0.8]}')
            with patch('video_harness.tracking_cli.track_video', return_value=artifact()) as track, patch('sys.stdout', new_callable=io.StringIO) as out:
                main(['track', 'input.mp4', '--output', 'track.json', '--box', '.2', '.2', '.6', '.7', '--start-frame', '10', '--end-frame', '20', '--corrections-file', str(corrections)])
                self.assertEqual(track.call_args.kwargs['corrections'], {12: [.1,.2,.6,.8]})
                self.assertTrue(json.loads(out.getvalue())['review_required'])

    def test_cli_duplicate_or_noncanonical_keys_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            corrections = Path(directory)/'corrections.json'
            for text in ('{"1":[],"1":[]}', '{"01":[]}', '{"1.0":[]}', '[]'):
                corrections.write_text(text)
                with patch('video_harness.tracking_cli.track_video') as track, patch('sys.stderr', new_callable=io.StringIO), self.assertRaises(SystemExit) as caught:
                    main(['track', 'input.mp4', '--output', 'track.json', '--box', '.2','.2','.6','.7', '--corrections-file', str(corrections)])
                self.assertEqual(caught.exception.code, 2)
                track.assert_not_called()

    @unittest.skipUnless(find_spec('cv2') and shutil.which('ffmpeg') and shutil.which('ffprobe'), 'tracking tools unavailable')
    def test_actual_cfr_decode_bounds_and_no_overwrite(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory)/'source.mp4'
            output = Path(directory)/'track.json'
            subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i',
                            'testsrc2=size=128x96:rate=10:duration=1', '-threads', '1',
                            '-c:v', 'libx264', '-pix_fmt', 'yuv420p', str(source)], check=True)
            result = track_video(source, [.1,.1,.9,.9], output, start_frame=2, end_frame=8, max_width=128)
            self.assertEqual(result['selection']['actor'],'automation')
            self.assertEqual([r['frame'] for r in result['rows']], list(range(2,8)))
            self.assertEqual(validate_track(output, source=source)['frame_count'], 6)
            with self.assertRaises(FileExistsError):
                track_video(source, [.1,.1,.9,.9], output)


if __name__ == '__main__':
    unittest.main()
