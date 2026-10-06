"""Recipe provenance remains sealed and proposals never adopt themselves."""
import unittest

from pathlib import Path
import tempfile
from tests import test_visual_editing as helpers
from video_harness.common import read, write
from video_harness.session import Session


class SessionMotionTemplateTests(unittest.TestCase):
    def test_recipe_preserves_base_settings_and_sealed_provenance(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        cfg, plan = helpers.VisualEditingTests().fixture(root, source_audio=True)
        cfg.update(edit_basis='visual', editing_pattern={'id': 'playful_short',
                   'music': 'off', 'sfx': 'off', 'beat_sync': 'off'}, fcp_handoff='video_only')
        write(root/'project.json', cfg)
        session = Session.start(root/'project.json', root/'session')
        session.propose_visual(plan, 'automation')
        session.approve('automation', 'Synthetic frame selection')
        original = session._load()['project']
        base_audio = {**cfg['audio'], 'target_lufs': -18}
        base = session.create_candidate({'editing_pattern': {'id': 'playful_short'},
                                         'audio': base_audio}, 'codex', 'Base')
        render = session.render(preview=False, actor='automation', candidate_id=base['id'])
        request = {'version': 1, 'id': 'accent', 'template': 'beat_focus',
                   'output_start': '0', 'output_end': '3/5', 'strength': .5,
                   'reason': 'Observed emphasis', 'reduced_motion': False, 'parameters': {}}
        candidate = session.propose_motion_template(render['id'], request, 'codex', 'Compare recipe')
        cfg = read(candidate['project']['path'])
        self.assertEqual(cfg['audio'], base_audio)
        self.assertEqual({e['type'] for e in cfg['video_effects']['events']},
                         {'smooth_zoom', 'saturation_pulse'})
        evidence = read(candidate['motion_template']['path'])
        self.assertEqual(evidence['request'], request)
        self.assertEqual(evidence['video'], render['files']['video'])
        self.assertEqual(session._load()['project'], original)
        self.assertEqual(session._load()['reviews'], [])
        rendered = session.render(preview=False, actor='automation', candidate_id=candidate['id'])
        self.assertEqual(read(Path(rendered['path'])/'result.json')['technical_status'], 'pass')
        applied = read(Path(rendered['path'])/'effects-evidence.json')
        self.assertEqual(applied['frame_count'], 8)
        reduced_request = {**request, 'reduced_motion': True}
        reduced = session.propose_motion_template(render['id'], reduced_request, 'codex', 'Reduced comparison')
        reduced_cfg = read(reduced['project']['path'])
        self.assertEqual([e['type'] for e in reduced_cfg['video_effects']['events']], ['saturation_pulse'])
        reduced_render = session.render(preview=False, actor='automation', candidate_id=reduced['id'])
        natural = session.create_candidate({'editing_pattern': {'id': 'natural'}},
                    'automation', 'Same base audio natural comparison', base_render_id=render['id'])
        natural_render = session.render(preview=False, actor='automation', candidate_id=natural['id'])
        comparison = session.compare_candidates([natural_render['id'], rendered['id'], reduced_render['id']])
        self.assertTrue(comparison)
        import subprocess
        pcm = []
        for item in (natural_render, rendered, reduced_render):
            pcm.append(subprocess.check_output(['ffmpeg', '-v', 'error', '-i',
                       item['files']['video']['path'], '-map', '0:a:0', '-f', 's16le', '-']))
        self.assertEqual(pcm[0], pcm[1])
        self.assertEqual(pcm[0], pcm[2])
        self.assertEqual(rendered['files']['motion_template'], candidate['motion_template'])
        self.assertEqual(session._load()['project'], original)
        self.assertEqual(session._load()['reviews'], [])
        session.adopt_candidate(candidate['id'], 'automation', 'Synthetic adoption; no human review')
        final = session.render(preview=False, actor='automation')
        self.assertEqual(final['files']['motion_template'], candidate['motion_template'])
        from video_harness.delivery import bundle
        delivery = read(bundle(final, read(final['brief']['path']), 'mp4', root/'delivery', accepted=False))
        self.assertEqual(delivery['files']['motion_template']['sha256'], candidate['motion_template']['sha256'])
        restored = session.candidate_from_selection({
            'version': 1, 'kind': 'comparison_selection_proposal',
            'render_id': rendered['id'], 'render_sha256': rendered['files']['video']['sha256'],
            'output_time': .2, 'note': 'Synthetic selected recipe',
            'adopted': False, 'final_review': False}, 'automation', 'Restore recipe provenance')
        self.assertEqual(restored['motion_template'], candidate['motion_template'])
        self.assertEqual(session._load()['project'], candidate['project'])
        self.assertEqual(session._load()['reviews'], [])
        with self.assertRaisesRegex(ValueError, 'natural/off'):
            session.propose_motion_template(natural_render['id'], request, 'codex', 'Conflicting request')
        with self.assertRaisesRegex(ValueError, 'Duplicate effect id'):
            from video_harness.video_effects import revise_effects
            revise_effects(cfg['video_effects'], read(render['files']['mapping']['path']),
                           evidence['operations'])
        Path(candidate['motion_template']['path']).write_text('{}')
        with self.assertRaises(ValueError):
            session.resume()
