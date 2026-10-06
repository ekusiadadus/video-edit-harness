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


class SemanticMaskArtifactTests(unittest.TestCase):
  def _fixture(self, root):
    source, track_path, probe = _fixture(root)
    model = root/'pose.task'; model.write_bytes(b'local pose model')
    track = json.loads(track_path.read_text())
    track['algorithm'] = 'pose-v1'
    track['engine_version'] = 'test-mediapipe'
    track['model'] = {'path': str(model.resolve()), 'sha256': _sha(model), 'bytes': model.stat().st_size}
    track['selection'] = {'actor': 'codex', 'reason': 'Observed torso', 'initial_box': [.15,.15,.85,.85], 'corrections': {'13': [.15,.15,.85,.85]}}
    for row in track['rows']:
      row['state'] = 'manual'
      row['quality'] = {'pose_geometry': 'torso_landmarks', 'min_visibility': .9,
                        'min_presence': .9, 'association_kind': 'seed_overlap', 'association_score': .8}
    track_path.write_text(json.dumps(track))
    return source, track_path, model, probe

  def _run(self, root, rows=None, manual=None, threshold=.5, model_path=None):
    source, track_path, model, probe = self._fixture(root)
    mask = np.zeros((64,64), np.uint8); mask[12:50,20:46] = 255
    if rows is None:
      rows = [{'frame': i, 'state': 'manual', 'box': [.15,.15,.85,.85],
               'mask': mask.copy(), 'quality': {}} for i in range(2)]
    observations = {}
    def semantic(frames, initial_box, supplied_model, fps, corrections, **kwargs):
      observations['rgb'] = [frame.copy() for frame in frames]
      observations['corrections'] = corrections
      return rows
    with patch('video_harness.video_effects._probe', return_value=probe), \
         patch('video_harness.video_effects._verified_rate', return_value=Fraction(30)), \
         patch('video_harness.subject_mask._probe', return_value=probe), \
         patch('video_harness.subject_mask._verified_rate', return_value=Fraction(30)), \
         patch('video_harness.subject_mask._decode', return_value=((i, _scene()) for i in (12,13))), \
         patch('video_harness.subject_mask.version', return_value='test-mediapipe'), \
         patch('video_harness.semantic_mask.segment_frames_pose', side_effect=semantic):
      doc = prepare_masks(source, track_path, root/'masks', 'codex', 'Unit pose mask',
                          {12: manual} if manual else None, backend='pose',
                          model_path=model_path, threshold=threshold)
      assert validate_masks(root/'masks'/'manifest.json', source, 12, 14) == doc
    return doc, observations, model, source

  def test_pose_manifest_rgb_manual_override_and_resume(self):
    with tempfile.TemporaryDirectory() as folder:
      root = Path(folder)
      manual = root/'manual.png'
      correction = np.zeros((64,64), np.uint8); correction[4:9,4:9] = 255
      cv2.imwrite(str(manual), correction)
      doc, observed, model, source = self._run(root, manual=manual)
      assert doc['version'] == 2 and doc['semantic']['model']['sha256'] == _sha(model)
      assert [row['origin'] for row in doc['rows']] == ['manual', 'pose']
      assert observed['corrections'] == {1: [.15,.15,.85,.85]}
      assert tuple(observed['rgb'][0][0,0]) == tuple(_scene()[0,0,::-1])
      assert np.array_equal(cv2.imread(doc['rows'][0]['mask_path'], 0), correction)
      model.write_bytes(b'changed model')
      with self.assertRaisesRegex(ValueError, 'model changed'):
        validate_masks(root/'masks'/'manifest.json')

  def test_pose_rejects_lost_geometry_and_invalid_threshold(self):
    with tempfile.TemporaryDirectory() as folder:
      root=Path(folder)
      source, track_path, model, probe = self._fixture(root)
      with patch('video_harness.video_effects._probe', return_value=probe), \
           patch('video_harness.video_effects._verified_rate', return_value=Fraction(30)), \
           patch('video_harness.subject_mask._probe', return_value=probe), \
           patch('video_harness.subject_mask._verified_rate', return_value=Fraction(30)):
        for bad in (float('nan'), float('inf'), 0, 1, True):
          with self.assertRaisesRegex(ValueError, 'threshold'):
            prepare_masks(source, track_path, root/'masks', 'codex', 'Bad threshold',
                          backend='pose', threshold=bad)
        with self.assertRaisesRegex(ValueError, 'model path'):
          prepare_masks(source, track_path, root/'masks', 'codex', 'Wrong model',
                        backend='pose', model_path=root/'other.task')
        model.unlink()
        with self.assertRaisesRegex(ValueError, 'model changed'):
          prepare_masks(source, track_path, root/'masks', 'codex', 'Missing model', backend='pose')
      mask=np.zeros((64,64),np.uint8);mask[20:40,20:40]=255
      for bad in ({'frame': 0, 'state':'lost', 'box':None, 'mask':None},
                  {'frame': 0, 'state':'manual', 'box':[.01,.01,.10,.10], 'mask':mask}):
        with tempfile.TemporaryDirectory() as nested:
          nroot=Path(nested)
          rows=[bad, {'frame':1,'state':'manual','box':[.15,.15,.85,.85],'mask':mask}]
          with self.assertRaisesRegex(ValueError, 'lost or differs'):
            self._run(nroot, rows=rows)
          assert not (nroot/'masks').exists()

  def test_pose_schema_origin_and_manual_pixels_are_checked(self):
    with tempfile.TemporaryDirectory() as folder:
      root=Path(folder)
      doc, _, _, _=self._run(root)
      path=root/'masks'/'manifest.json'
      for change in ({'algorithm':'opencv-grabcut-rect-v1'},
                     {'semantic':{**doc['semantic'],'threshold':float('nan')}},
                     {'semantic':{**doc['semantic'],'num_poses':5}},
                     {'version':1}):
        altered={**doc, **change};path.write_text(json.dumps(altered))
        with self.assertRaises(ValueError):
          validate_masks(path)
      altered={**doc,'rows':[dict(row) for row in doc['rows']]}
      altered['rows'][0]['origin']='grabcut';path.write_text(json.dumps(altered))
      with self.assertRaisesRegex(ValueError,'row binding'):
        validate_masks(path)

  def test_pose_source_and_model_change_during_generation_fail(self):
    for changed in ('source', 'model'):
      with tempfile.TemporaryDirectory() as folder:
        root=Path(folder)
        source, track_path, model, probe=self._fixture(root)
        mask=np.zeros((64,64),np.uint8);mask[16:48,16:48]=255
        def semantic(frames, initial_box, supplied_model, fps, corrections, **kwargs):
          list(frames)
          target=source if changed=='source' else model
          target.write_bytes(target.read_bytes()+b'changed')
          return [{'frame':i,'state':'manual','box':[.15,.15,.85,.85],
                   'mask':mask,'quality':{}} for i in range(2)]
        with patch('video_harness.video_effects._probe', return_value=probe), \
             patch('video_harness.video_effects._verified_rate', return_value=Fraction(30)), \
             patch('video_harness.subject_mask._probe', return_value=probe), \
             patch('video_harness.subject_mask._verified_rate', return_value=Fraction(30)), \
             patch('video_harness.subject_mask._decode', return_value=((i,_scene()) for i in (12,13))), \
             patch('video_harness.subject_mask.version', return_value='test-mediapipe'), \
             patch('video_harness.semantic_mask.segment_frames_pose', side_effect=semantic):
          with self.assertRaisesRegex(ValueError, 'changed during generation|model changed'):
            prepare_masks(source,track_path,root/'masks','codex','Tamper probe',backend='pose')
        assert not (root/'masks').exists()
