"""First session retime keeps actual original temporal-stage samples."""
from pathlib import Path
import tempfile
import subprocess
import unittest
import numpy as np

from tests import test_visual_editing as helpers
from tests.test_temporal_effect_samples import pixels
from video_harness.common import read, write
from video_harness.session import Session


class TemporalEffectRetimeSessionTests(unittest.TestCase):
    def test_first_retime_replays_original_samples_without_adoption(self):
        for kind in ('motion_trail', 'comparison_wipe'):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                cfg, plan = helpers.VisualEditingTests().fixture(root, source_audio=True)
                source = Path(cfg['assets'][0]['path'])
                pictures = []
                for i in range(10):
                    frame = np.zeros((128, 128, 3), np.uint8)
                    frame[:, i*10:i*10+10] = 255
                    pictures.append(frame)
                subprocess.run(['ffmpeg', '-v', 'error', '-y', '-f', 'rawvideo',
                    '-pixel_format', 'rgb24', '-video_size', '128x128', '-framerate', '10',
                    '-i', 'pipe:0', '-f', 'lavfi', '-i', 'sine=frequency=440:sample_rate=48000:duration=1',
                    '-c:v', 'libx264', '-crf', '0', '-pix_fmt', 'yuv420p', '-c:a', 'aac', str(source)],
                    input=b''.join(frame.tobytes() for frame in pictures), check=True, capture_output=True)
                from video_harness.assets import register_asset, _META
                cfg['assets'][0] = register_asset(source, {key: value for key, value in cfg['assets'][0].items() if key in _META})
                cfg.update(edit_basis='visual', fcp_handoff='video_only',
                    editing_pattern={'id': 'playful_short', 'music': 'off', 'sfx': 'off',
                                     'beat_sync': 'off', 'visual_assets': 'licensed'})
                project = root/'project.json'; write(project, cfg)
                session = Session.start(project, root/'session')
                session.propose_visual(plan, 'codex'); session.approve('codex', 'Synthetic selected ranges')
                initial = session.render(preview=False, actor='codex')
                event = {'id': 'history', 'type': kind, 'output_start': '0', 'output_end': '3/10',
                         'strength': .7, 'reason': 'Synthetic bounded temporal effect'}
                if kind == 'comparison_wipe':
                    event['parameters'] = {'asset_id': 'video1', 'source_start': .1, 'layout': 'side_by_side'}
                candidate = session.propose_effects(initial['id'], [{'action': 'add', 'event': event}],
                                                    'codex', 'Create synthetic original effect')
                original = session.render(preview=False, actor='codex', candidate_id=candidate['id'])
                evidence = read(original['files']['effects']['path'])
                sample = evidence['temporal_effect_samples'][0]
                before = session._load()['project']
                request = {'operations': [{'id': 'hold', 'kind': 'freeze', 'source_frame': 2,
                    'output_frames': 2, 'reason': 'Synthetic hold inside temporal event'}]}
                proposed = session.propose_retime(original['id'], request, 'codex', 'Preserve actual stage pixels')
                changed = read(proposed['candidate']['project']['path'])
                event_map = changed['video_effects']['events'][0]['content_map']
                self.assertEqual(event_map['original_sample'], sample)
                self.assertEqual(event_map['frames'], [0, 1, 2, 2, 2])
                rendered = session.render(preview=False, actor='codex', candidate_id=proposed['candidate']['id'])
                self.assertEqual(read(rendered['files']['result']['path'])['technical_status'], 'pass')
                self.assertEqual(session._load()['project'], before)
                self.assertEqual(session._load()['reviews'], [])
                session._verify_render(rendered)
                # Moving bars make wrong history or a restarted comparison visibly different.
                old = pixels(sample['original_layer']['path'], 128, 128)
                picture = pixels(Path(rendered['path'])/'visual-effects.mp4', 128, 128)
                expected = old[event_map['frames']]
                self.assertEqual(len(picture), 10)
                self.assertLess(np.abs(picture[:5].astype(float)-expected.astype(float)).mean(), 8)
                self.assertEqual(rendered['files']['temporal_replay_original_0']['sha256'],
                                 sample['original_layer']['sha256'])
                wrong = read(proposed['candidate']['project']['path'])['video_effects']
                wrong['events'][0]['content_map']['frames'][2] = 1
                stale_selection = session.create_candidate({'video_effects': wrong}, 'codex',
                    'Synthetic mismatched frame selection', base_render_id=rendered['id'])
                with self.assertRaisesRegex(ValueError, 'frame selection differs'):
                    session.render(preview=False, actor='codex', candidate_id=stale_selection['id'])
                # Clear the failed operation using the normal verified recovery route.
                session.resume('codex')
                # Changing the grade after migration must not silently keep old baked pixels.
                stale = session.create_candidate({'style': 'warm_documentary'}, 'codex',
                    'Synthetic stale picture binding', base_render_id=rendered['id'])
                with self.assertRaisesRegex(ValueError, 'picture|binding|changed'):
                    session.render(preview=False, actor='codex', candidate_id=stale['id'])
