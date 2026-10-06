"""Evidence for fair creative comparisons; never a perceptual approval."""
from copy import deepcopy
from fractions import Fraction
from pathlib import Path

from .common import read
from .production import frozen_pattern
from .render_cache import digest
from .time_mapping import compile_retime


def comparison_page(rows, mode='effects'):
    """Offline synchronized comparison; selection export is feedback, not approval."""
    if mode not in ('effects', 'timing'):
        raise ValueError('Unknown comparison mode')
    if mode == 'timing':
        return _timing_page(rows)
    import html
    import json
    cards = []
    for index, row in enumerate(rows):
        cards.append(f'<article><h2>{html.escape(row["label"])}</h2>'
                     f'<video preload="metadata" muted playsinline src="{html.escape(row["video"], quote=True)}"></video>'
                     f'<button data-audio="{index}">この案の音声</button>'
                     f'<button data-choice="{index}">この案を候補に選ぶ</button>'
                     f'<p>SHA-256: <code>{html.escape(row["sha256"])}</code></p></article>')
    data = json.dumps(rows, ensure_ascii=False).replace('<', '\\u003c')
    return '''<!doctype html><html lang="ja"><meta charset="utf-8">
<meta name="viewport" content="width=device-width"><title>編集候補の比較</title>
<style>body{font:16px system-ui;background:#171717;color:#eee;margin:24px}
main{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:18px}
video{width:100%;max-height:60vh}button,input,textarea{font:inherit;margin:6px;padding:8px}
article{padding:12px;border:2px solid #555;border-radius:8px}article.selected{border-color:#fff}
code{overflow-wrap:anywhere;font-size:11px}textarea{width:min(90%,700px)}</style>
<h1>同じ編集範囲の候補</h1><p>同じ時刻で比較します。音声は一案ずつ再生します。</p>
<button id="play">再生／停止</button><button id="start">先頭に戻す</button>
<label>再生位置 <input id="seek" type="range" min="0" max="0" step="0.01" value="0"></label>
<output id="time">0.00秒</output><p id="status" role="status">読み込み中</p>
<main>''' + ''.join(cards) + '''</main>
<label>修正したい点<br><textarea id="note" placeholder="例: 中盤のズームを弱める"></textarea></label>
<br><button id="save">選択と修正メモを保存</button>
<p>保存は候補の採用・人の最終承認・投稿を行いません。</p>
<script>const rows=''' + data + ''';
const videos=[...document.querySelectorAll('video')],seek=document.querySelector('#seek'),status=document.querySelector('#status');
let playing=false,choice=null,audio=0;
function message(text){status.textContent=text;}
function stop(){playing=false;videos.forEach(v=>v.pause());}
function position(t){videos.forEach(v=>{if(Number.isFinite(v.duration))v.currentTime=Math.min(t,v.duration);});seek.value=t;}
videos.forEach((v,i)=>{v.muted=i!==audio;v.addEventListener('loadedmetadata',()=>{
if(videos.every(x=>Number.isFinite(x.duration))){seek.max=Math.min(...videos.map(x=>x.duration));message('比較できます');}});
v.addEventListener('error',()=>{stop();message('動画を読み込めません。元のファイルが移動していないか確認してください。');});
v.addEventListener('ended',stop);});
document.querySelector('#play').onclick=async()=>{if(playing){stop();return;}
if(!videos.every(v=>v.readyState>=1)){message('動画の読み込みを待ってください');return;}
position(Number(seek.value));playing=true;try{await Promise.all(videos.map(v=>v.play()));message('再生中');}
catch(e){stop();message('再生できませんでした。動画ファイルとブラウザーを確認してください。');}};
document.querySelector('#start').onclick=()=>{stop();position(0);};
seek.oninput=()=>{stop();position(Number(seek.value));};
document.querySelectorAll('[data-audio]').forEach(b=>b.onclick=()=>{audio=Number(b.dataset.audio);videos.forEach((v,i)=>v.muted=i!==audio);message(rows[audio].label+' の音声');});
document.querySelectorAll('[data-choice]').forEach(b=>b.onclick=()=>{choice=Number(b.dataset.choice);
document.querySelectorAll('article').forEach((a,i)=>a.classList.toggle('selected',i===choice));message('候補: '+rows[choice].label);});
function tick(){if(playing){const t=videos[0].currentTime;seek.value=t;videos.slice(1).forEach(v=>{if(Math.abs(v.currentTime-t)>.12)v.currentTime=t;});}
document.querySelector('#time').textContent=Number(seek.value).toFixed(2)+'秒';requestAnimationFrame(tick);}tick();
document.querySelector('#save').onclick=()=>{if(choice===null){message('先に候補を選んでください');return;}
const result={version:1,kind:'comparison_selection_proposal',render_id:rows[choice].render_id,
render_sha256:rows[choice].sha256,output_time:Number(seek.value),note:document.querySelector('#note').value,
adopted:false,final_review:false};const url=URL.createObjectURL(new Blob([JSON.stringify(result,null,2)],{type:'application/json'}));
const a=document.createElement('a');a.href=url;a.download='comparison-selection.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
message('修正メモを保存しました。ハーネスで反映後、生成した動画を再確認してください。');};
</script></html>'''


