"""No-ASR beat cut proposals grounded in actual source frames."""
from copy import deepcopy
from fractions import Fraction
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from video_harness.beat_editing import suggest_beat_revision, annotate_speech_beats
from video_harness.common import fingerprint
from video_harness.render_cache import digest
from video_harness.visual import validate_visual_edl


@unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'FFmpeg required')
class BeatEditingTests(unittest.TestCase):
    def fixture(self, root, fps=(10, 15, 10), lengths=(2, 2, 2)):
        assets = []
        for index, (rate, length) in enumerate(zip(fps, lengths), 1):
            path = root / f'source-{index}.mp4'
            subprocess.run(['ffmpeg', '-v', 'error', '-nostdin', '-n', '-f', 'lavfi',
                            '-i', f'color=c=blue:s=64x64:r={rate}:d={length}',
                            '-c:v', 'libx264', '-pix_fmt', 'yuv420p', str(path)], check=True)
            assets.append({'asset_id': f'asset-{index}', 'kind': 'video', **fingerprint(path)})
        edl = {'version': 4, 'edit_basis': 'visual', 'status': 'reviewed_selection',
               'review': {'actor': 'codex', 'reason': 'Original visual spans reviewed',
                          'basis': 'source_inspection'},
               'sequence': [{'id': f'shot-{index}', 'asset_id': f'asset-{index}',
                             'source_start': 0, 'source_end': 1,
                             'reason': 'Actual generated frames'} for index in range(1, 4)]}
        normalized = validate_visual_edl(edl, assets)
        rows = []
        for index, segment in enumerate(normalized['sequence']):
            rows.append({'id': segment['id'], 'asset_id': segment['asset_id'],
                         'source_sha256': assets[index]['sha256'],
                         'source_first_frame': segment['source_first_frame'],
                         'source_end_frame_exclusive': segment['source_end_frame_exclusive'],
                         'source_fps': segment['source_fps'],
                         'output_first_frame': index * 10,
                         'output_end_frame_exclusive': (index + 1) * 10})
        mapping = {'edit_basis': 'visual', 'fps': '10', 'duration': 3.,
                   'frame_count': 30, 'sequence': rows}
        beats = {'fps': '10', 'source_sha256': assets[0]['sha256'], 'beats': [
            {'frame': 12, 'frame_time': 1.2, 'cut_eligible': True,
             'protected_speech': False, 'loop_seam_nearby': False},
            {'frame': 18, 'frame_time': 1.8, 'cut_eligible': True,
             'protected_speech': False, 'loop_seam_nearby': False}],
            'protected_intervals': []}
        return normalized, mapping, beats, assets

    def test_global_hold_chooses_later_beat_and_quantizes_unequal_fps(self):
        with tempfile.TemporaryDirectory() as temp:
            plan, mapping, beats, assets = self.fixture(Path(temp))
            original = deepcopy(plan)
            revision, evidence = suggest_beat_revision(plan, mapping, beats, assets,
                max_shift=.3, min_hold=.8, allowed_intervals=[(.7, 1.3), (1.7, 2.3)],
                actor='codex', reason='Propose safe visual beat alignment')
            self.assertEqual([c['suggested_frame'] for c in evidence['cuts']], [10, 18])
            self.assertEqual(revision['sequence'][1]['source_end_frame_exclusive'], 12)
            self.assertEqual(revision['sequence'][1]['source_end'], '4/5')
            self.assertEqual(revision['status'], 'proposed')
            self.assertNotIn('review', revision)
            self.assertEqual(plan, original)
            self.assertEqual(evidence['plan_sha256'], digest(plan))
            self.assertEqual(evidence['mapping_sha256'], digest(mapping))
            self.assertEqual(evidence['beatmap_sha256'], digest(beats))
            self.assertEqual(validate_visual_edl(revision, assets)['sequence'][1]['source_end'], '4/5')

    def test_no_nonspoken_permission_or_protected_beat_keeps_cut(self):
        with tempfile.TemporaryDirectory() as temp:
            plan, mapping, beats, assets = self.fixture(Path(temp))
            with self.assertRaisesRegex(ValueError, 'allowed_intervals'):
                suggest_beat_revision(plan, mapping, beats, assets, .3, .8, [], 'codex', 'test')
            beats['beats'][0]['protected_speech'] = True
            beats['beats'][1]['protected_speech'] = True
            revision, evidence = suggest_beat_revision(plan, mapping, beats, assets,
                .3, .8, [(.7, 1.3), (1.7, 2.3)], 'codex', 'No safe beat')
            self.assertEqual([c['suggested_frame'] for c in evidence['cuts']], [10, 20])
            self.assertEqual([s['source_end'] for s in revision['sequence']],
                             [s['source_end'] for s in plan['sequence']])
            beats['beats'][0]['protected_speech'] = False
            beats['protected_intervals'] = [[1.05, 1.15]]
            _, evidence = suggest_beat_revision(plan, mapping, beats, assets,
                .3, .8, [(.7, 1.3), (1.7, 2.3)], 'codex', 'Respect protected interval')
            self.assertEqual(evidence['cuts'][0]['suggested_frame'], 10)

    def test_stale_mapping_and_speech_plan_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            plan, mapping, beats, assets = self.fixture(Path(temp))
            mapping['sequence'][0]['source_sha256'] = '0' * 64
            with self.assertRaisesRegex(ValueError, 'mapping'):
                suggest_beat_revision(plan, mapping, beats, assets, .3, .8,
                                      [(.7, 1.3)], 'codex', 'Invalid source')
            speech = {'version': 3, 'sequence': [{'id': 'word-bound'}]}
            with self.assertRaisesRegex(ValueError, 'speech plans'):
                suggest_beat_revision(speech, mapping, beats, assets, .3, .8,
                                      [(.7, 1.3)], 'codex', 'Do not cut speech')
            before = deepcopy(speech)
            marks = annotate_speech_beats(speech, beats)
            self.assertFalse(marks['timing_changed'])
            self.assertEqual(speech, before)

    def test_frame_limit_prevents_extension(self):
        with tempfile.TemporaryDirectory() as temp:
            plan, mapping, beats, assets = self.fixture(Path(temp), lengths=(1, 2, 2))
            beats['beats'] = [beats['beats'][0]]
            revision, evidence = suggest_beat_revision(plan, mapping, beats, assets,
                .3, .8, [(.7, 1.3), (1.7, 2.3)], 'codex', 'Bounded by source')
            self.assertEqual(evidence['cuts'][0]['suggested_frame'], 10)
            self.assertEqual(revision['sequence'][0]['source_end_frame_exclusive'], 10)


if __name__ == '__main__':
    unittest.main()
