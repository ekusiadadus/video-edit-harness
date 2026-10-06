"""Pinned, local-only Depth Anything V2 Small inference on CPU.

The model predicts raw relative depth. No metric calibration, per-frame
normalization, source decoding, mask selection, or human review occurs here.
"""

from __future__ import annotations

from copy import deepcopy
import hashlib
import importlib.metadata
import json
from pathlib import Path
import re
import stat
from urllib.request import Request, urlopen

import numpy as np
from PIL import Image

from .common import fingerprint


MODEL_ID = 'depth-anything/Depth-Anything-V2-Small-hf'
_FILES = frozenset({'config.json', 'preprocessor_config.json', 'model.safetensors'})
_DOCUMENTS = frozenset({'README.md', 'LICENSE'})
_SHA = re.compile(r'[0-9a-f]{64}\Z')
_REVISION = re.compile(r'[0-9a-f]{40}\Z')
TRUSTED_REVISIONS = {
    '5426e4f0f36572d16453bbda7a8389317b1bef99': {
        'config.json': 'c56698d3643dde1f83ea2212759e6b31a22b8f827246a36dd007ee8a22b3ff75',
        'preprocessor_config.json': 'd41175c0d889477ca8fc67191e540faef14baf6275157b3fdecf78469e6bbf84',
        'model.safetensors': '3152477ce0d8d6978d76b995120de97cb5b928701fd0f817769f59e249a16b70',
    },
}
_DOWNLOAD_LIMITS = {'config.json': 1024 * 1024,
                    'preprocessor_config.json': 1024 * 1024,
                    'model.safetensors': 512 * 1024 * 1024,
                    'README.md': 1024 * 1024}


def _unique_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f'Duplicate model JSON key: {key}')
        result[key] = value
    return result


def _json(path):
    def invalid(value):
        raise ValueError(f'Nonfinite model JSON value: {value}')
    try:
        value = json.loads(path.read_text(encoding='utf-8'), object_pairs_hook=_unique_pairs,
                           parse_constant=invalid)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f'Invalid model JSON: {path.name}') from exc
    if not isinstance(value, dict):
        raise ValueError(f'Model JSON must be an object: {path.name}')
    return value


def _safetensors_header(path):
    """Check the bounded header and tensor offsets without loading weights."""
    size = path.stat().st_size
    if size < 10 or size > 512 * 1024 * 1024:
        raise ValueError('Model safetensors size is invalid')
    with path.open('rb') as stream:
        length = int.from_bytes(stream.read(8), 'little')
        if not 2 <= length <= min(16 * 1024 * 1024, size - 8):
            raise ValueError('Model safetensors header length is invalid')
        try:
            header = json.loads(stream.read(length), object_pairs_hook=_unique_pairs)
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise ValueError('Model safetensors header is invalid') from exc
    tensors = {key: value for key, value in header.items() if key != '__metadata__'} if isinstance(header, dict) else {}
    if not tensors:
        raise ValueError('Model safetensors has no tensor metadata')
    data_size = size - 8 - length
    for name, spec in tensors.items():
        if (not isinstance(name, str) or not name or not isinstance(spec, dict)
                or spec.get('dtype') not in {'F32', 'F16', 'BF16'}
                or not isinstance(spec.get('shape'), list)
                or any(type(dim) is not int or dim < 0 for dim in spec['shape'])
                or not isinstance(spec.get('data_offsets'), list)
                or len(spec['data_offsets']) != 2):
            raise ValueError('Model safetensors tensor metadata is invalid')
        first, end = spec['data_offsets']
        if type(first) is not int or type(end) is not int or not 0 <= first <= end <= data_size:
            raise ValueError('Model safetensors tensor offsets are invalid')
    return {'tensor_count': len(tensors), 'header_bytes': length}


