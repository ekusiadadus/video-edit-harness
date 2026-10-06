"""Source/frame bindings of explicit relative-depth fields, not model proof."""
from pathlib import Path
import json
import subprocess
import tempfile
import unittest
from contextlib import redirect_stdout
import io

import numpy as np

from video_harness.common import read
from video_harness.depth_artifact import prepare_manual_depth, validate_depth
from video_harness.depth_cli import main as depth_main


class DepthArtifactTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root/'source.mp4'
        subprocess.run(['ffmpeg','-v','error','-n','-f','lavfi','-i',
                        'color=blue:s=16x16:r=4:d=1','-c:v','libx264',
                        '-pix_fmt','yuv420p',str(self.source)], check=True, capture_output=True)
        self.fields = {}
        for frame in (1, 2):
            path = self.root/f'input-{frame}.npy'
            np.save(path, np.linspace(0, 1, 256, dtype=np.float32).reshape(16,16), allow_pickle=False)
            self.fields[frame] = path

    def test_cli_preparation_resolves_relative_fields_and_rejects_duplicate_frames(self):
        request = self.root/'request.json'
        rows = [{'frame': frame, 'path': path.name} for frame, path in self.fields.items()]
        request.write_text(json.dumps({'version': 1, 'fields': rows}))
        out = self.root/'cli-run'
        with redirect_stdout(io.StringIO()):
            depth_main(['prepare', str(self.source), str(request), '--output', str(out),
                        '--actor', 'codex', '--note', 'Relative field fixture'])
        doc = validate_depth(out/'fields/depth.json')
        self.assertEqual([row['frame'] for row in doc['rows']], [1,2])
        self.assertEqual(read(out/'result.json')['technical_status'], 'pass')
        request.write_text(json.dumps({'version': 1, 'fields': [rows[0], rows[0]]}))
        failed = self.root/'duplicate-run'
        with self.assertRaises(SystemExit):
            depth_main(['prepare', str(self.source), str(request), '--output', str(failed),
                        '--actor', 'codex', '--note', 'Duplicate rejection'])
        self.assertEqual(read(failed/'result.json')['technical_status'], 'failed')
        self.assertFalse((failed/'fields').exists())

    def test_contiguous_manual_fields_preserve_values_and_require_review(self):
        manifest = prepare_manual_depth(self.source, self.fields, self.root/'depth', 'codex', 'Manual field trial')
        doc = validate_depth(manifest)
        self.assertEqual((doc['start_frame'], doc['end_frame_exclusive'], doc['fps']), (1,3,'4'))
        self.assertIs(doc['review_required'], True)
        self.assertIs(doc['metric_distance'], False)
        self.assertIs(doc['adopted'], False)
        for row in doc['rows']:
            np.testing.assert_array_equal(np.load(row['field']['path']), np.load(self.fields[row['frame']]))
        with self.assertRaises(FileExistsError):
            prepare_manual_depth(self.source, self.fields, self.root/'depth', 'codex', 'No overwrite')
        self.source.write_bytes(self.source.read_bytes()+b'changed')
        with self.assertRaisesRegex(ValueError, 'fingerprint'):
            validate_depth(manifest)

    def test_display_rotation_rejected_before_field_preparation(self):
        rotated = self.root/'rotated.mp4'
        attempt = subprocess.run(['ffmpeg', '-v', 'error', '-n', '-noautorotate',
                                  '-display_rotation', '90', '-i', str(self.source),
                                  '-c', 'copy', str(rotated)], capture_output=True)
        if attempt.returncode:
            # Older FFmpeg uses output metadata instead of display_rotation.
            subprocess.run(['ffmpeg', '-v', 'error', '-n', '-i', str(self.source),
                            '-c', 'copy', '-metadata:s:v:0', 'rotate=90', str(rotated)],
                           check=True, capture_output=True)
        target = self.root/'rotated-depth'
        with self.assertRaisesRegex(ValueError, 'display transforms'):
            prepare_manual_depth(rotated, self.fields, target, 'codex', 'Rotated source rejection')
        self.assertFalse(target.exists())

    def test_invalid_fields_and_frame_ids_fail_without_normalizing_or_writing(self):
        invalid = [({}, 'empty'), ({True:self.fields[1]}, 'boolean'),
                   ({-1:self.fields[1]}, 'negative'), ({1:self.fields[1],3:self.fields[2]}, 'gap')]
        for fields, name in invalid:
            with self.subTest(name=name), self.assertRaises(ValueError):
                prepare_manual_depth(self.source, fields, self.root/name, 'codex', 'Invalid trial')
            self.assertFalse((self.root/name).exists())
        for index, array in enumerate((np.zeros((16,16), np.uint16), np.zeros((8,8),np.float32),
                                       np.full((16,16),np.nan,np.float32), np.full((16,16),1.1,np.float32))):
            np.save(self.fields[1], array, allow_pickle=False)
            with self.assertRaises(ValueError):
                prepare_manual_depth(self.source, self.fields, self.root/f'bad-{index}', 'codex', 'Invalid trial')

    def test_changed_fields_and_malformed_manifest_fail(self):
        manifest = prepare_manual_depth(self.source, self.fields, self.root/'depth', 'automation', 'Fixture')
        original = read(manifest)
        for key, value in (('source', None), ('start_frame', True), ('metric_distance', True),
                           ('rows', []), ('normalization','per-frame-minmax')):
            manifest.write_text(json.dumps({**original,key:value}))
            with self.subTest(key=key), self.assertRaises(ValueError):
                validate_depth(manifest)
        manifest.write_text(json.dumps(original))
        np.save(original['rows'][0]['field']['path'], np.zeros((16,16),np.float32), allow_pickle=False)
        with self.assertRaisesRegex(ValueError, 'binding changed'):
            validate_depth(manifest)
