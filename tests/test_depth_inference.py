"""Shared-interval normalization and raw/model provenance, using a fake predictor."""
import io
import json
import subprocess
from contextlib import redirect_stdout
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

import numpy as np
import tests.test_depth_model as model_fixture
from video_harness.common import read
from video_harness.depth_model import inspect_model
from video_harness.depth_artifact import validate_depth
from video_harness.depth_cli import main


class DepthInferenceTests(TestCase):
    def setUp(self):
        fixture = model_fixture.DepthModelTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        self.model_dir = fixture.folder
        self.root = self.model_dir.parent/(self.model_dir.name+'-source')
        self.root.mkdir()
        import shutil
        self.addCleanup(shutil.rmtree, self.root)
        self.source = self.root/'source.mp4'
        subprocess.run(['ffmpeg','-v','error','-n','-f','lavfi','-i',
                        'color=blue:s=16x16:r=4:d=1','-c:v','libx264',
                        '-pix_fmt','yuv420p',str(self.source)], check=True, capture_output=True)
        self.binding = {**inspect_model(self.model_dir), 'device':'cpu',
                        'runtime':{key:'synthetic' for key in ('torch','transformers','safetensors')},
                        'inference':{'resize':'official_DPTImageProcessor_518','interpolation':'bicubic',
                                     'align_corners':False,'raw_relative_depth':True,'near_high_ordering':'unverified'}}

    def fake(self):
        binding = self.binding
        class Predictor:
            def __init__(self, folder):
                self.binding = binding
                self.index = 0
            def predict(self, picture):
                values = np.linspace(0, 1, 256, dtype=np.float32).reshape(16,16) + 10*self.index
                self.index += 1
                return values
        return Predictor

    def test_cli_inference_retains_raw_scale_and_rejects_changed_provenance(self):
        out = self.root/'inferred'
        with patch('video_harness.depth_model.LocalDepthModel', self.fake()), redirect_stdout(io.StringIO()):
            main(['infer',str(self.source),'--model',str(self.model_dir),'--first-frame','1',
                  '--end-frame-exclusive','3','--output',str(out),'--actor','automation',
                  '--note','Synthetic raw predictor; not real model proof'])
        manifest = out/'depth/fields/depth.json'
        doc = validate_depth(manifest)
        self.assertEqual(doc['version'], 2)
        self.assertEqual(doc['normalization'], 'interval_shared_minmax')
        self.assertEqual((doc['inference']['minimum'], doc['inference']['maximum']), (0.,11.))
        values = [np.load(row['field']['path']) for row in doc['rows']]
        self.assertLess(float(values[0].max()), .1)
        self.assertGreater(float(values[1].min()), .9)
        self.assertFalse(doc['inference']['temporal_consistency'])
        self.assertFalse(doc['adopted'])
        self.assertEqual(read(out/'result.json')['technical_status'], 'pass')
        original = manifest.read_text()
        for key, value in [('minimum',-1.),('temporal_consistency',True),('raw_fields',[])]:
            changed = json.loads(original)
            changed['inference'][key] = value
            manifest.write_text(json.dumps(changed))
            with self.subTest(key=key), self.assertRaises(ValueError):
                validate_depth(manifest)
        manifest.write_text(original)
        changed = json.loads(original)
        changed['inference']['model']['runtime']['torch'] = 'fabricated-runtime'
        manifest.write_text(json.dumps(changed))
        with self.assertRaisesRegex(ValueError,'execution record'):
            validate_depth(manifest)
        manifest.write_text(original)
        raw = doc['inference']['raw_fields'][0]['field']['path']
        np.save(raw, np.ones((16,16),dtype=np.float32), allow_pickle=False)
        with self.assertRaisesRegex(ValueError,'binding changed'):
            validate_depth(manifest)

    def test_constant_prediction_fails_without_adopted_manifest(self):
        predictor = self.fake()
        predictor.predict = lambda self, picture: np.ones((16,16),dtype=np.float32)
        out = self.root/'constant'
        with patch('video_harness.depth_model.LocalDepthModel', predictor), self.assertRaises(SystemExit):
            main(['infer',str(self.source),'--model',str(self.model_dir),'--first-frame','0',
                  '--end-frame-exclusive','2','--output',str(out),'--actor','codex','--note','No relative ordering'])
        self.assertEqual(read(out/'result.json')['technical_status'],'failed')
        self.assertFalse((out/'depth/fields/depth.json').exists())