FIXED_SETTINGS = ('input_color', 'white_balance_gains', 'use_case', 'style',
                  'style_intensity', 'adjustments', 'audio', 'review_regions',
                  'region_corrections', 'composition_guides', 'visual_pipeline_version')


def _timing_page(rows):
    """Retiming changes output time, so each full video has its own controls."""
    import html
    import json
    cards = []
    for index, row in enumerate(rows):
        duration = row.get('duration_seconds')
        timing = row.get('retime_operations', [])
        coverage = row.get('source_coverage', {})
        additions = row.get('production_changes', {})
        details = (f'<p>長さ: {html.escape(str(duration))} 秒</p>' if duration is not None else '')
        if timing:
            descriptions = []
            for operation in timing:
                if operation.get('kind') == 'freeze':
                    location = (f'元の編集 {operation.get("source_frame")} フレームを '
                                f'{operation.get("output_frames")} フレーム停止')
                elif operation.get('kind') == 'ramp':
                    location = (f'元の編集 {operation.get("source_first_frame")}–'
                                f'{operation.get("source_end_frame_exclusive")} フレーム、'
                                f'速度 {operation.get("speed_start")}→{operation.get("speed_end")}')
                else:
                    location = str(operation.get('kind', 'retime'))
                descriptions.append(f'{location}: {operation.get("reason", "")}')
            details += '<p>変更: ' + html.escape('; '.join(descriptions)) + '</p>'
        else:
            details += '<p>変更: 元の間</p>'
        if coverage:
            details += (f'<p>元の編集タイムライン: {coverage.get("omitted_original_timeline_frames", 0)} フレーム省略、'
                        f'{coverage.get("repeated_output_frames", 0)} フレーム反復</p>')
        if additions:
            cues = additions.get('rendered_cues', [])
            details += (f'<p>追加した音: {sum(c.get("role") in ("music", "sfx") for c in cues)} 箇所、'
                        f'追加した映像・文字: {sum(c.get("role") not in ("music", "sfx") for c in cues)} 箇所、'
                        f'エフェクト: {len(additions.get("rendered_effects", []))} 箇所</p>')
        cards.append(f'<article><h2>{html.escape(row["label"])}</h2>'
                     f'<video controls preload="metadata" playsinline src="{html.escape(row["video"], quote=True)}"></video>'
                     + details +
                     f'<button data-choice="{index}">この案を候補に選ぶ</button>'
                     f'<p>SHA-256: <code>{html.escape(row["sha256"])}</code></p></article>')
    data = json.dumps(rows, ensure_ascii=False).replace('<', '\\u003c')
    return '''<!doctype html><html lang="ja"><meta charset="utf-8">
<meta name="viewport" content="width=device-width"><title>間の比較</title>
<style>body{font:16px system-ui;background:#171717;color:#eee;margin:24px}
main{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:18px}
video{width:100%;max-height:60vh}button,textarea{font:inherit;margin:6px;padding:8px}
article{padding:12px;border:2px solid #555;border-radius:8px}article.selected{border-color:#fff}
code{overflow-wrap:anywhere;font-size:11px}textarea{width:min(90%,700px)}</style>
<h1>同じ元のカットを使った間の比較</h1>
<p>速度変更や停止で各案の長さと元映像の使われ方が変わります。各動画を個別に最後まで再生し、映像と音声を確認してください。表示時刻は案の間で対応しません。</p>
<main>''' + ''.join(cards) + '''</main>
<label>修正したい点<br><textarea id="note" placeholder="例: 中盤の停止を短くする"></textarea></label>
<br><button id="save">選択と修正メモを保存</button>
<p id="status" role="status"></p><p>保存は候補の採用・人の最終承認・投稿を行いません。</p>
<script>const rows=''' + data + ''';
const videos=[...document.querySelectorAll('video')],status=document.querySelector('#status');
let choice=null;
videos.forEach((video,i)=>video.addEventListener('play',()=>{
videos.forEach((other,j)=>{if(j!==i)other.pause();});}));
document.querySelectorAll('[data-choice]').forEach(b=>b.onclick=()=>{choice=Number(b.dataset.choice);
document.querySelectorAll('article').forEach((a,i)=>a.classList.toggle('selected',i===choice));
status.textContent='候補: '+rows[choice].label;});
document.querySelector('#save').onclick=()=>{if(choice===null){status.textContent='先に候補を選んでください';return;}
const result={version:1,kind:'comparison_selection_proposal',render_id:rows[choice].render_id,
render_sha256:rows[choice].sha256,output_time:videos[choice].currentTime,
note:document.querySelector('#note').value,adopted:false,final_review:false};
const url=URL.createObjectURL(new Blob([JSON.stringify(result,null,2)],{type:'application/json'}));
const a=document.createElement('a');a.href=url;a.download='comparison-selection.json';a.click();
setTimeout(()=>URL.revokeObjectURL(url),1000);
status.textContent='修正メモを保存しました。生成した動画を再確認してください。';};
</script></html>'''


