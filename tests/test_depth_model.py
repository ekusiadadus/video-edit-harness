"""Local-only model identity checks and mocked CPU inference boundary."""

from contextlib import nullcontext
from hashlib import sha256
import json
from pathlib import Path
import struct
import sys
import tempfile
from types import ModuleType, SimpleNamespace
from io import BytesIO
from unittest import TestCase
from unittest.mock import patch

import numpy as np

from video_harness import depth_model
from video_harness.depth_model import (LocalDepthModel, fetch_model, inspect_model,
                                       validate_model_binding)


REVISION = '5426e4f0f36572d16453bbda7a8389317b1bef99'


class DepthModelTests(TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.config = {
            'model_type': 'depth_anything',
            'architectures': ['DepthAnythingForDepthEstimation'],
            'backbone': None,
            'backbone_config': {'model_type': 'dinov2', 'hidden_size': 384,
                                'image_size': 518, 'patch_size': 14},
            'fusion_hidden_size': 64, 'neck_hidden_sizes': [48, 96, 192, 384],
            'reassemble_hidden_size': 384, 'head_hidden_size': 32,
            'use_pretrained_backbone': False,
        }
        self.processor = {'image_processor_type': 'DPTImageProcessor',
                          'size': {'height': 518, 'width': 518},
                          'ensure_multiple_of': 14, 'keep_aspect_ratio': True,
                          'do_resize': True, 'do_rescale': True,
                          'do_normalize': True, 'do_pad': False,
                          'image_mean': [0.485, 0.456, 0.406],
                          'image_std': [0.229, 0.224, 0.225]}
        self.save_snapshot()
        fake = json.loads((self.folder/'provenance.json').read_text())['files']
        registry = patch.dict(depth_model.TRUSTED_REVISIONS, {REVISION: fake}, clear=True)
        registry.start()
        self.addCleanup(registry.stop)

    def save_snapshot(self):
        (self.folder/'config.json').write_text(json.dumps(self.config))
        (self.folder/'preprocessor_config.json').write_text(json.dumps(self.processor))
        header = json.dumps({'depth_head.weight': {'dtype': 'F32', 'shape': [1],
                                                  'data_offsets': [0, 4]}}).encode()
        (self.folder/'model.safetensors').write_bytes(struct.pack('<Q', len(header))+header+b'\0'*4)
        files = {name: sha256((self.folder/name).read_bytes()).hexdigest()
                 for name in ('config.json', 'preprocessor_config.json', 'model.safetensors')}
        (self.folder/'provenance.json').write_text(json.dumps({
            'model_id': 'depth-anything/Depth-Anything-V2-Small-hf',
            'revision': REVISION, 'license': 'Apache-2.0', 'files': files}))

    def test_inspect_and_binding_detect_changes(self):
        (self.folder/'README.md').write_text('Official model card retained for notice.')
        binding = inspect_model(self.folder)
        self.assertEqual(binding['revision'], REVISION)
        self.assertEqual(binding['config']['hidden_size'], 384)
        self.assertEqual(binding['processor']['image_processor_type'], 'DPTImageProcessor')
        self.assertIn('README.md', binding['documents'])
        self.assertEqual(validate_model_binding(binding), binding)
        self.assertEqual(validate_model_binding({**binding, 'runtime': {'torch': 'test'},
                                                 'device': 'cpu'}), binding)
        (self.folder/'model.safetensors').write_bytes((self.folder/'model.safetensors').read_bytes()+b'x')
        changed = json.loads((self.folder/'provenance.json').read_text())
        changed['files']['model.safetensors'] = sha256((self.folder/'model.safetensors').read_bytes()).hexdigest()
        (self.folder/'provenance.json').write_text(json.dumps(changed))
        with self.assertRaisesRegex(ValueError, 'trusted official registry'):
            validate_model_binding(binding)

    def test_rejects_wrong_identity_unsafe_tree_symlink_and_processor(self):
        provenance = json.loads((self.folder/'provenance.json').read_text())
        for key, value in (('model_id', 'other/model'), ('revision', 'short'),
                           ('license', 'CC-BY-NC-4.0')):
            changed = {**provenance, key: value}
            (self.folder/'provenance.json').write_text(json.dumps(changed))
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, 'provenance'):
                inspect_model(self.folder)
        (self.folder/'provenance.json').write_text(json.dumps({**provenance, 'revision': '0'*40}))
        with self.assertRaisesRegex(ValueError, 'trusted official registry'):
            inspect_model(self.folder)
        (self.folder/'provenance.json').write_text(json.dumps(provenance))
        for name in ('custom.py', 'pytorch_model.bin', 'extra.json'):
            extra = self.folder/name
            extra.write_bytes(b'unsafe')
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, 'optional notice'):
                inspect_model(self.folder)
            extra.unlink()
        weights = self.folder/'model.safetensors'
        saved = weights.read_bytes()
        weights.unlink()
        external = self.folder.parent/f'{self.folder.name}-external-weights.safetensors'
        external.write_bytes(saved)
        self.addCleanup(external.unlink)
        weights.symlink_to(external)
        with self.assertRaisesRegex(ValueError, 'symlinks'):
            inspect_model(self.folder)
        weights.unlink()
        weights.write_bytes(saved)
        self.processor['image_processor_type'] = 'DepthAnythingImageProcessor'
        self.save_snapshot()
        updated = json.loads((self.folder/'provenance.json').read_text())['files']
        with patch.dict(depth_model.TRUSTED_REVISIONS, {REVISION: updated}, clear=True):
            with self.assertRaisesRegex(ValueError, 'DPTImageProcessor'):
                inspect_model(self.folder)

    def test_bounded_fetch_uses_pinned_urls_and_retains_failures(self):
        sources = {name: (self.folder/name).read_bytes()
                   for name in ('config.json', 'preprocessor_config.json', 'model.safetensors')}
        sources['README.md'] = b'Pinned official model card fixture.\n'
        seen = []

        class Response(BytesIO):
            def __enter__(self):
                return self

            def __exit__(self, *_):
                self.close()

        def local_response(request, timeout):
            self.assertEqual(timeout, 30)
            seen.append(request.full_url)
            return Response(sources[request.full_url.rsplit('/', 1)[-1]])

        target = self.folder.parent/f'{self.folder.name}-fetched'
        self.addCleanup(lambda: __import__('shutil').rmtree(target, ignore_errors=True))
        with patch('video_harness.depth_model.urlopen', side_effect=local_response):
            fetched = fetch_model(target, REVISION)
        self.assertEqual(fetched['revision'], REVISION)
        self.assertIn('README.md', fetched['documents'])
        self.assertEqual(len(seen), 4)
        self.assertTrue(all(f'/resolve/{REVISION}/' in url for url in seen))
        with self.assertRaises(FileExistsError):
            fetch_model(target, REVISION)
        with self.assertRaisesRegex(ValueError, 'Unsupported'):
            fetch_model(self.folder.parent/'unsupported', '0'*40)

        failing = self.folder.parent/f'{self.folder.name}-partial'
        self.addCleanup(lambda: __import__('shutil').rmtree(failing, ignore_errors=True))
        def changed_response(request, timeout):
            name = request.full_url.rsplit('/', 1)[-1]
            return Response(b'altered' if name == 'model.safetensors' else sources[name])
        with patch('video_harness.depth_model.urlopen', side_effect=changed_response):
            with self.assertRaisesRegex(ValueError, 'trusted official registry'):
                fetch_model(failing, REVISION)
        self.assertTrue(failing.is_dir())
        self.assertFalse((failing/'provenance.json').exists())

    def test_mocked_cpu_inference_returns_finite_full_canvas_raw_values(self):
        calls = []

        class Tensor:
            def __init__(self, value):
                self.value = np.asarray(value)
                self.ndim = self.value.ndim
                self.shape = self.value.shape

            def to(self, device):
                calls.append(('to', device))
                return self

            def unsqueeze(self, axis):
                return Tensor(np.expand_dims(self.value, axis))

            def __getitem__(self, key):
                return Tensor(self.value[key])

            def detach(self):
                return self

            def cpu(self):
                return self

            def numpy(self):
                return self.value

        class Processor:
            @classmethod
            def from_pretrained(cls, path, **kwargs):
                calls.append(('processor', path, kwargs))
                return cls()

            def __call__(self, *, images, return_tensors):
                calls.append(('image', images.size, return_tensors))
                return {'pixel_values': Tensor(np.zeros((1, 3, 2, 2)))}

        class Model:
            @classmethod
            def from_pretrained(cls, path, **kwargs):
                calls.append(('model', path, kwargs))
                return cls()

            def to(self, device):
                calls.append(('model_to', device))
                return self

            def eval(self):
                calls.append(('eval',))
                return self

            def __call__(self, **kwargs):
                return SimpleNamespace(predicted_depth=Tensor(np.full((1, 2, 2), 2.5)))

        def interpolate(tensor, *, size, mode, align_corners):
            calls.append(('interpolate', size, mode, align_corners))
            return Tensor(np.full((1, 1, *size), 2.5))

        torch = ModuleType('torch')
        torch.no_grad = nullcontext
        torch.nn = SimpleNamespace(functional=SimpleNamespace(interpolate=interpolate))
        transformers = ModuleType('transformers')
        transformers.AutoImageProcessor = Processor
        transformers.AutoModelForDepthEstimation = Model
        safetensors = ModuleType('safetensors')
        with patch.dict(sys.modules, {'torch': torch, 'transformers': transformers,
                                      'safetensors': safetensors}), patch(
                                          'video_harness.depth_model.importlib.metadata.version',
                                          return_value='test-version'):
            model = LocalDepthModel(self.folder)
            image = np.zeros((3, 5, 3), np.uint8)
            raw = model.predict(image)
        self.assertEqual(raw.shape, (3, 5))
        self.assertEqual(raw.dtype, np.float32)
        self.assertTrue(np.all(raw == 2.5))  # no hidden [0, 1] normalization
        self.assertEqual(model.binding['device'], 'cpu')
        self.assertEqual(model.binding['runtime']['torch'], 'test-version')
        self.assertIn(('interpolate', (3, 5), 'bicubic', False), calls)
        processor_call = next(row for row in calls if row[0] == 'processor')
        model_call = next(row for row in calls if row[0] == 'model')
        self.assertTrue(processor_call[2]['local_files_only'])
        self.assertFalse(processor_call[2]['trust_remote_code'])
        self.assertTrue(model_call[2]['use_safetensors'])
        with self.assertRaisesRegex(ValueError, 'RGB uint8'):
            model.predict(image.astype(np.float32))
