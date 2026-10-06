"""Partial effect graphs keep parent phase/history and cannot masquerade as full renders."""
from fractions import Fraction
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from tests.test_video_effects import fixture, digest, pcm_hash
from video_harness.video_effects import render_effects, resolve_effects
from video_harness.effect_preview import _excerpt


class EffectWindowTests(unittest.TestCase):
    def test_window_preserves_trail_history_pulse_phase_and_finished_audio(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); source = root/'source.mp4'; fixture(source)
            mapping = {'fps': '10', 'duration': '6/5', 'sequence': []}
            events = [
                {'id':'trail', 'type':'motion_trail', 'output_start':'1/5', 'output_end':'1',
                 'strength':.7, 'reason':'Observed synthetic history', 'parameters':{'history_frames':4}},
                {'id':'pulse', 'type':'saturation_pulse', 'output_start':'1/5', 'output_end':'1',
                 'strength':.8, 'reason':'Observed synthetic phase', 'parameters':{'minimum_saturation':0}}]
            plan = resolve_effects({'version':1,'mapping_sha256':digest(mapping),'events':events},mapping)
            # Lossless encoding isolates the filter/frame-clock contract from
            # normal CRF differences caused by a new excerpt GOP boundary.
            real_run = subprocess.run
            def lossless(command, *args, **kwargs):
                command = list(command)
                if '-crf' in command:
                    index = command.index('-crf'); command[index:index+2] = ['-qp','0']
                return real_run(command,*args,**kwargs)
            with patch('video_harness.video_effects.subprocess.run', side_effect=lossless):
                render_effects(source,plan,root/'full.mp4',capture_temporal_samples=False)
                report = render_effects(source,plan,root/'window.mp4',capture_temporal_samples=False,
                                        output_window=(5,9),audio_source=root/'full.mp4')
            def pixels(path):
                return subprocess.check_output(['ffmpeg','-v','error','-i',str(path),'-an',
                    '-pix_fmt','rgb24','-f','rawvideo','-'])
            full = pixels(root/'full.mp4'); window = pixels(root/'window.mp4'); stride = len(full)//12
            self.assertEqual(window,full[5*stride:9*stride])
            self.assertEqual(report['frame_count'],4)
            self.assertEqual(report['duration'],.4)
            self.assertEqual(report['output_window']['parent_frame_count'],12)
            self.assertEqual(report['temporal_effect_samples'],[])
            _excerpt(root/'full.mp4',root/'audio-reference.mp4',5,9,Fraction(10),root/'excerpt.log')
            self.assertEqual(pcm_hash(root/'window.mp4'),pcm_hash(root/'audio-reference.mp4'))
            empty = resolve_effects(None,mapping)
            off = render_effects(source,empty,root/'off.mp4',capture_temporal_samples=False,
                                 output_window=(11,12),audio_source=root/'full.mp4')
            self.assertEqual(off['frame_count'],1)
            for bounds in ((True,2),(-1,2),(2,2),(0,13)):
                with self.assertRaises(ValueError):
                    render_effects(source,plan,root/'bad.mp4',capture_temporal_samples=False,
                                   output_window=bounds)
            with self.assertRaisesRegex(ValueError,'capture'):
                render_effects(source,plan,root/'capture.mp4',output_window=(5,9))

    def test_fractional_fps_final_frame_keeps_audio_coverage(self):
        from video_harness.effect_preview import _check_excerpt
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp); source=root/'fractional.mp4'; output=root/'last.mp4'
            rate=Fraction(30000,1001)
            subprocess.run(['ffmpeg','-v','error','-nostdin','-n','-f','lavfi','-i',
                'testsrc2=s=160x90:r=30000/1001:d=0.4004','-f','lavfi','-i',
                'sine=frequency=440:sample_rate=48000:duration=0.4004',
                '-c:v','libx264','-pix_fmt','yuv420p','-c:a','aac',str(source)],check=True,capture_output=True)
            mapping={'fps':str(rate),'duration':str(Fraction(12,1)/rate),'sequence':[]}
            report=render_effects(source,resolve_effects(None,mapping),output,
                capture_temporal_samples=False,output_window=(11,12))
            self.assertEqual(report['frame_count'],1)
            self.assertEqual(report['fps'],str(rate))
            _check_excerpt(output,1,rate,(160,90),root/'decode.log')