def _timing_mapping(render, mapping, cfg):
    """Verify an output map is exactly the compiled timing of its original edit."""
    retime = mapping.get('retime')
    if retime is None:
        if cfg.get('retime'):
            raise ValueError('Retime setting has no retimed output mapping')
        return mapping, None
    original_path = Path(render['path']) / 'pre-retime-mapping.json'
    if not original_path.is_file():
        raise ValueError('Retimed comparison requires retained pre-retime mapping')
    original = read(original_path)
    setting = cfg.get('retime')
    if not isinstance(retime, dict) or not isinstance(setting, dict):
        raise ValueError('Retimed comparison requires source-bound retime setting')
    proposal = setting.get('proposal')
    if not isinstance(proposal, dict) or not isinstance(proposal.get('request'), dict):
        raise ValueError('Retimed comparison has invalid proposal')
    if retime.get('input_mapping_sha256') != digest(original) or setting.get('input_mapping_sha256') != digest(original):
        raise ValueError('Retime original mapping binding differs')
    supplied = proposal.get('mapping')
    if retime.get('compiled_mapping') != supplied:
        raise ValueError('Retime compiled mapping differs from proposal')
    request = proposal['request']
    if not isinstance(supplied, dict) or any(key not in supplied for key in ('input_frame_count', 'fps')):
        raise ValueError('Retime compiled mapping is incomplete')
    if not isinstance(request.get('operations'), list):
        raise ValueError('Retime operations are missing')
    compiled = compile_retime(supplied['input_frame_count'], supplied['fps'],
                              request['operations'], request.get('protected_intervals', []))
    if compiled != supplied or not compiled['timing_changed']:
        raise ValueError('Retime mapping differs from requested operations')
    if original.get('edit_basis') == 'visual':
        from .retime_mapping import remap_visual_mapping
        expected = remap_visual_mapping(original, compiled)
    else:
        from .speech_retime import remap_speech_mapping
        expected = remap_speech_mapping(original, compiled)
    if expected != mapping:
        raise ValueError('Retimed output mapping differs from original edit and operations')
    return original, request['operations']


def _timing_dimensions(mapping, fallback=None):
    """Resolve exact dimensions from visual fields or speech FCPXML frame time."""
    if 'fps' in mapping and 'frame_count' in mapping:
        fps = Fraction(str(mapping['fps']))
        count = mapping['frame_count']
    elif isinstance(mapping.get('xml'), dict) and 'frame_duration' in mapping['xml']:
        fps = 1 / Fraction(str(mapping['xml']['frame_duration']).removesuffix('s'))
        frames = Fraction(str(mapping['duration'])) * fps
        if frames.denominator != 1:
            raise ValueError('Speech original duration is not frame aligned')
        count = int(frames)
    elif fallback is not None:
        fps, count = fallback
    else:
        raise ValueError('Timing comparison needs original frame dimensions')
    if (fps <= 0 or type(count) is not int or count <= 0 or
            abs(Fraction(str(mapping['duration'])) - Fraction(count, 1) / fps) > Fraction(1, 1000000)):
        raise ValueError('Timing comparison frame dimensions differ from duration')
    return fps, count


