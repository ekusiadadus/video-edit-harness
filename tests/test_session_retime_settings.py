"""Synthetic render integration for separately reviewable setting migration."""
from pathlib import Path
import tempfile
import unittest

from tests import test_visual_editing as helpers
from video_harness.common import read, write
from video_harness.render_cache import digest
from video_harness.session import Session


class SessionRetimeSettingTests(unittest.TestCase):
    def test_static_title_fade_migration_preserves_old_alpha_and_rejects_wrong_clock(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cfg, plan = helpers.VisualEditingTests().fixture(root, source_audio=True)
            cfg.update(edit_basis='visual', fcp_handoff='video_only',
                editing_pattern={'id': 'playful_short', 'music': 'off', 'sfx': 'off',
                                 'beat_sync': 'off', 'visual_assets': 'licensed'})
            project = root/'project.json'; write(project, cfg)
            session = Session.start(project, root/'session')
            session.propose_visual(plan, 'codex'); session.approve('codex', 'Synthetic ranges')
            initial = session.render(preview=False, actor='codex')
            mapping = read(initial['files']['mapping']['path'])
            session.update_project({'cue_plan': {'version': 1, 'mapping_sha256': digest(mapping),
                'cues': [{'id': 'static', 'role': 'title', 'text': 'GO',
                          'output_start': '1/10', 'output_end': '1/2',
                          'fade_in': '1/5', 'fade_out': '1/5',
                          'reason': 'Synthetic original title fade'}]}}, 'codex', 'Bind actual mapping')
            observed = session.render(preview=False, actor='codex')
            clock = read(observed['files']['overlays']['path'])['video_cue_clocks'][0]
            before = session._load()['project']
            request = {'operations': [{'id': 'hold', 'kind': 'freeze', 'source_frame': 2,
                'output_frames': 2, 'reason': 'Synthetic hold inside fade'}]}
            proposal = session.propose_retime(observed['id'], request, 'codex', 'Keep original alpha')
            changed = read(proposal['candidate']['project']['path'])
            phase = changed['cue_plan']['cues'][0]['phase_map']
            self.assertEqual(phase['frames'], [0, 1, 1, 1, 2, 3])
            self.assertEqual(phase['original_layer'], clock['original_layer'])
            rendered = session.render(preview=False, actor='codex', candidate_id=proposal['candidate']['id'])
            self.assertEqual(read(rendered['files']['result']['path'])['technical_status'], 'pass')
            self.assertEqual(session._load()['project'], before)
            self.assertEqual(session._load()['reviews'], [])
            session._verify_render(rendered)
            wrong = changed['cue_plan']; wrong['cues'][0]['phase_map']['frames'][1] = 0
            bad = session.create_candidate({'cue_plan': wrong}, 'codex', 'Synthetic wrong frame',
                                           base_render_id=rendered['id'])
            with self.assertRaisesRegex(ValueError, 'frame selection differs'):
                session.render(preview=False, actor='codex', candidate_id=bad['id'])

    def test_video_cue_migration_uses_sealed_observed_clock(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cfg, plan = helpers.VisualEditingTests().fixture(root, source_audio=True)
            cfg.update(edit_basis='visual', fcp_handoff='video_only',
                editing_pattern={'id': 'playful_short', 'music': 'off', 'sfx': 'off',
                                 'beat_sync': 'off', 'visual_assets': 'licensed'})
            project = root/'project.json'
            write(project, cfg)
            session = Session.start(project, root/'session')
            session.propose_visual(plan, 'codex')
            session.approve('codex', 'Synthetic observed ranges')
            initial = session.render(preview=False, actor='codex')
            mapping = read(initial['files']['mapping']['path'])
            session.update_project({'cue_plan': {'version': 1, 'mapping_sha256': digest(mapping),
                'cues': [{'id': 'video', 'role': 'video', 'asset_id': 'video1',
                          'output_start': '1/5', 'output_end': '2/5',
                          'source_start': '1/10', 'source_end': '3/10', 'reason': 'Synthetic video cue'}]}},
                'codex', 'Bind video to the observed edit')
            observed = session.render(preview=False, actor='codex')
            clock = read(observed['files']['overlays']['path'])['video_cue_clocks'][0]
            before = session._load()['project']
            request = {'operations': [{'id': 'hold', 'kind': 'freeze', 'source_frame': 3,
                'output_frames': 2, 'reason': 'Synthetic frame hold'}]}
            candidate = session.propose_retime(observed['id'], request, 'codex', 'Keep video synchronized')
            changed = read(candidate['candidate']['project']['path'])
            phase = changed['cue_plan']['cues'][0]['phase_map']
            self.assertEqual(phase['version'], 2)
            self.assertEqual(phase['original_layer'], clock['original_layer'])
            self.assertEqual(phase['frames'], [0, 1, 1, 1])
            rendered = session.render(preview=False, actor='codex', candidate_id=candidate['candidate']['id'])
            self.assertEqual(read(rendered['files']['result']['path'])['technical_status'], 'pass')
            self.assertEqual(read(rendered['files']['overlays']['path'])['video_phase_layers'][0]['phase_map'], phase)
            self.assertEqual(session._load()['project'], before)
            session._verify_render(rendered)
            layer = Path(clock['original_layer']['path'])
            saved = layer.read_bytes()
            changed_layer = bytearray(saved)
            changed_layer[-1] ^= 1
            layer.write_bytes(changed_layer)
            with self.assertRaises(ValueError):
                session._verify_render(rendered)
            with self.assertRaises(ValueError):
                session.propose_retime(observed['id'], request, 'codex', 'Reject changed layer')
            layer.write_bytes(saved)
            with Path(observed['files']['overlays']['path']).open('a') as stream:
                stream.write('changed')
            with self.assertRaises(ValueError):
                session.propose_retime(observed['id'], request, 'codex', 'Reject changed clock')

    def test_default_migration_renders_exact_mapping_without_adopting(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cfg, plan = helpers.VisualEditingTests().fixture(root, source_audio=True)
            cfg.update(edit_basis='visual', fcp_handoff='video_only',
                editing_pattern={'id': 'playful_short', 'music': 'off', 'sfx': 'off',
                                 'beat_sync': 'off', 'visual_assets': 'own_only'})
            project = root / 'project.json'
            write(project, cfg)
            session = Session.start(project, root / 'session')
            session.propose_visual(plan, 'codex')
            session.approve('codex', 'Synthetic selected ranges')
            initial = session.render(preview=False, actor='codex')
            mapping = read(initial['files']['mapping']['path'])
            bounds = {'output_start': '1/5', 'output_end': '2/5', 'reason': 'Synthetic emphasis'}
            session.update_project({
                'cue_plan': {'version': 1, 'mapping_sha256': digest(mapping),
                    'cues': [{'id': 'label', 'role': 'title', 'text': 'X', **bounds}]},
                'video_effects': {'version': 1, 'mapping_sha256': digest(mapping),
                    'events': [{'id': 'accent', 'type': 'monochrome', 'strength': .5, **bounds}]},
                'composition_guides': [{'id': 'ui', 'kind': 'ui', 'rect': [.8, .8, 1, 1], **bounds}],
            }, 'codex', 'Bind settings to observed fixture mapping')
            observed = session.render(preview=False, actor='codex')
            before = session._load()['project']
            request = {'operations': [{'id': 'hold', 'kind': 'freeze', 'source_frame': 3,
                'output_frames': 2, 'reason': 'Synthetic frame hold'}]}
            migrated = session.propose_retime(observed['id'], request, 'codex', 'Preserve placed accents')
            self.assertEqual(migrated['timeline_settings_mode'], 'migrate')
            self.assertEqual(migrated['invalidated_timeline_settings'], [])
            self.assertEqual(session._load()['project'], before)
            changed = read(migrated['candidate']['project']['path'])
            for row in (changed['cue_plan']['cues'][0], changed['video_effects']['events'][0],
                        changed['composition_guides'][0]):
                self.assertEqual((row['output_start'], row['output_end']), ('1/5', '3/5'))
            rendered = session.render(preview=False, actor='codex', candidate_id=migrated['candidate']['id'])
            actual = read(rendered['files']['mapping']['path'])
            self.assertEqual(digest(actual), migrated['migration']['new_mapping_sha256'])
            self.assertEqual(read(rendered['files']['result']['path'])['technical_status'], 'pass')
            self.assertEqual(session._load()['project'], before)
            cleared = session.propose_retime(observed['id'], request, 'codex', 'Explicitly rebuild accents',
                                             timeline_settings='clear')
            self.assertEqual(set(cleared['invalidated_timeline_settings']),
                             {'cue_plan', 'video_effects', 'composition_guides'})
            self.assertIsNone(read(cleared['candidate']['project']['path'])['cue_plan'])
            migration_ref = migrated['candidate']['retime_settings_migration']
            with Path(migration_ref['path']).open('a') as stream:
                stream.write('changed')
            with self.assertRaises(ValueError):
                session._verify(session._load())
