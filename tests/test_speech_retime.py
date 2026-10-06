"""Synthetic speech timing evidence; no ASR or human listening claim."""
from copy import deepcopy
from fractions import Fraction
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from video_harness.common import fingerprint
from video_harness.cues import plan_cues
from video_harness.edl import build_plan
from video_harness.editorial import build_story_plan, make_brief
from video_harness.render_cache import digest
from video_harness.speech_retime import (prepare_speech_retime, verify_speech_setting,
                                         remap_speech_mapping, remapped_subtitles)
from video_harness.time_mapping import compile_retime


class SpeechRetimeTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.source = Path(self.temporary.name) / 'speech-base.mov'
        subprocess.run(['ffmpeg', '-v', 'error', '-nostdin', '-n', '-f', 'lavfi', '-i',
                        'color=c=gray:s=64x64:r=30:d=2', '-f', 'lavfi', '-i',
                        'sine=frequency=440:sample_rate=48000:duration=2',
                        '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-c:a', 'pcm_s16le',
                        str(self.source)], check=True)
        transcript = {'version': 1, 'source': fingerprint(self.source), 'duration': 2.,
                      'language': 'en', 'backend': {'name': 'synthetic'},
                      'words': [{'id': 'a', 'start': .2, 'end': .5, 'text': 'First', 'probability': 1.},
                                {'id': 'b', 'start': 1.2, 'end': 1.5, 'text': 'Last', 'probability': 1.}],
                      'segments': [], 'semantic_text': 'First Last', 'warnings': []}
        self.plan = build_plan({'source': str(self.source)}, transcript)
        self.mapping = {'source': fingerprint(self.source), 'keep': [[0., 2.]],
                        'duration': 2.}
        self.request = {'operations': [{'id': 'slow', 'kind': 'ramp',
                     'source_first_frame': 18, 'source_end_frame_exclusive': 30,
                     'speed_start': .5, 'speed_end': .5, 'reason': 'Observed pause'}],
                     'nonspoken_intervals': [{'first_frame': 16,
                     'end_frame_exclusive': 32, 'reason': 'Listened and observed pause'}]}

    def prepared(self):
        return prepare_speech_retime(self.source, self.plan, self.mapping,
                                     self.request, 'automation', 'Synthetic retime candidate')

    def test_source_bound_words_and_observed_operations(self):
        setting = self.prepared()
        self.assertEqual(setting['word_protection']['protected_intervals'], [[6, 15], [36, 45]])
        self.assertEqual(setting['proposal']['request']['protected_intervals'], [[6, 15], [36, 45]])
        self.assertEqual([c['id'] for c in setting['proposal']['captions']],
                         ['word:a:0', 'word:b:0'])
        self.assertEqual(verify_speech_setting(self.source, self.plan, self.mapping, setting), setting)
        self.assertIn('First', remapped_subtitles(setting))
        self.assertIn('Last', remapped_subtitles(setting))

    def test_words_and_unobserved_audio_reject_operations(self):
        for first, end, observation in [(8, 14, (7, 15)), (18, 30, (20, 30)),
                                        (18, 30, (18, 25))]:
            request = deepcopy(self.request)
            request['operations'][0]['source_first_frame'] = first
            request['operations'][0]['source_end_frame_exclusive'] = end
            request['nonspoken_intervals'][0]['first_frame'], request['nonspoken_intervals'][0]['end_frame_exclusive'] = observation
            with self.subTest(first=first, observation=observation), self.assertRaises(ValueError):
                prepare_speech_retime(self.source, self.plan, self.mapping,
                                      request, 'automation', 'Synthetic retime candidate')
        request = deepcopy(self.request)
        request['operations'] = [{'id': 'hold', 'kind': 'freeze', 'source_frame': 19,
                                  'output_frames': 4, 'reason': 'Pause'}]
        request['nonspoken_intervals'] = []
        with self.assertRaisesRegex(ValueError, 'observed'):
            prepare_speech_retime(self.source, self.plan, self.mapping,
                                  request, 'automation', 'Synthetic retime candidate')

    def test_stale_and_tampered_bindings_rejected(self):
        setting = self.prepared()
        variants = []
        tampered = deepcopy(setting)
        tampered['proposal']['mapping']['frame_map'][0] = 5
        variants.append((self.plan, self.mapping, tampered))
        tampered = deepcopy(setting)
        tampered['word_protection']['protected_intervals'] = []
        variants.append((self.plan, self.mapping, tampered))
        changed_mapping = deepcopy(self.mapping)
        changed_mapping['note'] = 'Stale mapping'
        variants.append((self.plan, changed_mapping, setting))
        changed_plan = deepcopy(self.plan)
        changed_plan['status'] = 'revised'
        variants.append((changed_plan, self.mapping, setting))
        changed_transcript = deepcopy(self.plan)
        changed_transcript['transcript']['words'][0]['text'] = 'Altered'
        variants.append((changed_transcript, self.mapping, setting))
        for plan, mapping, candidate in variants:
            with self.subTest(candidate=digest(candidate)[:8]), self.assertRaises(ValueError):
                verify_speech_setting(self.source, plan, mapping, candidate)

    def test_same_source_bytes_in_new_render_folder_verify(self):
        setting = self.prepared()
        relocated = Path(self.temporary.name) / 'next-render' / 'speech-base.mov'
        relocated.parent.mkdir()
        shutil.copyfile(self.source, relocated)
        self.assertEqual(verify_speech_setting(relocated, self.plan, self.mapping, setting), setting)
        with relocated.open('ab') as stream:
            stream.write(b'changed')
        with self.assertRaises(ValueError):
            verify_speech_setting(relocated, self.plan, self.mapping, setting)

    def test_exact_original_frame_trace_and_fractional_fps(self):
        base = {'source': fingerprint(self.source), 'keep': [[0., 1.], [1.5, 2.5]],
                'duration': 2., 'sequence_ids': ['opening', 'later'],
                'sequence': [{'id': 'opening', 'chapter_id': 'intro'},
                             {'id': 'later', 'chapter_id': 'outcome'}]}
        compiled = compile_retime(60, '30', [{'id': 'hold', 'kind': 'freeze',
            'source_frame': 29, 'output_frames': 3, 'reason': 'Observed visual pause'}])
        result = remap_speech_mapping(base, compiled)
        refs = result['retime']['frames']
        self.assertEqual((refs[29]['base_output_frame'], refs[29]['source_frame']), (29, 29))
        self.assertEqual((refs[33]['base_output_frame'], refs[33]['source_frame'],
                          refs[33]['source_span_id']), (30, 45, 'later'))
        self.assertEqual(result['frame_count'], 63)
        self.assertEqual([row['id'] for row in result['sequence']], ['opening', 'later'])
        self.assertEqual(result['sequence'][1]['source_start'], 1.5)
        self.assertEqual(result['sequence'][1]['chapter_id'], 'outcome')
        self.assertEqual(result['sequence'][1]['output_start'], 33 / 30)
        self.assertEqual(result['sequence'][-1]['output_end'], result['duration'])
        planned = plan_cues({'id': 'playful_short', 'music': 'off', 'sfx': 'off',
                             'visual_assets': 'off', 'beat_sync': 'off'}, [], result)
        self.assertEqual(planned['cues'], [])
        rate = Fraction(30000, 1001)
        fractional = {'source': base['source'], 'keep': [[0., float(30/rate)]],
                      'duration': float(30/rate)}
        mapping = compile_retime(30, '30000/1001', [])
        self.assertEqual(remap_speech_mapping(fractional, mapping)['retime']['frames'][-1]['source_frame'], 29)

    def test_repeated_word_occurrences_keep_distinct_captions_and_junction(self):
        source = Path(self.temporary.name) / 'repeated.mov'
        subprocess.run(['ffmpeg', '-v', 'error', '-nostdin', '-n', '-f', 'lavfi', '-i',
                        'color=c=gray:s=64x64:r=100:d=0.24', '-f', 'lavfi', '-i',
                        'sine=frequency=440:sample_rate=48000:duration=0.24',
                        '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-c:a', 'pcm_s16le',
                        str(source)], check=True)
        cfg = {'source': str(source), 'editorial': {'goal': 'Synthetic repeat'}}
        transcript = {'version': 1, 'source': fingerprint(source), 'duration': .4,
                      'words': [{'id': 'tiny', 'start': .08999999, 'end': .09999999,
                                 'text': 'A', 'probability': 1.},
                                {'id': 'next', 'start': .2, 'end': .3,
                                 'text': 'B', 'probability': 1.}], 'segments': []}
        spec = {'chapters': [{'id': 'one', 'goal_ids': ['goal-1'], 'spans': [
                    {'id': 's1', 'start_word_id': 'tiny', 'end_word_id': 'tiny',
                     'pad_before': .00999999, 'pad_after': .00000001, 'reason': 'Opening'},
                    {'id': 's2', 'start_word_id': 'next', 'end_word_id': 'next',
                     'pad_before': .09, 'pad_after': 0, 'reason': 'Repeat overlap'}]}],
                'omissions': []}
        plan = build_story_plan(cfg, transcript, make_brief(cfg), spec)
        mapping = {'source': fingerprint(source), 'keep': [[.08, .1], [.08, .3]],
                   'duration': .24, 'sequence_ids': ['s1', 's2']}
        setting = prepare_speech_retime(source, plan, mapping,
                                        {'operations': [], 'nonspoken_intervals': []},
                                        'automation', 'Synthetic repeated occurrence')
        self.assertEqual([c['id'] for c in setting['proposal']['captions']],
                         ['word:tiny:0', 'word:tiny:1', 'word:next:0'])
        srt = remapped_subtitles(setting)
        self.assertIn('\nA\n\n', srt)
        self.assertIn('\nA B\n\n', srt)
        self.assertEqual(setting['edit_junction_frames'], [2])

    def test_partially_retained_word_remains_in_subtitles(self):
        source = Path(self.temporary.name) / 'partial.mov'
        subprocess.run(['ffmpeg', '-v', 'error', '-nostdin', '-n', '-f', 'lavfi', '-i',
                        'color=c=gray:s=64x64:r=30', '-frames:v', '59', '-c:v', 'libx264',
                        '-pix_fmt', 'yuv420p', str(source)], check=True)
        transcript = {'version': 1, 'source': fingerprint(source), 'duration': 2.,
                      'words': [{'id': 'partial', 'start': 1.94, 'end': 1.99,
                                 'text': 'Ending', 'probability': 1.}], 'segments': []}
        plan = build_plan({'source': str(source)}, transcript)
        mapping = {'source': fingerprint(source), 'keep': [[0., 59 / 30]],
                   'duration': 59 / 30}
        setting = prepare_speech_retime(source, plan, mapping,
                                        {'operations': [], 'nonspoken_intervals': []},
                                        'automation', 'Synthetic partial word')
        self.assertTrue(setting['word_protection']['word_occurrences'][0]['partial'])
        self.assertEqual(setting['proposal']['captions'][0]['id'], 'word:partial:0')
        self.assertIn('Ending', remapped_subtitles(setting))


if __name__ == '__main__':
    unittest.main()