def inspect_model(model_dir) -> dict:
    """Bind the exact local Small snapshot, refusing executable or linked files."""
    folder = Path(model_dir).expanduser()
    if folder.is_symlink() or not folder.is_dir():
        raise ValueError('Model directory must be a local real directory')
    folder = folder.resolve(strict=True)
    entries = list(folder.iterdir())
    names = {item.name for item in entries}
    if not (_FILES | {'provenance.json'}) <= names or names - (_FILES | _DOCUMENTS | {'provenance.json'}):
        raise ValueError('Model directory needs official files, provenance and optional notice documents only')
    for item in entries:
        if item.is_symlink() or not stat.S_ISREG(item.lstat().st_mode):
            raise ValueError('Model files must be regular local files, without symlinks')
    if not 0 < (folder/'provenance.json').stat().st_size <= 64 * 1024:
        raise ValueError('Model provenance size is invalid')
    provenance = _json(folder/'provenance.json')
    if (set(provenance) != {'model_id', 'revision', 'license', 'files'}
            or provenance['model_id'] != MODEL_ID
            or not isinstance(provenance['revision'], str)
            or not _REVISION.fullmatch(provenance['revision'])
            or provenance['license'] != 'Apache-2.0'
            or not isinstance(provenance['files'], dict)
            or set(provenance['files']) != _FILES):
        raise ValueError('Model provenance must bind official Small ID, revision, license and files')
    for filename, sha in provenance['files'].items():
        if not isinstance(sha, str) or not _SHA.fullmatch(sha):
            raise ValueError(f'Model provenance SHA is invalid: {filename}')
    trusted = TRUSTED_REVISIONS.get(provenance['revision'])
    if trusted is None or provenance['files'] != trusted:
        raise ValueError('Model revision or provenance SHA is not in trusted official registry')
    refs = {name: fingerprint(folder/name) for name in sorted(_FILES)}
    documents = {name: fingerprint(folder/name) for name in sorted(names & _DOCUMENTS)}
    if any(ref['bytes'] > 1024 * 1024 for ref in documents.values()):
        raise ValueError('Model notice document size is invalid')
    if any(refs[name]['sha256'] != provenance['files'][name] for name in _FILES):
        raise ValueError('Model file SHA differs from provenance')
    if any(refs[name]['sha256'] != trusted[name] for name in _FILES):
        raise ValueError('Model file SHA differs from trusted official registry')
    for name in ('config.json', 'preprocessor_config.json'):
        if not 0 < refs[name]['bytes'] <= 1024 * 1024:
            raise ValueError('Model configuration size is invalid')
    config = _json(folder/'config.json')
    backbone = config.get('backbone_config')
    if (config.get('model_type') != 'depth_anything'
            or config.get('architectures') != ['DepthAnythingForDepthEstimation']
            or config.get('backbone') is not None
            or not isinstance(backbone, dict)
            or backbone.get('model_type') != 'dinov2'
            or type(backbone.get('hidden_size')) is not int or backbone['hidden_size'] != 384
            or backbone.get('image_size') != 518 or backbone.get('patch_size') != 14
            or config.get('fusion_hidden_size') != 64
            or config.get('neck_hidden_sizes') != [48, 96, 192, 384]
            or config.get('reassemble_hidden_size') != 384
            or config.get('head_hidden_size') != 32
            or config.get('use_pretrained_backbone') is not False
            or any(key in config for key in ('auto_map', 'custom_pipelines', 'quantization_config'))):
        raise ValueError('Model config is not official Depth Anything V2 Small')
    processor = _json(folder/'preprocessor_config.json')
    if (processor.get('image_processor_type') != 'DPTImageProcessor'
            or processor.get('size') != {'height': 518, 'width': 518}
            or processor.get('ensure_multiple_of') != 14
            or processor.get('keep_aspect_ratio') is not True
            or processor.get('do_resize') is not True
            or processor.get('do_rescale') is not True
            or processor.get('do_normalize') is not True
            or processor.get('do_pad') is not False
            or processor.get('image_mean') != [0.485, 0.456, 0.406]
            or processor.get('image_std') != [0.229, 0.224, 0.225]
            or any(key in processor for key in ('auto_map', 'processor_class'))):
        raise ValueError('Model processor is not official Small DPTImageProcessor')
    header = _safetensors_header(folder/'model.safetensors')
    if any(fingerprint(folder/name) != refs[name] for name in _FILES):
        raise ValueError('Model files changed during inspection')
    if any(fingerprint(folder/name) != documents[name] for name in documents):
        raise ValueError('Model notice documents changed during inspection')
    return {'directory': str(folder), 'model_id': MODEL_ID,
            'revision': provenance['revision'], 'license': provenance['license'],
            'files': refs, 'documents': documents,
            'config': {'model_type': 'depth_anything',
                                     'backbone_model_type': 'dinov2', 'hidden_size': 384},
            'processor': {'image_processor_type': 'DPTImageProcessor',
                          'size': {'height': 518, 'width': 518}, 'ensure_multiple_of': 14},
            'safetensors': header}


