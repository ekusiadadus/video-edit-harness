"""BGM corrections preserve picture/source audio and never reuse stale preview audio."""
from copy import deepcopy
import json
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest

from video_harness.common import fingerprint, read, write
from video_harness.comparison_music import music_controls, revise_music
from video_harness.render_cache import digest


class MusicCorrectionContractTests(unittest.TestCase):
    def test_only_existing_music_is_editable_and_normalized_solo_gain_is_hidden(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write(root / 'result.json', {'artifacts': {}})
            render = {'path': str(root), 'files': {'result': fingerprint(root / 'result.json')}}
            mapping = {'fps': '24', 'duration': '1'}
            production = {'mapping_sha256': digest(mapping), 'cues': [
                {'id': 'bgm', 'role': 'music', 'asset_id': 'song', 'gain_db': 0},
                {'id': 'click', 'role': 'sfx', 'asset_id': 'sfx', 'gain_db': -3}]}
            cfg = {'audio': {'normalize': True}}
            self.assertFalse(music_controls(cfg, production, render)[0]['adjustable_gain'])
            off = revise_music(cfg, mapping, production, render, [{'action': 'remove', 'id': 'bgm'}])
            self.assertEqual(off['cues'], [production['cues'][1]])
            for operations in ([{'action': 'gain', 'id': 'bgm', 'gain_db': -12}],
                               [{'action': 'remove', 'id': 'click'}],
                               [{'action': 'remove', 'id': 'bgm'}] * 2,
                               [{'action': 'gain', 'id': 'bgm', 'gain_db': float('nan')}],
                               [{'action': 'replace', 'id': 'bgm', 'asset_id': 'another'}]):
                with self.assertRaises(ValueError):
                    revise_music(cfg, mapping, production, render, operations)
            mix = {'speech_rms': .1}
            write(root / 'mix-evidence.json', mix)
            result2 = root / 'result2.json'
            write(result2, {'artifacts': {'mix-evidence.json': fingerprint(root / 'mix-evidence.json')['sha256']}})
            render['files']['result'] = fingerprint(result2)
            self.assertTrue(music_controls(cfg, production, render)[0]['adjustable_gain'])
            revised = revise_music(cfg, mapping, production, render,
                                   [{'action': 'gain', 'id': 'bgm', 'gain_db': -12}])
            self.assertEqual(revised['cues'][0]['gain_db'], -12)
            self.assertEqual(production['cues'][0]['gain_db'], 0)
            for gain in (True, float('nan'), float('inf'), -61, 13):
                with self.assertRaises(ValueError):
                    revise_music(cfg, mapping, production, render,
                                 [{'action': 'gain', 'id': 'bgm', 'gain_db': gain}])
            Path(root / 'mix-evidence.json').write_text('{"speech_rms":0}')
            with self.assertRaisesRegex(ValueError, 'evidence changed'):
                music_controls(cfg, production, render)
            captured = deepcopy(production)
            captured['cues'][1]['audio_retime'] = {}
            self.assertEqual(music_controls(cfg, captured, render), [])

    @unittest.skipUnless(shutil.which('node'), 'Node required for browser script contract')
    def test_page_music_gain_off_undo_and_candidate_switching(self):
        from video_harness.comparison import comparison_page
        rows = [{'label': 'natural', 'video': 'file:///a.mp4', 'render_id': 'a', 'sha256': 'a' * 64},
                {'label': 'music', 'video': 'file:///b.mp4', 'render_id': 'b', 'sha256': 'b' * 64,
                 'music_controls': [{'id': 'bgm', 'asset_id': 'song', 'gain_db': 0,
                                     'adjustable_gain': True, 'minimum_gain_db': -60, 'maximum_gain_db': 12,
                                     'replacement_choices': [{'asset_id': 'new', 'asset_sha256': 'c'*64, 'label': 'New song'}]}]}]
        script = re.search(r'<script>(.*?)</script>', comparison_page(rows), re.S).group(1)
        harness = r'''
const vm=require('node:vm'),assert=require('node:assert/strict');
class E{constructor(){this.children=[];this.events={};this.dataset={};this.value='0';this.duration=1;this.currentTime=0;this.classList={toggle(){}};}
append(...x){this.children.push(...x);}replaceChildren(){this.children=[];}addEventListener(k,v){this.events[k]=v;}click(){this.onclick?.();}pause(){}}
const ids={},videos=[new E(),new E()],articles=[new E(),new E()],choices=rows.map((r,i)=>{const e=new E();e.dataset.choice=i;return e;}),audios=choices;let saved;
const context={Map,Set,Number,JSON,Array,String,Promise,Blob,document:{querySelector(s){return ids[s]??=new E();},querySelectorAll(s){return {video:videos,article:articles,'[data-choice]':choices,'[data-audio]':audios}[s];},createElement(){return new E();}},URL:{createObjectURL(b){saved=b;return 'blob:test';},revokeObjectURL(){}},setTimeout(){},requestAnimationFrame(){}};
vm.runInNewContext(script,context);
(async()=>{const save=async()=>{ids['#save'].click();return JSON.parse(await saved.text());};
choices[1].click();let row=ids['#music-list'].children[0];let gain=row.children[1].children[0];gain.value='-12';gain.events.change();
let value=await save();assert.equal(value.version,4);assert.deepEqual(value.effect_operations,[]);assert.deepEqual(value.music_operations,[{action:'gain',id:'bgm',gain_db:-12}]);
choices[0].click();assert.equal((await save()).version,1);choices[1].click();assert.deepEqual(await save(),value);
row=ids['#music-list'].children[0];const off=row.children[2].children[0];off.checked=true;off.events.change();assert.deepEqual((await save()).music_operations,[{action:'remove',id:'bgm'}]);
ids['#undo-effects'].click();assert.deepEqual(await save(),value);ids['#reset-effects'].click();assert.equal((await save()).version,1);
gain=ids['#music-list'].children[0].children[1].children[0];gain.value='100';gain.events.change();const old=saved;ids['#save'].click();assert.equal(saved,old);assert.match(ids['#status'].textContent,/BGM/);
ids['#undo-effects'].click();assert.equal((await save()).version,1);
row=ids['#music-list'].children[0];const track=row.children[3].children[0];track.value='new';track.events.change();
let newValue=await save();assert.equal(newValue.version,5);assert.deepEqual(newValue.music_operations,[{action:'replace',id:'bgm',asset_id:'new',asset_sha256:'c'.repeat(64),source_start:'0',gain_db:0}]);
row=ids['#music-list'].children[0];const start=row.children[4].children[0];start.value='0.1';start.events.change();assert.equal((await save()).music_operations[0].source_start,'0.1');
ids['#undo-effects'].click();assert.deepEqual(await save(),newValue);ids['#reset-effects'].click();assert.equal((await save()).version,1);
})().catch(e=>{console.error(e);process.exitCode=1;});'''
        subprocess.run(['node', '-e', 'const rows=' + json.dumps(rows) + ';const script=' + json.dumps(script) + ';' + harness], check=True)


class MusicCorrectionRenderTests(unittest.TestCase):
    def test_real_music_gain_changes_ratio_and_off_restores_source_without_adoption(self):
        import numpy as np
        from tests.test_visual_editing import VisualEditingTests
        from video_harness.assets import register_asset
        from video_harness.session import Session
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cfg, plan = VisualEditingTests().fixture(root, source_audio=True)
            music = root / 'music.wav'
            subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i',
                'sine=frequency=880:sample_rate=48000:duration=1', str(music)], check=True)
            metadata = {key: cfg['assets'][0][key] for key in ('creator', 'source_url', 'license_url',
                'acquired_on', 'verified_on', 'evidence_path', 'credit', 'cost', 'currency', 'content_id', 'rights')}
            cfg['assets'].append(register_asset(music, {**metadata, 'asset_id': 'song', 'kind': 'music'}))
            alternative = root / 'alternative.wav'
            subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i',
                'sine=frequency=1320:sample_rate=48000:duration=1', str(alternative)], check=True)
            cfg['assets'].append(register_asset(alternative, {**metadata, 'asset_id': 'alternative', 'kind': 'music'}))
            cfg.update(edit_basis='visual')
            cfg['audio']['normalize'] = True
            write(root / 'project.json', cfg)
            session = Session.start(root / 'project.json', root / 'session')
            session.propose_visual(plan, 'codex')
            session.approve('codex', 'Synthetic ranges')
            natural = session.render(preview=False)
            mapping = read(natural['files']['mapping']['path'])
            candidate = session.create_candidate({'editing_pattern': {'id': 'gentle_vlog',
                'music': 'selected', 'sfx': 'off', 'visual_assets': 'off', 'beat_sync': 'off'},
                'cue_plan': {'version': 1, 'mapping_sha256': digest(mapping), 'cues': [
                    {'id': 'bgm', 'role': 'music', 'asset_id': 'song', 'output_start': '0',
                     'output_end': '4/5', 'source_start': '0', 'source_end': '4/5', 'gain_db': 0,
                     'fade_in': 0, 'fade_out': 0, 'duck': False, 'loop': False, 'reason': 'Synthetic music'}]}},
                'codex', 'Synthetic BGM baseline')
            original = session.render(preview=False, candidate_id=candidate['id'])
            page = session.compare_candidates([natural['id'], original['id']])
            html = Path(page['artifact']['path']).read_text()
            rows = json.loads(re.search(r'<script>const rows=(.*?);\nconst videos', html, re.S).group(1))
            self.assertEqual(rows[1]['music_controls'][0]['id'], 'bgm')
            self.assertTrue(rows[1]['music_controls'][0]['adjustable_gain'])
            before = session._load()
            receipt = {'version': 4, 'kind': 'comparison_selection_proposal', 'render_id': original['id'],
                'render_sha256': original['files']['video']['sha256'], 'output_time': .2,
                'note': 'Lower BGM', 'adopted': False, 'final_review': False,
                'effect_operations': [], 'music_operations': [{'action': 'gain', 'id': 'bgm', 'gain_db': -12}]}
            weaker = session.candidate_from_selection(receipt, 'codex', 'Lower music only')
            with self.assertRaisesRegex(ValueError, 'full render'):
                session.preview_changes(weaker['id'])
            revised = session.render(preview=False, candidate_id=weaker['id'])
            off_receipt = {**receipt, 'music_operations': [{'action': 'remove', 'id': 'bgm'}]}
            off = session.candidate_from_selection(off_receipt, 'codex', 'Disable music only')
            muted = session.render(preview=False, candidate_id=off['id'])
            replacement_op = {'action': 'replace', 'id': 'bgm', 'asset_id': 'alternative',
                'asset_sha256': fingerprint(alternative)['sha256'], 'source_start': '1/10', 'gain_db': 0}
            replacement_receipt = {**receipt, 'version': 5, 'music_operations': [replacement_op]}
            for change in ({'asset_sha256': '0'*64}, {'source_start': '1/2'}, {'source_start': -1},
                           {'source_start': 'nan'}, {'source_start': '-1/10'}):
                with self.assertRaises(ValueError):
                    session.candidate_from_selection({**replacement_receipt,
                        'music_operations': [{**replacement_op, **change}]}, 'codex', 'Invalid replacement')
            with self.assertRaises(ValueError):
                session.candidate_from_selection({**replacement_receipt, 'version': 4}, 'codex', 'Version 4 immutable')
            changed = session.candidate_from_selection(replacement_receipt, 'codex', 'Change registered track')
            with self.assertRaisesRegex(ValueError, 'full render'):
                session.preview_changes(changed['id'])
            replaced = session.render(preview=False, candidate_id=changed['id'])
            self.assertFalse(read(replaced['files']['music_change_evidence']['path'])['new_track_beat_alignment_verified'])
            self.assertEqual(read(changed['project']['path'])['editing_pattern']['beat_sync'], 'off')
            followup = session.create_candidate({'style_intensity': .5}, 'codex', 'Retain song evidence', base_render_id=replaced['id'])
            self.assertEqual(followup['music_change_evidence'], changed['music_change_evidence'])
            stale = Path(changed['music_change_evidence']['path'])
            retained = stale.read_bytes()
            stale.write_text('{}')
            with self.assertRaises(ValueError):
                session.resume()
            stale.write_bytes(retained)
            def pcm(render):
                return np.frombuffer(subprocess.check_output(['ffmpeg', '-v', 'error', '-i',
                    render['files']['video']['path'], '-vn', '-ac', '1', '-ar', '48000', '-f', 'f32le', '-']), dtype=np.float32)
            def ratio(audio):
                samples = audio[4800:28800]
                spectrum = np.abs(np.fft.rfft(samples * np.hanning(len(samples))))
                freqs = np.fft.rfftfreq(len(samples), 1/48000)
                return 20*np.log10(spectrum[np.argmin(abs(freqs-880))]/spectrum[np.argmin(abs(freqs-440))])
            samples = pcm(replaced)[4800:28800]
            spectrum = np.abs(np.fft.rfft(samples * np.hanning(len(samples))))
            freqs = np.fft.rfftfreq(len(samples), 1/48000)
            self.assertGreater(spectrum[np.argmin(abs(freqs-1320))],
                               30*spectrum[np.argmin(abs(freqs-880))])
            delta = ratio(pcm(original)) - ratio(pcm(revised))
            self.assertTrue(10 < delta < 14, delta)
            self.assertLess(ratio(pcm(muted)), ratio(pcm(original)) - 30)
            def picture(render):
                return subprocess.check_output(['ffmpeg', '-v', 'error', '-i', render['files']['video']['path'],
                    '-an', '-pix_fmt', 'rgb24', '-f', 'rawvideo', '-'])
            self.assertEqual(picture(original), picture(revised))
            self.assertEqual(picture(original), picture(muted))
            self.assertEqual(picture(original), picture(replaced))
            self.assertEqual(read(original['files']['mapping']['path']), read(replaced['files']['mapping']['path']))
            self.assertEqual(read(original['files']['mapping']['path']), read(revised['files']['mapping']['path']))
            for key in ('project', 'plan', 'reviews'):
                self.assertEqual(before[key], session._load()[key])
