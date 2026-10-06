"""Effects require exact mapping and actually alter picture, not audio timing."""
from __future__ import annotations

from fractions import Fraction
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image, ImageChops, ImageStat
from video_harness.video_effects import resolve_effects, render_effects, _verified_rate, revise_effects


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                     separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def fixture(path):
    subprocess.run(['ffmpeg', '-v', 'error', '-nostdin', '-y',
                    '-f', 'lavfi', '-i', 'testsrc2=s=160x90:r=10:d=1.2',
                    '-f', 'lavfi', '-i', 'sine=frequency=440:sample_rate=48000:duration=1.2',
                    '-c:v', 'libx264', '-pix_fmt', 'yuv420p',
                    '-c:a', 'aac', '-shortest', str(path)],
                   check=True, capture_output=True)


def frame(path, index, out):
    subprocess.run(['ffmpeg', '-v', 'error', '-nostdin', '-y', '-i', str(path),
                    '-vf', f'select=eq(n\\,{index})', '-frames:v', '1', str(out)],
                   check=True, capture_output=True)
    return Image.open(out).convert('RGB')


def pcm_hash(path):
    decoded = subprocess.check_output(['ffmpeg', '-v', 'error', '-i', str(path),
                                       '-map', '0:a:0', '-f', 's16le', '-acodec', 'pcm_s16le', '-'])
    return hashlib.sha256(decoded).hexdigest()