def _timing_evidence(renders, source):
    if not 2 <= len(renders) <= 4:
        raise ValueError('Compare two to four renders')
    rows = []
    for render in renders:
        cfg = read(render['project']['path'])
        mapping = read(render['files']['mapping']['path'])
        original, operations = _timing_mapping(render, mapping, cfg)
        pattern = frozen_pattern(cfg)
        source_ids = {row['asset_id'] for row in original.get('sequence', [])
                      if original.get('edit_basis') == 'visual'}
        registry = {a['asset_id']: a for a in cfg.get('assets', [])}
        if not source_ids <= registry.keys():
            raise ValueError('Comparison source asset is missing')
        fixed = {'source_sha256': source['sha256'],
                 'visual_sources': {key: registry[key]['sha256'] for key in sorted(source_ids)},
                 'original_mapping_sha256': digest(original),
                 'settings': {key: deepcopy(cfg.get(key, 1 if key == 'visual_pipeline_version' else None))
                              for key in FIXED_SETTINGS if key != 'composition_guides'},
                 'preview': render.get('preview')}
        original_fps, base_frames = _timing_dimensions(original)
        fps, output_frames = _timing_dimensions(mapping, (original_fps, base_frames))
        if fps != original_fps:
            raise ValueError('Timing comparison FPS differs from original edit')
        selected = (mapping['retime']['compiled_mapping']['frame_map'] if operations is not None
                    else list(range(base_frames)))
        if len(selected) != output_frames:
            raise ValueError('Timing frame count differs from output mapping')
        production = read(render['files']['production']['path']) if 'production' in render['files'] else {}
        rows.append({'render_id': render['id'], 'video_sha256': render['files']['video']['sha256'],
                     'pattern': pattern['id'], 'fixed': fixed,
                     'duration_seconds': float(Fraction(output_frames, 1) / fps),
                     'original_duration_seconds': float(Fraction(base_frames, 1) / fps),
                     'retime_operations': deepcopy(operations or []),
                     'production_changes': {'editing_pattern': pattern['id'],
                                            'cue_plan': deepcopy(cfg.get('cue_plan')),
                                            'video_effects': deepcopy(cfg.get('video_effects')),
                                            'rendered_cues': deepcopy(production.get('cues', [])),
                                            'rendered_effects': deepcopy(production.get('effects', {}).get('events', [])),
                                            'composition_guides': deepcopy(cfg.get('composition_guides') or [])},
                     'source_coverage': {'original_selected_frames': base_frames,
                                         'output_frames': output_frames,
                                         'distinct_original_timeline_frames': len(set(selected)),
                                         'omitted_original_timeline_frames': base_frames - len(set(selected)),
                                         'repeated_output_frames': output_frames - len(set(selected)),
                                         'explanation': 'These counts refer to the retained original cut timeline; speed ramps may omit frames and holds may repeat frames.'}})
    if len({digest(row['fixed']) for row in rows}) != 1:
        raise ValueError('Timing comparison must fix original source coverage, color, base audio settings and preview mode')
    if not any(row['pattern'] == 'natural' and not row['retime_operations'] for row in rows):
        raise ValueError('Include a natural no-addition baseline in the comparison')
    return {'version': 2, 'mode': 'timing', 'conditions': rows[0]['fixed'], 'candidates': rows,
            'review_status': 'awaiting_selection_and_exact_render_review',
            'timeline_explanation': 'Each output has its own timeline and duration. Equal output timestamps do not identify the same original frames.',
            'audio_basis': 'Same base audio settings; timing changes may alter audio duration and rhythm.'}


def comparison_evidence(renders, source, mode='effects'):
    if mode == 'timing':
        return _timing_evidence(renders, source)
    if mode != 'effects':
        raise ValueError('Unknown comparison mode')
    if not 2 <= len(renders) <= 4:
        raise ValueError('Compare two to four renders')
    rows = []
    for render in renders:
        cfg = read(render['project']['path'])
        mapping = read(render['files']['mapping']['path'])
        pattern = frozen_pattern(cfg)
        source_ids = {row['asset_id'] for row in mapping.get('sequence', [])
                      if mapping.get('edit_basis') == 'visual'}
        registry = {a['asset_id']: a for a in cfg.get('assets', [])}
        if not source_ids <= registry.keys():
            raise ValueError('Comparison source asset is missing')
        fixed = {'source_sha256': source['sha256'],
                 'visual_sources': {key: registry[key]['sha256'] for key in sorted(source_ids)},
                 'mapping_sha256': digest(mapping),
                 'settings': {key: deepcopy(cfg.get(key,1 if key=='visual_pipeline_version' else None)) for key in FIXED_SETTINGS},
                 'preview': render.get('preview')}
        production = read(render['files']['production']['path']) if 'production' in render['files'] else {}
        rows.append({'render_id': render['id'], 'video_sha256': render['files']['video']['sha256'],
                     'pattern': pattern['id'], 'fixed': fixed,
                     'selection': deepcopy(production.get('selection_report')),
                     'placement_reasons': deepcopy(production.get('reasons', [])),
                     'cue_reasons': [{'id': cue['id'], 'reason': cue.get('reason', '')}
                                    for cue in production.get('cues', [])]})
    if len({digest(row['fixed']) for row in rows}) != 1:
        raise ValueError('Comparison must fix source frames, color, base audio settings and preview mode')
    if not any(row['pattern'] == 'natural' for row in rows):
        raise ValueError('Include a natural no-addition baseline in the comparison')
    return {'version': 1, 'conditions': rows[0]['fixed'], 'candidates': rows,
            'review_status': 'awaiting_selection_and_exact_render_review',
            'audio_basis': 'Same base normalization settings; added music and intentional ducking may differ.'}
