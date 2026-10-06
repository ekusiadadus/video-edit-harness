"""Actual synthetic local rendering, not human acceptance or platform playback."""
from copy import deepcopy
from pathlib import Path
import subprocess
import tempfile
import unittest

from tests import test_visual_editing as helpers
from video_harness.assets import register_asset
from video_harness.common import fingerprint, read, write
from video_harness.session import Session
from video_harness.transitions import prepare_transitions


def request(kind='push'):
    event = {'id': 'move', 'left_segment_id': 'first', 'before_frames': 2,
             'after_frames': 2, 'type': kind, 'reason': 'Synthetic requested picture overlap'}
    if kind == 'push':
        event['direction'] = 'left'
    return {'version': 1, 'events': [event]}


class SessionTransitionTests(unittest.TestCase):
    def fixture(self, root):
        cfg, plan = helpers.VisualEditingTests().fixture(root, source_audio=True)
        red = root/'red.mp4'
        subprocess.run(['ffmpeg', '-v', 'error', '-n', '-f', 'lavfi', '-i',
                        'color=c=red:s=128x128:r=10:d=1', '-c:v', 'libx264',
                        '-pix_fmt', 'yuv420p', str(red)], check=True)
        old = cfg['assets'][0]
        metadata = {key: old[key] for key in ('asset_id','kind','creator','source_url','license_url',
            'acquired_on','verified_on','evidence_path','credit','rights','cost','currency','content_id')}
        metadata['asset_id'] = 'red'
        cfg['assets'].append(register_asset(red, metadata))
        cfg.update(edit_basis='visual', editing_pattern={'id': 'gentle_vlog', 'intensity': 'low'},
                   fcp_handoff='video_only')
        plan['sequence'][1]['asset_id'] = 'red'
        project = root/'project.json'; write(project, cfg)
        session = Session.start(project, root/'session')
        session.propose_visual(plan, 'automation')
        session.approve('automation', 'Synthetic source-frame selection')
        return session

    def test_candidate_composite_feedback_review_comparison_and_natural_reset(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); session = self.fixture(root)
            base = session.render(preview=False, actor='automation')
            state = deepcopy(session._load())
            natural = session.create_candidate({'editing_pattern': {'id': 'natural'}},
                                                'automation', 'Synthetic natural baseline')
            baseline = session.render(preview=False, actor='automation', candidate_id=natural['id'])
            proposed = session.propose_transitions(base['id'], request(), 'automation', 'Synthetic push candidate')
            self.assertFalse(proposed['adopted'])
            rendered = session.render(preview=False, actor='automation', candidate_id=proposed['candidate']['id'])
            self.assertEqual(session._load()['project'], state['project'])
            self.assertEqual(session._load()['reviews'], [])
            mapping = read(rendered['files']['mapping']['path'])
            self.assertEqual(mapping['frame_count'], 8)
            self.assertEqual(mapping['sequence'], read(base['files']['mapping']['path'])['sequence'])
            compiled = read(rendered['files']['transitions']['path'])['compiled']
            self.assertEqual(compiled, mapping['transitions']['compiled'])
            pipeline = read(Path(rendered['path'])/'visual-pipeline.json')
            self.assertTrue(pipeline['grade_input']['path'].endswith('visual-transitioned.mp4'))
            feedback = session.add_feedback(rendered['id'], .3, .5, 'comment',
                                            'Synthetic composite provenance', 'automation')
            self.assertEqual({r['asset_id'] for r in feedback['source_spans']}, {'video1', 'red'})
            session.dismiss_feedback(feedback['id'], 'automation', 'Synthetic test only')
            inspection = read(session.inspect(rendered['id'], .3, .3)['path'])
            self.assertIn('audio_source_spans', inspection)
            self.assertIn('frame_correspondence', inspection)
            self.assertNotIn('side', inspection['audio_source_spans'][0])
            comparison = session.compare_candidates([baseline['id'], rendered['id']])
            evidence = read(comparison['evidence']['path'])
            self.assertEqual(evidence['candidates'][1]['transitions'], request()['events'])
            self.assertNotEqual(evidence['candidates'][0]['output_mapping_sha256'],
                                evidence['candidates'][1]['output_mapping_sha256'])
            names = ['meaning','pacing','cut_boundaries','color','audio_only','asset_rights']
            report = {'render_sha256': rendered['files']['video']['sha256'],
                      'checks': [{'id': name, 'status': 'pass', 'basis': 'synthetic',
                                  'note': 'Synthetic fixture, no human acceptance'} for name in names]}
            with self.assertRaisesRegex(ValueError, 'transitions'):
                session.review(rendered['id'], report, 'automation')
            report['checks'].append({'id': 'transitions', 'status': 'pass', 'basis': 'synthetic',
                                     'note': 'Synthetic transition render validation'})
            self.assertTrue(session.review(rendered['id'], report, 'automation')['passed'])
            session.adopt_candidate(proposed['candidate']['id'], 'automation', 'Synthetic explicit selection')
            delivery = session.package(rendered['id'], target='mp4', actor='automation')
            manifest = read(delivery['artifact']['path'])
            self.assertIn('transitions', manifest['files'])
            self.assertIn('pre_transition_mapping', manifest['files'])
            self.assertEqual(manifest['files']['video']['sha256'], rendered['files']['video']['sha256'])
            completion = session.finish(delivery['id'], actor='automation')
            self.assertEqual(completion['status'], 'synthetic_complete')
            reset = session.create_candidate({'editing_pattern': {'id': 'natural'}},
                                              'automation', 'Synthetic removal of all transitions')
            self.assertNotIn('transitions', read(reset['project']['path']))
            with self.assertRaisesRegex(ValueError, 'natural/off'):
                session.create_candidate({'editing_pattern': {'id': 'natural'},
                                          'transitions': read(proposed['candidate']['project']['path'])['transitions']},
                                         'automation', 'Synthetic conflicting request')

    def test_preparation_rejects_rights_stale_source_base_and_conflicts(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); session = self.fixture(root)
            base = session.render(preview=False, actor='automation')
            cfg = read(base['project']['path']); mapping = read(base['files']['mapping']['path'])
            assembly = Path(base['path'])/'visual-base.mp4'
            for changes, error in [({'retime': {'version': 1}}, 'without retime'),
                                   ({'audio_cuts': {}}, 'without retime'),
                                   ({'input_color': 'apple_log'}, 'Rec.709'),
                                   ({'fcp_handoff': 'editable'}, 'baked'),
                                   ({'editing_pattern': {'id': 'natural'}, '_editing_pattern_snapshot': None}, 'natural/off')]:
                with self.assertRaisesRegex(ValueError, error):
                    prepare_transitions(assembly, mapping, {**cfg, **changes}, request(),
                                        'automation', 'Synthetic rejection case')
            denied = deepcopy(cfg); denied['assets'][0]['rights']['modification'] = False
            with self.assertRaises(ValueError):
                prepare_transitions(assembly, mapping, denied, request(), 'automation', 'Synthetic denied right')
            denied = deepcopy(cfg); denied['assets'][0]['sha256'] = 'f'*64
            with self.assertRaises(ValueError):
                prepare_transitions(assembly, mapping, denied, request(), 'automation', 'Synthetic changed source')
            short = root/'short.mp4'
            subprocess.run(['ffmpeg','-v','error','-n','-i',str(assembly),'-frames:v','2',
                            '-an',str(short)],check=True)
            with self.assertRaisesRegex(ValueError, 'frame count/FPS'):
                prepare_transitions(short,mapping,cfg,request(),'automation','Synthetic wrong base')


if __name__ == '__main__':
    unittest.main()