class EffectsTest(unittest.TestCase):
    def test_wrapped_title_render_keeps_audio_and_refuses_changed_engine_binding(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);source=root/'source.mp4';output=root/'wrapped.mp4'
            fixture(source)
            mapping={'fps':'10','duration':'6/5','sequence':[]}
            event={'id':'wrapped','type':'keyword_title','effect_version':2,
                   'output_start':'1/5','output_end':'1','strength':1,'reason':'Measured two-line title',
                   'parameters':{'text':'Modern dance rhythm','language':'en',
                                 'max_width_fraction':.65,'font_size_fraction':.12}}
            plan=resolve_effects({'version':1,'mapping_sha256':digest(mapping),'events':[event]},mapping)
            report=render_effects(source,plan,output)
            self.assertEqual(pcm_hash(source),pcm_hash(output))
            self.assertEqual(report['frame_count'],12)
            self.assertGreater(len(report['text_assets'][0]['rendered_lines']),1)
            bounds=report['text_assets'][0]['bounds']
            crop=tuple(round(v*s) for v,s in zip(bounds,(160,90,160,90)))
            before=frame(source,5,root/'before-wrap.png');after=frame(output,5,root/'after-wrap.png')
            self.assertGreater(sum(ImageStat.Stat(ImageChops.difference(before.crop(crop),after.crop(crop))).mean),20)
            broken=json.loads(json.dumps(plan));broken['events'][0]['layout_binding']['model_sha256']='0'*64
            with self.assertRaisesRegex(ValueError,'layout engine/model binding'):
                render_effects(source,broken,root/'changed.mp4')

    def test_tracked_zoom_renders_exact_valid_rows_and_rejects_stale_or_lost(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);source=root/'source.mp4';output=root/'tracked.mp4';track=root/'track.json'
            fixture(source)
            doc={'version':1,'algorithm':'lk-affine-v1','source':{'path':str(source),'sha256':hashlib.sha256(source.read_bytes()).hexdigest(),'bytes':source.stat().st_size},
                 'fps':'10','start_frame':0,'end_frame_exclusive':12,'review_required':True,
                 'rows':[{'frame':i,'box':[.1+i*.02,.2,.3+i*.02,.5],'state':'manual','quality':{'feature_count':10}} for i in range(12)]}
            track.write_text(json.dumps(doc))
            mapping={'fps':'10','duration':'6/5','sequence':[]}
            event={'id':'follow','type':'tracked_zoom','output_start':'1/5','output_end':'1',
                   'strength':1,'reason':'Synthetic renderer test','parameters':{'track_path':str(track),'max_scale':1.5}}
            setting={'version':1,'mapping_sha256':digest(mapping),'events':[event]}
            plan=resolve_effects(setting,mapping)
            from video_harness.composition import resolve_guides
            guide={'id':'torso','kind':'subject','track_path':str(track),'output_start':'1/5',
                   'output_end':'1','reason':'Protect the observed fixture box'}
            composition=resolve_guides([guide],mapping)
            report=render_effects(source,plan,output,composition=composition)
            self.assertEqual(report['frame_count'],12)
            self.assertEqual(pcm_hash(source),pcm_hash(output))
            self.assertEqual(report['tracking_inputs'][0]['sha256'],plan['events'][0]['parameters']['track_sha256'])
            self.assertEqual(report['composition']['checks'][0]['frames_checked'],8)
            wrong=json.loads(json.dumps(doc));wrong['source']['sha256']='0'*64
            other=root/'wrong-input-track.json';other.write_text(json.dumps(wrong))
            bad_guide=resolve_guides([{**guide,'track_path':str(other)}],mapping)
            with self.assertRaisesRegex(ValueError,'different effects input'):
                render_effects(source,plan,root/'wrong-input.mp4',composition=bad_guide)
            before=frame(source,5,root/'original.png');after=frame(output,5,root/'zoomed.png')
            self.assertGreater(sum(ImageStat.Stat(ImageChops.difference(before,after)).mean),5)
            track.write_text(track.read_text()+'\n')
            with self.assertRaisesRegex(ValueError,'artifact changed'):
                render_effects(source,plan,root/'stale.mp4')
            doc['rows'][5]={'frame':5,'box':None,'state':'lost','quality':{'feature_count':0,'reason':'occlusion'}}
            track.write_text(json.dumps(doc))
            with self.assertRaisesRegex(ValueError,'lost frames'):
                resolve_effects(setting,mapping)

    def test_declared_region_rejects_title_before_render_and_records_clearance(self):
        from video_harness.composition import resolve_guides
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);source=root/'source.mp4';output=root/'title.mp4'
            fixture(source)
            mapping={'fps':'10','duration':'6/5','sequence':[]}
            event={'id':'word','type':'keyword_title','output_start':'1/5','output_end':'1',
                   'strength':1,'reason':'Show the result','parameters':{'text':'結果','y':.75,'font_size_fraction':.12}}
            plan=resolve_effects({'version':1,'mapping_sha256':digest(mapping),'events':[event]},mapping)
            guide={'id':'hands','kind':'subject','rect':[.1,.1,.9,.95],
                   'output_start':'0','output_end':'6/5','reason':'Keep observed action visible'}
            composition=resolve_guides([guide],mapping)
            with self.assertRaisesRegex(ValueError,'intersects'):
                render_effects(source,plan,output,composition=composition)
            self.assertFalse(output.exists())
            composition=resolve_guides([{**guide,'rect':[.01,.01,.05,.05]}],mapping)
            report=render_effects(source,plan,output,composition=composition)
            self.assertEqual(report['composition']['checks'][0]['status'],'no_detected_conflict')

    def test_keyword_title_has_measured_bounds_and_real_animation(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);source=root/'source.mp4';output=root/'title.mp4'
            fixture(source)
            mapping={'fps':'10','duration':'6/5','sequence':[]}
            event={'id':'keyword','type':'keyword_title','output_start':'1/5','output_end':'1',
                   'strength':1,'reason':'Emphasize the demonstrated result',
                   'parameters':{'text':'結果','motion':'rise','font_size_fraction':.12}}
            plan=resolve_effects({'version':1,'mapping_sha256':digest(mapping),'events':[event]},mapping)
            report=render_effects(source,plan,output)
            self.assertEqual(pcm_hash(source),pcm_hash(output))
            self.assertEqual(report['frame_count'],12)
            bounds=report['text_assets'][0]['bounds']
            self.assertTrue(0<=bounds[0]<bounds[2]<=1)
            self.assertTrue(0<=bounds[1]<bounds[3]<=1)
            before=frame(source,5,root/'before-title.png');after=frame(output,5,root/'after-title.png')
            crop=tuple(round(v*s) for v,s in zip(bounds,(160,90,160,90)))
            self.assertGreater(sum(ImageStat.Stat(ImageChops.difference(before.crop(crop),after.crop(crop))).mean),30)
            broken=json.loads(json.dumps(plan));broken['events'][0]['font_sha256']='0'*64
            with self.assertRaisesRegex(ValueError,'font binding'):
                render_effects(source,broken,root/'bad-font.mp4')

    def test_comparison_uses_second_video_and_retains_only_base_sound(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source, second, output = root/'red.mp4', root/'blue.mp4', root/'comparison.mp4'
            for path, color, freq in [(source, 'red', 440), (second, 'blue', 880)]:
                subprocess.run(['ffmpeg','-v','error','-nostdin','-n',
                    '-f','lavfi','-i',f'color={color}:s=160x90:r=10:d=1.2',
                    '-f','lavfi','-i',f'sine=frequency={freq}:sample_rate=48000:duration=1.2',
                    '-c:v','libx264','-pix_fmt','yuv420p','-c:a','aac','-shortest',str(path)],
                    check=True,capture_output=True)
            registry = [{'asset_id':'second','kind':'video','path':str(second),
                         'sha256':hashlib.sha256(second.read_bytes()).hexdigest()}]
            mapping={'fps':'10','duration':'6/5','sequence':[]}
            event={'id':'comparison','type':'comparison_wipe','output_start':'1/5',
                   'output_end':'1','strength':1,'reason':'Compare distinct source pictures',
                   'parameters':{'asset_id':'second'}}
            setting={'version':1,'mapping_sha256':digest(mapping),'events':[event]}
            plan=resolve_effects(setting,mapping,registry)
            report=render_effects(source,plan,output,registry)
            self.assertEqual(pcm_hash(source),pcm_hash(output))
            picture=frame(output,5,root/'middle.png')
            left,right=picture.getpixel((30,45)),picture.getpixel((130,45))
            self.assertGreater(left[0],200)
            self.assertGreater(right[2],200)
            self.assertLess(right[0],20)
            final=frame(output,11,root/'end.png')
            self.assertGreater(final.getpixel((130,45))[0],200)
            self.assertFalse(report['secondary_inputs'][0]['audio_used'])
            event['parameters']['layout']='side_by_side'
            pair_plan=resolve_effects(setting,mapping,registry)
            pair_output=root/'pair.mp4'
            pair_report=render_effects(source,pair_plan,pair_output,registry)
            self.assertEqual(pair_report['frame_count'],12)
            self.assertEqual(pcm_hash(source),pcm_hash(pair_output))
            pair_picture=frame(pair_output,5,root/'pair.png')
            self.assertGreater(pair_picture.getpixel((30,45))[0],200)
            self.assertGreater(pair_picture.getpixel((130,45))[2],200)
            self.assertLess(max(pair_picture.getpixel((30,5))),20)
            second.write_bytes(b'changed source')
            with self.assertRaisesRegex(ValueError,'mismatch'):
                render_effects(source,plan,root/'bad.mp4',registry)

    def test_revisions_validate_and_preserve_original(self):
        mapping = {'fps': '10', 'duration': '6/5', 'sequence': []}
        event = {'id': 'focus', 'type': 'smooth_zoom', 'output_start': '0',
                 'output_end': '6/5', 'strength': .8, 'reason': 'show left subject',
                 'parameters': {'anchor_x': .2}}
        setting = revise_effects(None, mapping, [{'action': 'add', 'event': event}])
        updated = revise_effects(setting, mapping, [{'action': 'update', 'id': 'focus',
                                'changes': {'strength': .3, 'parameters': {'anchor_y': .7}}}])
        self.assertEqual(setting['events'][0]['strength'], .8)
        self.assertEqual(updated['events'][0]['parameters']['anchor_x'], .2)
        self.assertEqual(updated['events'][0]['parameters']['anchor_y'], .7)
        self.assertEqual(revise_effects(updated, mapping, [{'action': 'remove', 'id': 'focus'}])['events'], [])
        with self.assertRaises(ValueError):
            revise_effects(updated, mapping, [{'action': 'update', 'id': 'focus',
                           'changes': {'parameters': {'anchor_x': float('nan')}}}])

    def test_parameterized_effects_change_picture_and_preserve_sound(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / 'source.mp4'
            fixture(source)
            mapping = {'fps': '10', 'duration': '6/5', 'sequence': []}
            outputs = []
            for index, params in enumerate(({'anchor_x': .1}, {'anchor_x': .9})):
                row = {'id': 'zoom', 'type': 'smooth_zoom', 'output_start': '0',
                       'output_end': '6/5', 'strength': 1, 'reason': 'target anchor',
                       'parameters': {**params, 'max_scale': 1.5}}
                plan = resolve_effects({'version': 1, 'mapping_sha256': digest(mapping), 'events': [row]}, mapping)
                out = root / f'zoom{index}.mp4'
                report = render_effects(source, plan, out)
                self.assertEqual(report['frame_count'], 12)
                self.assertEqual(pcm_hash(source), pcm_hash(out))
                outputs.append(frame(out, 5, root / f'z{index}.png'))
            self.assertGreater(sum(ImageStat.Stat(ImageChops.difference(*outputs)).mean), 15)
            pictures = []
            for index, strength in enumerate((.2, 1)):
                row = {'id': 'color', 'type': 'saturation_pulse', 'output_start': '0',
                       'output_end': '6/5', 'strength': strength, 'reason': 'local accent'}
                plan = resolve_effects({'version': 1, 'mapping_sha256': digest(mapping), 'events': [row]}, mapping)
                out = root / f'saturation{index}.mp4'
                render_effects(source, plan, out)
                self.assertEqual(pcm_hash(source), pcm_hash(out))
                pictures.append(frame(out, 5, root / f's{index}.png'))
            self.assertGreater(sum(ImageStat.Stat(ImageChops.difference(*pictures)).mean), 15)

    def test_quantized_cfr_timestamps_accepted_but_true_vfr_rejected(self):
        stream = {'r_frame_rate': '24000/1001', 'avg_frame_rate': '128000/5339',
                  'time_base': '1/16000'}
        def frames(ticks):
            return json.dumps({'frames': [{'best_effort_timestamp': str(tick)}
                                          for tick in ticks]}).encode()
        with patch('video_harness.video_effects.subprocess.check_output', return_value=frames([0, 672, 1328, 2000])):
            self.assertEqual(_verified_rate('unused.mp4', stream, 4), Fraction(24000, 1001))
        with patch('video_harness.video_effects.subprocess.check_output', return_value=frames([0, 672, 4000, 4672])):
            with self.assertRaisesRegex(ValueError, 'constant frame rate'):
                _verified_rate('unused.mp4', stream, 4)

    def test_natural_and_strict_plan(self):
        legacy = {'duration': 1, 'sequence': []}
        self.assertEqual(resolve_effects(None, legacy)['events'], [])
        mapping = {'fps': '10', 'duration': '6/5s', 'sequence': [
            {'id': 'a', 'output_start': '0s', 'output_end': '3/5s'},
            {'id': 'b', 'output_start': '3/5s', 'output_end': '6/5s'}]}
        plan = resolve_effects({'preset': 'pop_dance', 'intensity': 'low'}, mapping)
        self.assertEqual({e['type'] for e in plan['events']},
                         {'zoom_pulse', 'split_screen'})
        self.assertEqual(plan['mapping_sha256'], digest(mapping))
        stale = {'version': 1, 'mapping_sha256': '0' * 64, 'events': []}
        with self.assertRaisesRegex(ValueError, 'Stale'):
            resolve_effects(stale, mapping)
        invalid = {'version': 1, 'mapping_sha256': digest(mapping), 'events': [
            {'id': 'bad', 'type': 'shake', 'output_start': '0', 'output_end': '1/10',
             'strength': .5, 'reason': 'test'}]}
        with self.assertRaisesRegex(ValueError, 'Unsupported'):
            resolve_effects(invalid, mapping)
        invalid['events'][0]['type'] = 'monochrome'
        invalid['events'][0]['output_start'] = '1/20'
        with self.assertRaisesRegex(ValueError, 'align'):
            resolve_effects(invalid, mapping)

    def test_four_effects_render_picture_and_preserve_audio(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source, result = root / 'source.mp4', root / 'result.mp4'
            fixture(source)
            mapping = {'fps': '10', 'duration': '6/5', 'sequence': [
                {'id': 'a', 'output_start': '0', 'output_end': '3/5'},
                {'id': 'b', 'output_start': '3/5', 'output_end': '6/5'}]}
            rows = []
            for index, kind in enumerate(('zoom_pulse', 'split_screen', 'monochrome', 'color_frame')):
                rows.append({'id': str(index), 'type': kind,
                             'output_start': str(Fraction(2 + 2 * index, 10)),
                             'output_end': str(Fraction(4 + 2 * index, 10)),
                             'strength': .7, 'reason': 'explicit review choice'})
            plan = resolve_effects({'version': 1, 'mapping_sha256': digest(mapping), 'events': rows}, mapping)
            report = render_effects(source, plan, result)
            self.assertEqual(report['frame_count'], 12)
            self.assertEqual(report['fps'], '10')
            self.assertEqual(pcm_hash(source), pcm_hash(result))
            for index in (2, 4, 6, 8):
                before = frame(source, index, root / f'before-{index}.png')
                after = frame(result, index, root / f'after-{index}.png')
                self.assertGreater(sum(ImageStat.Stat(ImageChops.difference(before, after)).mean), 8,
                                   f'effect at frame {index} was not visible')
            self.assertTrue(result.is_file())


if __name__ == '__main__':
    unittest.main()