def fetch_model(output, revision='5426e4f0f36572d16453bbda7a8389317b1bef99') -> dict:
    """Download only the pinned official files into a new, retained directory.

    A failed fetch leaves the incomplete directory for diagnosis, without
    provenance.json, so it cannot pass ``inspect_model``.
    """
    if not isinstance(revision, str) or revision not in TRUSTED_REVISIONS:
        raise ValueError('Unsupported official Small model revision')
    target = Path(output).expanduser().resolve()
    if target.exists():
        raise FileExistsError(target)
    target.mkdir(parents=True, exist_ok=False)
    trusted = TRUSTED_REVISIONS[revision]
    for name in ('config.json', 'preprocessor_config.json', 'model.safetensors', 'README.md'):
        url = f'https://huggingface.co/{MODEL_ID}/resolve/{revision}/{name}'
        request = Request(url, headers={'User-Agent': 'video-edit-harness/depth-small-fetch'})
        limit = _DOWNLOAD_LIMITS[name]
        length = 0
        digest = hashlib.sha256()
        with urlopen(request, timeout=30) as response, (target/name).open('xb') as output_file:
            while chunk := response.read(1024 * 1024):
                length += len(chunk)
                if length > limit:
                    raise ValueError(f'Model download exceeds bounded size: {name}')
                digest.update(chunk)
                output_file.write(chunk)
        if length == 0:
            raise ValueError(f'Model download is empty: {name}')
        if name in trusted and digest.hexdigest() != trusted[name]:
            raise ValueError(f'Model download SHA differs from trusted official registry: {name}')
        if name == 'README.md':
            try:
                (target/name).read_text(encoding='utf-8')
            except UnicodeError as exc:
                raise ValueError('Model README must be UTF-8 text') from exc
    provenance = {'model_id': MODEL_ID, 'revision': revision,
                  'license': 'Apache-2.0', 'files': deepcopy(trusted)}
    (target/'provenance.json').write_text(json.dumps(provenance, indent=2)+'\n', encoding='utf-8')
    return inspect_model(target)


def validate_model_binding(binding: dict) -> dict:
    """Recheck immutable model identity; runtime metadata remains run evidence."""
    if not isinstance(binding, dict) or not isinstance(binding.get('directory'), str):
        raise ValueError('Model binding needs an absolute local directory')
    expected = inspect_model(binding['directory'])
    allowed = set(expected) | {'runtime', 'device', 'inference'}
    if set(binding) - allowed or any(binding.get(key) != value for key, value in expected.items()):
        raise ValueError('Model binding differs from current local snapshot')
    return expected


class LocalDepthModel:
    """CPU-only official checkpoint loader; construction never downloads files."""

    def __init__(self, model_dir):
        identity = inspect_model(model_dir)
        try:
            import torch
            import transformers
            import safetensors
            from transformers import AutoImageProcessor, AutoModelForDepthEstimation
        except ImportError as exc:
            raise RuntimeError('Local depth inference needs torch, transformers and safetensors') from exc
        folder = identity['directory']
        processor = AutoImageProcessor.from_pretrained(
            folder, local_files_only=True, trust_remote_code=False)
        model = AutoModelForDepthEstimation.from_pretrained(
            folder, local_files_only=True, trust_remote_code=False,
            use_safetensors=True).to('cpu').eval()
        if inspect_model(folder) != identity:
            raise ValueError('Model files changed while loading')
        self._torch = torch
        self._processor = processor
        self._model = model
        self.binding = {**deepcopy(identity),
                        'runtime': {name: importlib.metadata.version(name)
                                    for name in ('torch', 'transformers', 'safetensors')},
                        'device': 'cpu',
                        'inference': {'resize': 'official_DPTImageProcessor_518',
                                      'interpolation': 'bicubic', 'align_corners': False,
                                      'raw_relative_depth': True,
                                      'near_high_ordering': 'unverified'}}

    def predict(self, rgb_uint8: np.ndarray) -> np.ndarray:
        """Return full-canvas raw float32 relative depth; never min-max scale."""
        if (not isinstance(rgb_uint8, np.ndarray) or rgb_uint8.dtype != np.uint8
                or rgb_uint8.ndim != 3 or rgb_uint8.shape[2] != 3
                or min(rgb_uint8.shape[:2]) <= 0):
            raise ValueError('Depth input must be a nonempty HxWx3 RGB uint8 array')
        height, width = rgb_uint8.shape[:2]
        image = Image.fromarray(rgb_uint8, mode='RGB')
        inputs = self._processor(images=image, return_tensors='pt')
        inputs = {key: value.to('cpu') for key, value in inputs.items()}
        with self._torch.no_grad():
            predicted = self._model(**inputs).predicted_depth
            if predicted.ndim != 3 or predicted.shape[0] != 1:
                raise ValueError('Depth model returned an unexpected tensor shape')
            resized = self._torch.nn.functional.interpolate(
                predicted.unsqueeze(1), size=(height, width), mode='bicubic',
                align_corners=False)[0, 0]
        raw = resized.detach().cpu().numpy().astype(np.float32, copy=True)
        if raw.shape != (height, width) or not np.isfinite(raw).all():
            raise ValueError('Depth model returned invalid full-canvas depth')
        return raw
