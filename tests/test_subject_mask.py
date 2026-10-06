import json
from fractions import Fraction
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import cv2
import numpy as np

from video_harness.subject_mask import prepare_masks, segment_frame, validate_masks
from video_harness.video_effects import _sha


def _scene():
    frame = np.full((64, 64, 3), (220, 20, 20), np.uint8)
    cv2.circle(frame, (32, 32), 14, (20, 220, 20), -1)
    return frame


class SubjectMaskTests(unittest.TestCase):
  def test_segment_frame_is_actual_foreground_and_deterministic(self):
    frame = _scene()
    first, stats = segment_frame(frame, [.15, .15, .85, .85])
    second, _ = segment_frame(frame, [.15, .15, .85, .85])
    assert np.array_equal(first, second)
    assert set(np.unique(first)) == {0, 255}
    assert first[32, 32] == 255
    assert first[10, 10] == 0  # Inside the rectangle, outside the subject.
    assert stats['foreground_pixels'] < 44 * 44
    assert stats['foreground_pixels'] + stats['background_pixels'] == 64 * 64


  def test_segment_frame_rejects_no_background_and_empty_result(self):
    with self.assertRaisesRegex(ValueError, 'background'):
        segment_frame(_scene(), [0, 0, 1, 1])
    with self.assertRaises(ValueError):
        segment_frame(np.zeros((64, 64, 3), np.uint8), [.2, .2, .8, .8])


def _fixture(tmp_path):
    source = tmp_path / 'source.bin'
    source.write_bytes(b'fictional source for mocked decode')
    track_path = tmp_path / 'track.json'
    track = {
        'version': 1, 'algorithm': 'csrt-v1', 'source': {
            'path': str(source.resolve()), 'sha256': _sha(source), 'bytes': source.stat().st_size},
        'fps': '30', 'start_frame': 12, 'end_frame_exclusive': 14,
        'rows': [
            {'frame': i, 'box': [.15, .15, .85, .85], 'state': 'manual' if i == 12 else 'tracked',
             'quality': {'tracker_update': True, **({'template_correlation': .8} if i == 13 else {})}}
            for i in (12, 13)], 'review_required': True}
    track_path.write_text(json.dumps(track))
    probe = {'streams': [{'codec_type': 'video', 'nb_read_frames': '20', 'width': 64, 'height': 64}]}
    return source, track_path, probe


def _prepare(tmp_path, corrections=None):
    source, track_path, probe = _fixture(tmp_path)
    frames = [(i, _scene()) for i in (12, 13)]
    # Stub only the media probe and decoder. Provenance, track and PNG validation run normally.
    with patch('video_harness.video_effects._probe', return_value=probe), \
         patch('video_harness.video_effects._verified_rate', return_value=Fraction(30)), \
         patch('video_harness.subject_mask._probe', return_value=probe), \
         patch('video_harness.subject_mask._verified_rate', return_value=Fraction(30)), \
         patch('video_harness.subject_mask._decode', return_value=(item for item in frames)):
        doc = prepare_masks(source, track_path, tmp_path/'masks', 'codex', 'Synthetic unit fixture', corrections)
    return source, track_path, doc


class SubjectMaskArtifactTests(unittest.TestCase):
  def test_prepare_and_validate_binds_absolute_frames_and_detects_png_tamper(self):
    with tempfile.TemporaryDirectory() as folder:
      self._prepare_and_validate(Path(folder))

  def _prepare_and_validate(self, tmp_path):
    source, _, doc = _prepare(tmp_path)
    manifest = tmp_path/'masks'/'manifest.json'
    with patch('video_harness.video_effects._probe', return_value={'streams': [{'codec_type': 'video', 'nb_read_frames': '20', 'width': 64, 'height': 64}]}), \
         patch('video_harness.video_effects._verified_rate', return_value=Fraction(30)), \
         patch('video_harness.subject_mask._probe', return_value={'streams': [{'codec_type': 'video', 'nb_read_frames': '20', 'width': 64, 'height': 64}]}), \
         patch('video_harness.subject_mask._verified_rate', return_value=Fraction(30)):
        assert validate_masks(manifest, source, 12, 14) == doc
    assert [Path(row['mask_path']).name for row in doc['rows']] == ['00000012.png', '00000013.png']
    assert all(Path(row['mask_path']).is_absolute() for row in doc['rows'])
    Path(doc['rows'][0]['mask_path']).write_bytes(b'tampered')
    with self.assertRaisesRegex(ValueError, 'Mask PNG changed'):
        validate_masks(manifest)


  def test_manual_correction_must_be_full_size_binary_and_sealed(self):
    with tempfile.TemporaryDirectory() as folder:
      self._manual_invalid(Path(folder))

  def _manual_invalid(self, tmp_path):
    manual = tmp_path/'manual.png'
    cv2.imwrite(str(manual), np.full((64, 64), 127, np.uint8))
    with self.assertRaisesRegex(ValueError, 'binary'):
        _prepare(tmp_path, {12: manual})
    cv2.imwrite(str(manual), np.zeros((32, 32), np.uint8))
    with self.assertRaisesRegex(ValueError, 'full-size'):
        _prepare(tmp_path, {12: manual})


  def test_manual_correction_provenance_and_original_tamper(self):
    with tempfile.TemporaryDirectory() as folder:
      self._manual_tamper(Path(folder))

  def _manual_tamper(self, tmp_path):
    manual = tmp_path/'manual.png'
    mask = np.zeros((64, 64), np.uint8)
    cv2.circle(mask, (32, 32), 14, 255, -1)
    cv2.imwrite(str(manual), mask)
    _, _, doc = _prepare(tmp_path, {12: manual})
    assert doc['rows'][0]['origin'] == 'manual'
    assert doc['selection']['corrections']['12']['sha256'] == _sha(manual)
    manual.write_bytes(b'tampered')
    with self.assertRaisesRegex(ValueError, 'Manual mask changed'):
        validate_masks(tmp_path/'masks'/'manifest.json')


  def test_resealed_manual_row_must_match_selected_pixels(self):
    with tempfile.TemporaryDirectory() as folder:
      root=Path(folder);manual=root/'manual.png'
      mask=np.zeros((64,64),np.uint8);cv2.circle(mask,(32,32),14,255,-1)
      cv2.imwrite(str(manual),mask)
      _,_,doc=_prepare(root,{12:manual})
      row=doc['rows'][0];export=Path(row['mask_path'])
      altered=np.zeros((64,64),np.uint8);altered[5:15,5:15]=255
      cv2.imwrite(str(export),altered)
      row['sha256']=_sha(export)
      row['stats']={'foreground_pixels':100,'background_pixels':3996}
      manifest=root/'masks'/'manifest.json';manifest.write_text(json.dumps(doc))
      with self.assertRaisesRegex(ValueError,'selected manual correction'):
        validate_masks(manifest)


if __name__ == '__main__':
    unittest.main()
