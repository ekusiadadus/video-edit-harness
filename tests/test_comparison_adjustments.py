"""Browser corrections create actual new renders without adopting old choices."""
from copy import deepcopy
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from tests.test_visual_editing import VisualEditingTests
from video_harness.common import read, write
from video_harness.render_cache import digest
from video_harness.session import Session
from video_harness.video_effects import comparison_effect_controls, revise_comparison_effects


@unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'FFmpeg required')
class ComparisonAdjustmentTests(unittest.TestCase):
    def test_frame_range_and_anchor_move_render_and_preview_both_windows(self):
        from video_harness.assets import register_asset
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            cfg, plan = VisualEditingTests().fixture(root, source_audio=True)
            source = root / 'pattern.mp4'
            subprocess.run(['ffmpeg', '-v', 'error', '-nostdin', '-n', '-f', 'lavfi',
                '-i', 'testsrc2=s=128x128:r=10:d=1', '-f', 'lavfi',
                '-i', 'sine=frequency=440:sample_rate=48000:duration=1',
                '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-c:a', 'aac', str(source)], check=True)
            old = cfg['assets'][0]
            metadata = {key: old[key] for key in ('asset_id', 'kind', 'creator', 'source_url',
                'license_url', 'acquired_on', 'verified_on', 'evidence_path', 'credit',
                'cost', 'currency', 'content_id', 'rights')}
            cfg.update(source=str(source), edit_basis='visual', assets=[register_asset(source, metadata)])
            write(root / 'project.json', cfg)
            session = Session.start(root / 'project.json', root / 'session')
            session.propose_visual(plan, 'automation')
            session.approve('automation', 'Synthetic observed frame ranges')
            natural = session.render(preview=False)
            mapping = read(natural['files']['mapping']['path'])
            setting = {'version': 1, 'mapping_sha256': digest(mapping), 'events': [
                {'id': 'zoom', 'type': 'smooth_zoom', 'output_start': '0', 'output_end': '2/5',
                 'strength': 1, 'parameters': {'max_scale': 1.3}, 'reason': 'Synthetic target'}]}
            base = session.create_candidate({'editing_pattern': {'id': 'gentle_vlog',
                'music': 'off', 'sfx': 'off', 'beat_sync': 'off'}, 'video_effects': setting},
                'codex', 'Original zoom interval')
            original = session.render(preview=False, candidate_id=base['id'])
            changes = {'strength': 1, 'output_start': '2/5', 'output_end': '4/5',
                       'parameters': {'anchor_x': .5, 'anchor_y': .5}}
            receipt = {'version': 3, 'kind': 'comparison_selection_proposal', 'render_id': original['id'],
                'render_sha256': original['files']['video']['sha256'], 'output_time': .2,
                'note': 'Move zoom to second interval and target', 'adopted': False, 'final_review': False,
                'effect_operations': [{'action': 'update', 'id': 'zoom', 'changes': changes}]}
            before = session._load()
            with self.assertRaises(ValueError):
                session.candidate_from_selection({**receipt, 'version': 2}, 'codex', 'Reject v2 new fields')
            for invalid in ({'output_start': '2/5'}, {'output_start': '1/100', 'output_end': '4/5'},
                            {'output_start': '1/10000', 'output_end': '4/5'},
                            {'parameters': {'max_scale': 1.5}}, {'parameters': {'anchor_x': True}},
                            {'parameters': {'anchor_y': float('nan')}}):
                with self.assertRaises(ValueError):
                    session.candidate_from_selection({**receipt, 'effect_operations': [
                        {'action': 'update', 'id': 'zoom', 'changes': invalid}]}, 'codex', 'Reject invalid range/position')
                self.assertEqual(session._load(), before)
            candidate = session.candidate_from_selection(receipt, 'codex', 'Apply observed range and anchor')
            rendered = session.render(preview=False, candidate_id=candidate['id'])
            preview = read(session.preview_effects(rendered['id'], context_frames=0)['path'])
            self.assertEqual((preview['first_frame'], preview['end_frame_exclusive']), (0, 8))
            alternative = deepcopy(receipt)
            alternative['effect_operations'][0]['changes']['parameters'] = {'anchor_x': .8, 'anchor_y': .2}
            other = session.candidate_from_selection(alternative, 'codex', 'Compare target position only')
            other_render = session.render(preview=False, candidate_id=other['id'])
            def decoded(render, audio=False):
                options = ['-vn', '-f', 's16le'] if audio else ['-an', '-pix_fmt', 'rgb24', '-f', 'rawvideo']
                return subprocess.check_output(['ffmpeg', '-v', 'error', '-i', render['files']['video']['path'], *options, '-'])
            self.assertNotEqual(decoded(rendered), decoded(other_render))
            self.assertNotEqual(decoded(original), decoded(rendered))
            self.assertEqual(decoded(original, True), decoded(rendered, True))
            self.assertEqual(session._load()['project'], before['project'])
            self.assertEqual(session._load()['reviews'], [])

    def test_adjusted_snapshot_renders_changed_picture_and_same_audio_without_adoption(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            cfg, plan = VisualEditingTests().fixture(root, source_audio=True)
            cfg['edit_basis'] = 'visual'
            write(root / 'project.json', cfg)
            session = Session.start(root / 'project.json', root / 'session')
            session.propose_visual(plan, 'automation')
            session.approve('automation', 'Synthetic source inspection')
            natural = session.render(preview=False, actor='automation')
            mapping = read(natural['files']['mapping']['path'])
            effects = {'version': 1, 'mapping_sha256': digest(mapping), 'events': [
                {'id': 'pulse', 'type': 'saturation_pulse', 'output_start': '0',
                 'output_end': '2/5', 'strength': 1, 'parameters': {'minimum_saturation': 0},
                 'reason': 'Synthetic saturation comparison'},
                {'id': 'mono', 'type': 'monochrome', 'output_start': '2/5',
                 'output_end': '4/5', 'strength': 1, 'reason': 'Synthetic off comparison'}]}
            base = session.create_candidate({'editing_pattern': {'id': 'gentle_vlog',
                'music': 'off', 'sfx': 'off', 'beat_sync': 'off'}, 'video_effects': effects},
                'codex', 'Create synthetic effect baseline')
            original = session.render(preview=False, candidate_id=base['id'])
            page = session.compare_candidates([natural['id'], original['id']])
            html = Path(page['artifact']['path']).read_text()
            self.assertIn('effect_controls', html)
            self.assertIn('adjustable_strength', html)
            before = session._load()
            receipt = {'version': 2, 'kind': 'comparison_selection_proposal',
                'render_id': original['id'], 'render_sha256': original['files']['video']['sha256'],
                'output_time': .2, 'note': 'Less saturation change; no monochrome',
                'adopted': False, 'final_review': False, 'effect_operations': [
                    {'action': 'update', 'id': 'pulse', 'changes': {'strength': .2}},
                    {'action': 'remove', 'id': 'mono'}]}
            for invalid in ([], [{'action': 'remove', 'id': 'unknown'}],
                    [{'action': 'update', 'id': 'pulse', 'changes': {'strength': True}}],
                    [{'action': 'update', 'id': 'pulse', 'changes': {'strength': float('nan')}}],
                    [{'action': 'update', 'id': 'mono', 'changes': {'strength': .5}}],
                    [{'action': 'update', 'id': 'pulse', 'changes': {'parameters': {}}}],
                    [{'action': 'remove', 'id': 'pulse'}] * 2):
                with self.subTest(invalid=invalid):
                    with self.assertRaises(ValueError):
                        session.candidate_from_selection({**receipt, 'effect_operations': invalid},
                                                         'codex', 'Reject invalid changes')
                    self.assertEqual(session._load(), before)
            adjusted = session.candidate_from_selection(receipt, 'codex', 'Apply comparison corrections')
            self.assertEqual(read(adjusted['project']['path'])['video_effects']['events'][0]['strength'], .2)
            self.assertEqual(len(read(adjusted['project']['path'])['video_effects']['events']), 1)
            for key in ('project', 'plan', 'brief', 'reviews', 'phase'):
                self.assertEqual(session._load().get(key), before.get(key))
            with self.assertRaisesRegex(ValueError, 'Render'):
                session.adopt_candidate(adjusted['id'], 'codex', 'Cannot adopt before rendering')
            rendered = session.render(preview=False, candidate_id=adjusted['id'])
            def decode(render, kind):
                path = render['files']['video']['path']
                options = (['-an', '-pix_fmt', 'rgb24', '-f', 'rawvideo'] if kind == 'video'
                           else ['-vn', '-f', 's16le'])
                return subprocess.check_output(['ffmpeg', '-v', 'error', '-i', path, *options, '-'])
            self.assertNotEqual(decode(original, 'video'), decode(rendered, 'video'))
            self.assertEqual(decode(original, 'audio'), decode(rendered, 'audio'))
            self.assertEqual(read(rendered['files']['mapping']['path']), mapping)
            self.assertEqual(session._load()['reviews'], [])
            self.assertEqual(read(original['project']['path'])['video_effects'], effects)
            unchanged = session._load()
            with self.assertRaisesRegex(ValueError, 'changed effect'):
                session.preview_effects(rendered['id'], ['unknown'], 0)
            with self.assertRaisesRegex(ValueError, 'context'):
                session.preview_effects(rendered['id'], ['mono'], True)
            preview_ref = session.preview_effects(rendered['id'], ['mono'], 0)
            preview = read(preview_ref['path'])
            self.assertEqual(preview['first_frame'], 4)
            self.assertEqual(preview['end_frame_exclusive'], 8)
            self.assertEqual(preview['review_status'], 'pending')
            self.assertEqual(session._load(), unchanged)
            from unittest.mock import patch
            def failed_excerpt(source, target, first, end, rate, log):
                target.write_bytes(b'incomplete video')
                log.write_text('Synthetic failure after output creation')
                raise RuntimeError('Synthetic excerpt failure')
            folders = set((session.root / 'inspections').iterdir())
            with patch('video_harness.effect_preview._excerpt', side_effect=failed_excerpt):
                with self.assertRaisesRegex(RuntimeError, 'excerpt failure'):
                    session.preview_effects(rendered['id'], ['mono'], 0)
            failed = (set((session.root / 'inspections').iterdir()) - folders).pop()
            self.assertEqual(read(failed / 'result.json')['technical_status'], 'failed')
            self.assertFalse((failed / 'before.mp4').exists())
            self.assertFalse((failed / 'preview.html').exists())
            self.assertTrue((failed / 'before-render.log').exists())
            self.assertEqual(session._load(), unchanged)
            # The preview must be frames 4..7 of the completed picture, not a
            # restarted effect on frame zero of a shortened source.
            original_rgb = decode(original, 'video')
            revised_rgb = decode(rendered, 'video')
            for name, full_rgb in [('before', original_rgb), ('after', revised_rgb)]:
                clip = Path(preview_ref['path']).parent / (name + '.mp4')
                clip_rgb = subprocess.check_output(['ffmpeg', '-v', 'error', '-i', str(clip),
                    '-an', '-pix_fmt', 'rgb24', '-f', 'rawvideo', '-'])
                frame_bytes = len(full_rgb) // 8
                self.assertEqual(clip_rgb, full_rgb[4 * frame_bytes:8 * frame_bytes])
            session.adopt_candidate(adjusted['id'], 'codex', 'Adopt rendered synthetic correction')
            self.assertEqual(session._load()['project'], adjusted['project'])
            self.assertEqual(session._load()['reviews'], [])

    def test_sealed_phase_and_plan_captures_are_not_adjustable(self):
        mapping = {'fps': '10', 'duration': '.4', 'sequence': []}
        event = {'id': 'pulse', 'type': 'saturation_pulse', 'output_start': 0,
                 'output_end': '.4', 'strength': .5, 'reason': 'Synthetic phase clock',
                 'parameters': {'minimum_saturation': 0},
                 'phase_map': {'version': 1, 'original_frame_count': 4, 'frames': [0,1,2,3]}}
        setting = {'version': 1, 'mapping_sha256': digest(mapping), 'events': [event]}
        with self.assertRaisesRegex(ValueError, 'adjustable'):
            revise_comparison_effects(setting, mapping, [{'action': 'remove', 'id': 'pulse'}])
        self.assertEqual(comparison_effect_controls({'events': [{'id': 'captured', 'content_map': {}}]}), [])

@unittest.skipUnless(shutil.which('node'), 'Node required for browser script contract')
class ComparisonControlsScriptTests(unittest.TestCase):
    def test_controls_export_off_strength_undo_and_preserve_each_choice(self):
        import json
        import re
        from video_harness.comparison import comparison_page
        rows = [{'label': 'natural', 'video': 'file:///natural.mp4', 'render_id': 'natural',
                 'sha256': 'a' * 64, 'effect_controls': []},
                {'label': 'effects', 'video': 'file:///effects.mp4', 'render_id': 'effects',
                 'sha256': 'b' * 64, 'effect_controls': [
                     {'id': 'pulse', 'kind': 'smooth_zoom', 'strength': .005, 'adjustable_strength': True,
                      'fps': '30000/1001', 'frame_count': 30, 'first_frame': 3, 'end_frame_exclusive': 9,
                      'adjustable_range': True, 'anchor': {'anchor_x': .5, 'anchor_y': .5}},
                     {'id': 'mono', 'kind': 'monochrome', 'strength': 1, 'adjustable_strength': False}]}]
        script = re.search(r'<script>(.*?)</script>', comparison_page(rows), re.S).group(1)
        harness = r'''
const vm=require('node:vm'),assert=require('node:assert/strict');
class Element {
 constructor(){this.children=[];this.events={};this.dataset={};this.value='0';this.duration=1;this.currentTime=0;this.readyState=1;this.classList={toggle(){}};}
 append(...elements){this.children.push(...elements);}
 replaceChildren(){this.children=[];}
 addEventListener(name,callback){this.events[name]=callback;}
 click(){if(this.onclick)this.onclick();}
 pause(){}
}
const ids={},videos=[new Element(),new Element()],articles=[new Element(),new Element()];
const choices=rows.map((_,i)=>{const e=new Element();e.dataset.choice=i;return e;});
const audios=rows.map((_,i)=>{const e=new Element();e.dataset.audio=i;return e;});
let saved;
const context={console,Map,Set,Number,JSON,Array,String,Promise,Blob,
 document:{querySelector(s){return ids[s]??=new Element();},querySelectorAll(s){return ({video:videos,article:articles,'[data-choice]':choices,'[data-audio]':audios})[s];},createElement(){return new Element();}},
 requestAnimationFrame(){},setTimeout(){},URL:{createObjectURL(blob){saved=blob;return 'blob:test';},revokeObjectURL(){}}};
vm.runInNewContext(script,context);
const save=async()=>{ids['#save'].click();return JSON.parse(await saved.text());};
const input=(element,value)=>{element.value=value;element.events.input();};
(async()=>{
 choices[1].click();
 const list=ids['#effect-list'];
 assert.equal(list.children.length,2);
 assert.equal(list.children[1].children.length,2); // mono has title and Off, no strength slider
 const slider=list.children[0].children[1].children[0];
 assert.equal(slider.min,'0.005');assert.equal(slider.step,'any');assert.equal(slider.value,'0.005');
 input(slider,'0.2');input(slider,'0.3');slider.events.change();
 let receipt=await save();assert.equal(receipt.version,2);
 assert.deepEqual(receipt.effect_operations,[{action:'update',id:'pulse',changes:{strength:.3}}]);
 ids['#undo-effects'].click();assert.equal((await save()).version,1);
 input(list.children[0].children[1].children[0],'0.3');
 choices[0].click();assert.equal((await save()).version,1);
 choices[1].click();assert.equal((await save()).effect_operations[0].changes.strength,.3);
 const off=list.children[1].children[1].children[0];off.checked=true;off.events.change();
 receipt=await save();assert.deepEqual(receipt.effect_operations[1],{action:'remove',id:'mono'});
 ids['#undo-effects'].click();assert.equal((await save()).effect_operations.length,1);
 ids['#reset-effects'].click();receipt=await save();assert.equal(receipt.version,1);assert.equal(Object.keys(receipt).length,8);
 ids['#undo-effects'].click();assert.equal((await save()).effect_operations[0].changes.strength,.3);
 assert.equal((await save()).render_sha256,'b'.repeat(64));
 const start=list.children[0].children[2].children[0];start.value='6';start.events.change();
 receipt=await save();assert.equal(receipt.version,3);
 assert.equal(receipt.effect_operations[0].changes.output_start,'6006/30000');
 assert.equal(receipt.effect_operations[0].changes.output_end,'9009/30000');
 const anchorX=list.children[0].children[4].children[0];anchorX.value='0.2';anchorX.events.change();
 assert.deepEqual((await save()).effect_operations[0].changes.parameters,{anchor_x:.2});
 ids['#undo-effects'].click();assert.equal((await save()).effect_operations[0].changes.parameters,undefined);
 ids['#reset-effects'].click();assert.equal((await save()).version,1);
 const invalid=list.children[0].children[2].children[0];invalid.value='2.5';invalid.events.change();
 const lastSaved=saved;ids['#save'].click();assert.equal(saved,lastSaved);
 assert.match(ids['#status'].textContent,/範囲/);
 ids['#undo-effects'].click();assert.equal((await save()).version,1);
})().catch(error=>{console.error(error);process.exitCode=1;});
'''
        subprocess.run(['node', '-e', 'const rows=' + json.dumps(rows) + ';const script=' +
                        json.dumps(script) + ';' + harness], check=True, capture_output=True)
