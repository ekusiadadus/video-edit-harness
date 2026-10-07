"""Music trim, selected peak clocks, protected windows and sealed session recipe."""
from copy import deepcopy
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from video_harness.beat_motion import compile_beat_focus
from video_harness.beats import ANALYZER_VERSION, analyze_beats
from video_harness.common import fingerprint, read, write
from video_harness.render_cache import digest


def fixture():
    mapping = {'fps': '10', 'duration': '4/5', 'frame_count': 8, 'sequence': []}
    beat_map = {'source_sha256': 'a'*64, 'source_bytes': 10, 'analyzer_version': ANALYZER_VERSION,
                'method': 'manual_beats', 'source_start': 0, 'duration': 1,
                'beats': [.4, .6, .8], 'ambiguity': []}
    cue = {'id': 'bgm', 'role': 'music', 'asset_id': 'song', 'output_start': '0',
           'output_end': '4/5', 'source_start': '1/5', 'source_end': '1', 'loop': False}
    production = {'mapping_sha256': digest(mapping), 'pattern': {'beat_sync': 'selected'},
                  'cues': [cue], 'assets': [{'asset_id': 'song', 'kind': 'music',
                    'sha256': 'a'*64, 'bytes': 10, 'path': 'test.wav'}]}
    request = {'version': 1, 'id': 'focus', 'cue_id': 'bgm', 'beat_map': beat_map,
               'beat_indices': [1], 'window_frames': 3, 'strength': .8,
               'reduced_motion': False, 'parameters': {}, 'protected_intervals': []}
    return request, mapping, production


class BeatFocusTests(unittest.TestCase):
    def compile(self, request, mapping, production):
        with patch('video_harness.beat_motion.verify_production'), patch('video_harness.beat_motion.probe',
                return_value={'format': {'duration': '1'}}):
            return compile_beat_focus(request, mapping, production, 'Test actual music trim')

    def test_exact_peak_uses_music_trim_and_reduced_motion(self):
        req, mapping, production = fixture()
        before = deepcopy(req)
        ops, proof = self.compile(req, mapping, production)
        self.assertEqual(req, before)
        self.assertEqual([op['event']['type'] for op in ops], ['smooth_zoom', 'saturation_pulse'])
        for op in ops:
            self.assertEqual(op['event']['output_start'], '3/10')
            self.assertEqual(op['event']['output_end'], '3/5')
        self.assertEqual(proof['anchors'][0]['peak_frame'], 4)
        self.assertAlmostEqual(proof['anchors'][0]['output_time'], .4)
        reduced, proof = self.compile({**req, 'reduced_motion': True}, mapping, production)
        self.assertEqual([op['event']['type'] for op in reduced], ['saturation_pulse'])
        self.assertGreaterEqual(reduced[0]['event']['parameters']['minimum_saturation'], .95)
        self.assertFalse(proof['musical_meter_verified'])
        self.assertFalse(proof['human_listening_review'])

    def test_stale_music_windows_and_schemas_reject(self):
        req, mapping, production = fixture()
        cases = [{'version': True}, {'id': None}, {'cue_id': 'sfx'}, {'beat_indices': [True]},
                 {'beat_indices': [1, 1]}, {'beat_indices': [99]}, {'beat_indices': [0, 1]},
                 {'window_frames': 4}, {'window_frames': True}, {'window_frames': 9},
                 {'protected_intervals': [['1/2', '7/10']]},
                 {'protected_intervals': [[True, .6]]}, {'parameters': {'unknown': 1}},
                 {'beat_map': {**req['beat_map'], 'source_sha256': 'b'*64}},
                 {'beat_map': {**req['beat_map'], 'source_bytes': 11}},
                 {'beat_map': {**req['beat_map'], 'beats': [.6, .4]}},
                 {'beat_map': {**req['beat_map'], 'beats': [float('nan')]}},
                 {'beat_map': {**req['beat_map'], 'duration': 2}}]
        for changes in cases:
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.compile({**req, **changes}, mapping, production)
        with self.assertRaisesRegex(ValueError, 'mapping'):
            self.compile(req, {**mapping, 'fps': '11'}, production)
        production['cues'][0]['phase_map'] = {}
        with self.assertRaisesRegex(ValueError, 'Captured'):
            self.compile(req, mapping, production)

    def test_session_music_bytes_peak_and_recipe_survive_render(self):
        from tests.test_visual_editing import VisualEditingTests
        from video_harness.assets import register_asset
        from video_harness.session import Session
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cfg, plan = VisualEditingTests().fixture(root, source_audio=True)
            song = root/'song.wav'
            subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i',
                'sine=frequency=880:sample_rate=48000:duration=1', str(song)], check=True)
            metadata = {key: cfg['assets'][0][key] for key in ('creator','source_url','license_url',
                'acquired_on','verified_on','evidence_path','credit','cost','currency','content_id','rights')}
            cfg['assets'].append(register_asset(song, {**metadata,'asset_id':'song','kind':'music'}))
            cfg.update(edit_basis='visual',fcp_handoff='video_only')
            write(root/'project.json',cfg)
            s=Session.start(root/'project.json',root/'session');s.propose_visual(plan,'codex');s.approve('codex','Synthetic ranges')
            natural=s.render(preview=False)
            mapping=read(natural['files']['mapping']['path'])
            base=s.create_candidate({'editing_pattern':{'id':'playful_short','music':'selected','beat_sync':'selected'},
                'cue_plan':{'version':1,'mapping_sha256':digest(mapping),'cues':[
                    {'id':'bgm','asset_id':'song','role':'music','output_start':'0','output_end':'4/5',
                     'source_start':'1/5','source_end':'1','gain_db':0,'fade_in':0,'fade_out':0,
                     'duck':False,'loop':False,'reason':'Synthetic music trim'}]}},'codex','Enable requested beat accents')
            render=s.render(preview=False,candidate_id=base['id'])
            req=fixture()[0];req['beat_map']=analyze_beats(song,manual_beats=[.4,.6,.8])
            before=s._load()
            candidate=s.propose_beat_effects(render['id'],req,'codex','Selected observed synthetic beats')
            result=s.render(preview=False,candidate_id=candidate['id'])
            proof=read(result['files']['motion_template']['path'])
            self.assertEqual(proof['music_sha256'],fingerprint(song)['sha256'])
            self.assertEqual(proof['anchors'][0]['peak_frame'],4)
            self.assertEqual(result['files']['motion_template'],candidate['motion_template'])
            self.assertEqual(read(result['files']['mapping']['path']),mapping)
            def pcm(r):
                return subprocess.check_output(['ffmpeg','-v','error','-i',r['files']['video']['path'],'-vn','-f','s16le','-'])
            self.assertEqual(pcm(render),pcm(result))
            self.assertEqual(s._load()['project'],before['project'])
            self.assertEqual(s._load()['reviews'],before['reviews'])
            from video_harness.delivery import bundle
            delivery = read(bundle(result,read(result['brief']['path']),'mp4',root/'delivery',accepted=False))
            self.assertEqual(delivery['files']['motion_template']['sha256'],candidate['motion_template']['sha256'])
            saved= song.read_bytes();song.write_bytes(saved[:-100])
            with self.assertRaises(ValueError):
                s.propose_beat_effects(render['id'],req,'codex','Stale music bytes')
            song.write_bytes(saved)
            Path(candidate['motion_template']['path']).write_text('{}')
            with self.assertRaises(ValueError):s.resume()
