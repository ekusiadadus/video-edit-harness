"""Evidence for fair creative comparisons; never a perceptual approval."""
from copy import deepcopy
from collections import Counter
from fractions import Fraction
from pathlib import Path

from .common import read, fingerprint
from .production import frozen_pattern
from .render_cache import digest
from .time_mapping import compile_retime


def comparison_page(rows, mode='effects'):
    """Offline synchronized comparison; selection export is feedback, not approval."""
    if mode not in ('effects', 'timing', 'structure'):
        raise ValueError('Unknown comparison mode')
    if mode in ('timing', 'structure'):
        return _timing_page(rows, mode=mode)
    import html
    import json
    cards = []
    for index, row in enumerate(rows):
        names={'dissolve':'ディゾルブ','push':'プッシュ'}
        directions={'left':'左','right':'右','up':'上','down':'下'}
        transitions=''.join('<li>'+html.escape(names.get(event['type'],event['type'])+
                            (' / '+directions.get(event.get('direction'),event.get('direction',''))
                             if event.get('direction') else '')+
                            ' / '+event['left_segment_id'])+'</li>' for event in row.get('transitions',[]))
        detail=('<p>カット前後の実素材を重ねた候補</p><ul>'+transitions+'</ul>') if transitions else ''
        cards.append(f'<article><h2>{html.escape(row["label"])}</h2>'+detail+
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
code{overflow-wrap:anywhere;font-size:11px}textarea{width:min(90%,700px)}
#effect-panel{border:1px solid #777;border-radius:8px;padding:12px;margin:18px 0}
#effect-list{list-style:none;padding:0}#effect-list li{border-top:1px solid #555;padding:8px 0}
#effect-list label{display:inline-block;margin-right:12px}#effect-list input[type=range]{vertical-align:middle;width:min(34vw,220px)}
</style>
<h1>同じ編集範囲の候補</h1><p>同じ時刻で比較します。音声は一案ずつ再生します。</p>
<button id="play">再生／停止</button><button id="start">先頭に戻す</button>
<label>再生位置 <input id="seek" type="range" min="0" max="0" step="0.01" value="0"></label>
<output id="time">0.00秒</output><p id="status" role="status">読み込み中</p>
<main>''' + ''.join(cards) + '''</main>
<section id="effect-panel" aria-label="選んだ候補のエフェクト調整">
<h2>選んだ候補のエフェクト調整</h2>
<p>調整は保存する提案です。この動画の見た目は変わりません。反映後の動画を再確認してください。</p>
<p id="effect-summary">候補を選ぶと調整できるエフェクトを表示します。</p>
<ul id="effect-list"></ul>
<button id="undo-effects" type="button" disabled>直前の調整を戻す</button>
<button id="reset-effects" type="button" disabled>この候補の調整をすべて戻す</button>
</section>
<label>修正したい点<br><textarea id="note" placeholder="例: 中盤のズームを弱める"></textarea></label>
<br><button id="save">選択と修正メモを保存</button>
<p>保存は候補の採用・人の最終承認・投稿を行いません。</p>
<script>const rows=''' + data + ''';
const videos=[...document.querySelectorAll('video')],seek=document.querySelector('#seek'),status=document.querySelector('#status');
let playing=false,choice=null,audio=0;
const staged=rows.map(()=>({values:new Map(),ranges:new Map(),anchors:new Map(),disabled:new Set(),history:[]}));
const effectList=document.querySelector('#effect-list'),effectSummary=document.querySelector('#effect-summary');
const undoEffects=document.querySelector('#undo-effects'),resetEffects=document.querySelector('#reset-effects');
function controlsFor(index){return Array.isArray(rows[index].effect_controls)?rows[index].effect_controls:[];}
function snapshot(state){return {values:new Map(state.values),ranges:new Map(state.ranges),anchors:new Map(state.anchors),disabled:new Set(state.disabled)};}
function remember(state){state.history.push(snapshot(state));}
function frameTime(frame,fps){const [n,d='1']=String(fps).split('/');return String(BigInt(frame)*BigInt(d))+'/'+n;}
function operationsFor(index){const state=staged[index];return controlsFor(index).flatMap(event=>{
if(state.disabled.has(event.id))return [{action:'remove',id:event.id}];
const changes={},strength=state.values.get(event.id),range=state.ranges.get(event.id),anchor=state.anchors.get(event.id);
if(strength!==undefined && strength!==Number(event.strength))changes.strength=strength;
if(range){if(!Number.isInteger(range.first) || !Number.isInteger(range.end) || range.first<0 || range.end-range.first<(event.minimum_frames ?? 1) || range.end>event.frame_count)
throw new Error('範囲は動画内の開始・終了フレームで指定してください');
if(range.first!==event.first_frame || range.end!==event.end_frame_exclusive){changes.output_start=frameTime(range.first,event.fps);changes.output_end=frameTime(range.end,event.fps);}}
if(anchor){if(Object.values(anchor).some(v=>!Number.isFinite(v) || v<0 || v>1))throw new Error('位置は0〜1の範囲で指定してください');
const changed=Object.fromEntries(Object.entries(anchor).filter(([key,v])=>v!==event.anchor[key]));
if(Object.keys(changed).length)changes.parameters=changed;}
return Object.keys(changes).length?[{action:'update',id:event.id,changes}]:[];});}
function changedCount(index){try{return operationsFor(index).length;}catch(e){return '範囲・位置を確認';}}
function renderEffects(){effectList.replaceChildren();
if(choice===null){effectSummary.textContent='候補を選ぶと調整できるエフェクトを表示します。';
undoEffects.disabled=true;resetEffects.disabled=true;return;}
const controls=controlsFor(choice),state=staged[choice];
effectSummary.textContent=controls.length
? rows[choice].label+'：'+controls.length+' 件。変更 '+changedCount(choice)+' 件。'
: rows[choice].label+'：調整できるエフェクトはありません。';
for(const event of controls){const item=document.createElement('li');
const names={smooth_zoom:'滑らかなズーム',zoom_pulse:'ズームアクセント',saturation_pulse:'彩度アクセント',monochrome:'白黒',split_screen:'ミラー分割',comparison_wipe:'比較ワイプ',keyword_title:'キーワード',tracked_title:'追従ラベル',tracked_zoom:'追従ズーム',tracked_background:'背景強調',motion_trail:'残像',color_frame:'装飾枠'};
const title=document.createElement('span');title.textContent=(names[event.kind] ?? String(event.kind))+' ';item.append(title);
if(event.adjustable_strength){const strengthLabel=document.createElement('label');strengthLabel.textContent='強さ ';
const slider=document.createElement('input');slider.type='range';slider.min=String(Math.min(0.01,Number(event.strength)));slider.max='1';slider.step='any';
slider.value=String(state.values.get(event.id) ?? event.strength);slider.disabled=state.disabled.has(event.id);
const value=document.createElement('output');value.textContent=slider.value;let adjusting=false;
slider.addEventListener('input',()=>{if(!adjusting){remember(state);adjusting=true;}state.values.set(event.id,Number(slider.value));
value.textContent=slider.value;effectSummary.textContent=rows[choice].label+'：'+controls.length+' 件。変更 '+changedCount(choice)+' 件。';
undoEffects.disabled=false;resetEffects.disabled=changedCount(choice)===0;});
slider.addEventListener('change',()=>{adjusting=false;});
strengthLabel.append(slider,value);item.append(strengthLabel);}
function numeric(labelText,current,min,max,step,changed){const label=document.createElement('label');label.textContent=labelText;
const input=document.createElement('input');input.type='number';input.value=String(current);input.min=String(min);input.max=String(max);input.step=step;input.disabled=state.disabled.has(event.id);
input.addEventListener('change',()=>{remember(state);changed(input.value.trim()===''?NaN:Number(input.value));undoEffects.disabled=false;resetEffects.disabled=false;
effectSummary.textContent='変更 '+changedCount(choice)+' 件。反映後の映像を確認してください。';});label.append(input);item.append(label);}
if(event.adjustable_range){const range=state.ranges.get(event.id) ?? {first:event.first_frame,end:event.end_frame_exclusive};
numeric('開始フレーム ',range.first,0,event.frame_count-1,'1',v=>state.ranges.set(event.id,{...(state.ranges.get(event.id) ?? range),first:v}));
numeric('終了フレーム（含まない） ',range.end,1,event.frame_count,'1',v=>state.ranges.set(event.id,{...(state.ranges.get(event.id) ?? range),end:v}));}
if(event.anchor){for(const [key,label] of [['anchor_x','ズーム位置・横（左0／右1） '],['anchor_y','ズーム位置・縦（上0／下1） ']]){
const anchor=state.anchors.get(event.id) ?? event.anchor;
numeric(label,anchor[key],0,1,'any',v=>state.anchors.set(event.id,{...(state.anchors.get(event.id) ?? anchor),[key]:v}));}}
const offLabel=document.createElement('label');offLabel.textContent='オフ ';
const off=document.createElement('input');off.type='checkbox';off.checked=state.disabled.has(event.id);
off.addEventListener('change',()=>{remember(state);if(off.checked)state.disabled.add(event.id);
else state.disabled.delete(event.id);renderEffects();});offLabel.append(off);item.append(offLabel);
effectList.append(item);}
undoEffects.disabled=state.history.length===0;
resetEffects.disabled=state.history.length===0 || changedCount(choice)===0;}
undoEffects.onclick=()=>{if(choice===null)return;const state=staged[choice],previous=state.history.pop();
if(!previous)return;state.values=previous.values;state.ranges=previous.ranges;state.anchors=previous.anchors;state.disabled=previous.disabled;renderEffects();};
resetEffects.onclick=()=>{if(choice===null)return;const state=staged[choice];
if(!changedCount(choice))return;remember(state);state.values.clear();state.ranges.clear();state.anchors.clear();state.disabled.clear();renderEffects();};
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
document.querySelectorAll('article').forEach((a,i)=>a.classList.toggle('selected',i===choice));
renderEffects();message('候補: '+rows[choice].label);});
function tick(){if(playing){const t=videos[0].currentTime;seek.value=t;videos.slice(1).forEach(v=>{if(Math.abs(v.currentTime-t)>.12)v.currentTime=t;});}
document.querySelector('#time').textContent=Number(seek.value).toFixed(2)+'秒';requestAnimationFrame(tick);}tick();
document.querySelector('#save').onclick=()=>{if(choice===null){message('先に候補を選んでください');return;}
let operations;try{operations=operationsFor(choice);}catch(e){message(e.message);return;}
const result={version:operations.some(op=>op.changes && Object.keys(op.changes).some(k=>k!=='strength'))?3:(operations.length?2:1),kind:'comparison_selection_proposal',render_id:rows[choice].render_id,
render_sha256:rows[choice].sha256,output_time:Number(seek.value),note:document.querySelector('#note').value,
adopted:false,final_review:false};
if(operations.length)result.effect_operations=operations;
const url=URL.createObjectURL(new Blob([JSON.stringify(result,null,2)],{type:'application/json'}));
const a=document.createElement('a');a.href=url;a.download='comparison-selection.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
message('修正メモを保存しました。ハーネスで反映後、生成した動画を再確認してください。');};
</script></html>'''


FIXED_SETTINGS = ('input_color', 'white_balance_gains', 'use_case', 'style',
                  'style_intensity', 'adjustments', 'audio', 'review_regions',
                  'region_corrections', 'composition_guides', 'visual_pipeline_version', 'audio_cuts')


def _timing_page(rows, mode='timing'):
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
            if additions.get('audio_cuts'):
                details += '<p>J/Lカット: ' + html.escape('; '.join(
                    f'{event["kind"]}: {event["reason"]}' for event in additions['audio_cuts'])) + '</p>'
        if mode == 'structure':
            details += '<h3>素材の順序・範囲</h3><ol>' + ''.join(
                '<li>' + html.escape(_structure_label(span)) + '</li>'
                for span in row.get('structure', [])) + '</ol>'
            changes = row.get('source_span_changes', {})
            details += (f'<p>自然版に対する範囲の変更: 追加 {len(changes.get("added", []))}、'
                        f'除去 {len(changes.get("removed", []))}。同じ範囲の反復も別に数えます。</p>')
            for key, title in (('added', '追加した範囲'), ('removed', '除去した範囲')):
                if changes.get(key):
                    details += '<h3>' + title + '</h3><ul>' + ''.join(
                        '<li>' + html.escape(_structure_label(span)) + '</li>'
                        for span in changes[key]) + '</ul>'
        cards.append(f'<article><h2>{html.escape(row["label"])}</h2>'
                     f'<video controls preload="metadata" playsinline src="{html.escape(row["video"], quote=True)}"></video>'
                     + details +
                     f'<button data-choice="{index}">この案を候補に選ぶ</button>'
                     f'<p>SHA-256: <code>{html.escape(row["sha256"])}</code></p></article>')
    data = json.dumps(rows, ensure_ascii=False).replace('<', '\\u003c')
    page = '''<!doctype html><html lang="ja"><meta charset="utf-8">
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
    if mode == 'structure':
        page = page.replace('<title>間の比較</title>', '<title>構成の比較</title>').replace(
            '<h1>同じ元のカットを使った間の比較</h1>', '<h1>構成・順序・間の比較</h1>').replace(
            '速度変更や停止で各案の長さと元映像の使われ方が変わります。',
            '素材の選択範囲・順序・速度変更によって、各案の内容と長さが変わります。')
    return page


def _transition_original(render, mapping, cfg):
    """Keep exact base-cut comparison while disclosing the composed picture."""
    setting = cfg.get('transitions')
    if 'transitions' not in mapping:
        if setting is not None:
            raise ValueError('Transition setting has no composed output mapping')
        return mapping, []
    from .transition_feedback import attach_transitions
    original_path = Path(render['path'])/'pre-transition-mapping.json'
    if not original_path.is_file() or not isinstance(setting, dict):
        raise ValueError('Transition comparison needs retained original mapping and setting')
    original = read(original_path)
    compiled = mapping['transitions']['compiled']
    if setting.get('compiled') != compiled or attach_transitions(original, compiled) != mapping:
        raise ValueError('Transition comparison mapping differs from source-bound proposal')
    actual = fingerprint(Path(render['path'])/'visual-base.mp4')
    bound = setting.get('input_video', {})
    if any(actual[key] != bound.get(key) for key in ('sha256', 'bytes')):
        raise ValueError('Transition comparison base video changed')
    return original, deepcopy(compiled['request']['events'])


def _timing_mapping(render, mapping, cfg):
    """Verify an output map is exactly the compiled timing of its original edit."""
    retime = mapping.get('retime')
    if retime is None:
        if cfg.get('retime'):
            raise ValueError('Retime setting has no retimed output mapping')
        return _transition_original(render, mapping, cfg)[0], None
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
        # Summed frame-aligned float ranges may serialize with tiny residue.
        # The common duration tolerance below still rejects fractional frames.
        count = round(frames)
    elif fallback is not None:
        fps, count = fallback
    else:
        raise ValueError('Timing comparison needs original frame dimensions')
    if (fps <= 0 or type(count) is not int or count <= 0 or
            abs(Fraction(str(mapping['duration'])) - Fraction(count, 1) / fps) > Fraction(1, 1000000)):
        raise ValueError('Timing comparison frame dimensions differ from duration')
    return fps, count


def _structure_label(span):
    """Display exact original source ranges without exposing local paths."""
    if 'asset_id' in span:
        fps = Fraction(span['source_fps'])
        start = float(Fraction(span['source_first_frame'], 1) / fps)
        end = float(Fraction(span['source_end_frame_exclusive'], 1) / fps)
        text = (f'{span.get("id", "区間")}: {span["asset_id"]} / {start:.3f}–{end:.3f} 秒 '
                f'（{span["source_first_frame"]}–{span["source_end_frame_exclusive"]} フレーム、'
                f'{fps} fps、終了を含まない）')
    else:
        text = f'{span.get("id", "区間")}: {span["source_start"]}–{span["source_end"]} 秒'
    return text + (f' / {span["reason"]}' if span.get('reason') else '')


def _span_inventory(spans):
    """Count source ranges, preserving duplicate uses but ignoring sequence IDs."""
    return Counter(digest({key: value for key, value in span.items() if key not in ('id','reason')}) for span in spans)


def _timing_evidence(renders, source, *, mode='timing'):
    if not 2 <= len(renders) <= 4:
        raise ValueError('Compare two to four renders')
    rows = []
    source_pool = set()
    if mode == 'structure':
        for render in renders:
            mapping = read(render['files']['mapping']['path'])
            original, _ = _timing_mapping(render, mapping, read(render['project']['path']))
            if original.get('edit_basis') == 'visual':
                source_pool.update(span['asset_id'] for span in original['sequence'])
    for render in renders:
        cfg = read(render['project']['path'])
        mapping = read(render['files']['mapping']['path'])
        original, operations = _timing_mapping(render, mapping, cfg)
        pattern = frozen_pattern(cfg)
        source_ids = {row['asset_id'] for row in original.get('sequence', [])
                      if original.get('edit_basis') == 'visual'}
        registry = {a['asset_id']: a for a in cfg.get('assets', [])}
        required_sources = source_pool if mode == 'structure' else source_ids
        if not required_sources <= registry.keys():
            raise ValueError('Comparison source asset is missing')
        fixed = {'source_sha256': source['sha256'],
                 'visual_sources': {key: registry[key]['sha256'] for key in sorted(required_sources)},
                 'original_mapping_sha256': digest(original),
                 'settings': {key: deepcopy(cfg.get(key, 1 if key == 'visual_pipeline_version' else None))
                              for key in FIXED_SETTINGS if key != 'composition_guides'
                              and not (mode == 'structure' and key == 'audio_cuts')},
                 'preview': render.get('preview')}
        if mode == 'structure':
            fixed.pop('original_mapping_sha256')
            fixed['edit_basis'] = original.get('edit_basis', 'speech')
        original_fps, base_frames = _timing_dimensions(original)
        if mode == 'structure':
            fixed['fps'] = str(original_fps)
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
                     'depth_layer': deepcopy(cfg.get('depth_layer')),
                     'duration_seconds': float(Fraction(output_frames, 1) / fps),
                     'original_duration_seconds': float(Fraction(base_frames, 1) / fps),
                     'retime_operations': deepcopy(operations or []),
                     'production_changes': {'editing_pattern': pattern['id'],
                                            'audio_cuts': deepcopy((cfg.get('audio_cuts') or {}).get('request',{}).get('events',[])),
                                            'transitions': _transition_original(render, mapping, cfg)[1],
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
        if mode == 'structure':
            plan = render.get('plan')
            if not plan or not plan.get('sha256'):
                raise ValueError('Structure comparison requires sealed render plans')
            rows[-1]['plan_sha256'] = plan['sha256']
            rows[-1]['original_mapping_sha256'] = digest(original)
            if fixed['edit_basis'] == 'visual':
                for span in original['sequence']:
                    if span['source_sha256'] != registry[span['asset_id']]['sha256']:
                        raise ValueError('Structure mapping source SHA differs from registered asset')
                spans = [{key: deepcopy(span[key]) for key in ('id','asset_id','source_sha256',
                    'source_fps','source_first_frame','source_end_frame_exclusive')}
                         for span in original['sequence']]
            else:
                if original.get('source', {}).get('sha256') != source['sha256']:
                    raise ValueError('Structure speech mapping source SHA differs from session source')
                identities = original.get('sequence_ids', [f'span-{i+1}' for i in range(len(original['keep']))])
                spans = [{'id': identity, 'source_start': span[0], 'source_end': span[1]}
                         for identity, span in zip(identities, original['keep'], strict=True)]
            if plan.get('path'):
                reasons = {span['id']: span.get('reason', '') for span in read(plan['path']).get('sequence', [])}
                for span in spans:
                    span['reason'] = reasons.get(span['id'], '')
            rows[-1]['structure'] = spans
    if len({digest(row['fixed']) for row in rows}) != 1:
        raise ValueError('Timing comparison must fix original source coverage, color, base audio settings and preview mode'
                         if mode == 'timing' else 'Structure comparison must fix source pool, edit basis, color, base audio settings and preview mode')
    if not any(row['pattern'] == 'natural' and not row['retime_operations'] for row in rows):
        raise ValueError('Include a natural no-addition baseline in the comparison')
    if mode == 'structure':
        baseline = next(row for row in rows if row['pattern'] == 'natural' and not row['retime_operations'])
        inventory = _span_inventory(baseline['structure'])
        for row in rows:
            current = _span_inventory(row['structure'])
            ranges = {digest({key: value for key, value in span.items() if key not in ('id','reason')}):
                      {key: deepcopy(value) for key, value in span.items() if key not in ('id','reason')}
                      for span in baseline['structure'] + row['structure']}
            row['source_span_changes'] = {'baseline_render_id': baseline['render_id'],
                'added': [ranges[key] for key in (current - inventory).elements()],
                'removed': [ranges[key] for key in (inventory - current).elements()],
                'same_range_multiplicity': current == inventory,
                'explanation': 'Exact original source spans, including duplicate occurrences. Retiming frame omissions/repetitions are reported separately.'}
    return {'version': 2 if mode == 'timing' else 3, 'mode': mode, 'conditions': rows[0]['fixed'], 'candidates': rows,
            'review_status': 'awaiting_selection_and_exact_render_review',
            'timeline_explanation': 'Each output has its own timeline and duration. Equal output timestamps do not identify the same original frames.',
            'audio_basis': 'Same base audio settings; timing changes may alter audio duration and rhythm.'}


def comparison_evidence(renders, source, mode='effects'):
    if mode in ('timing', 'structure'):
        return _timing_evidence(renders, source, mode=mode)
    if mode != 'effects':
        raise ValueError('Unknown comparison mode')
    if not 2 <= len(renders) <= 4:
        raise ValueError('Compare two to four renders')
    rows = []
    for render in renders:
        cfg = read(render['project']['path'])
        mapping = read(render['files']['mapping']['path'])
        original, transitions = _transition_original(render, mapping, cfg)
        pattern = frozen_pattern(cfg)
        source_ids = {row['asset_id'] for row in mapping.get('sequence', [])
                      if mapping.get('edit_basis') == 'visual'}
        registry = {a['asset_id']: a for a in cfg.get('assets', [])}
        if not source_ids <= registry.keys():
            raise ValueError('Comparison source asset is missing')
        fixed = {'source_sha256': source['sha256'],
                 'visual_sources': {key: registry[key]['sha256'] for key in sorted(source_ids)},
                 'mapping_sha256': digest(original),
                 'settings': {key: deepcopy((cfg.get(key) or []) if key=='composition_guides'
                                            else cfg.get(key,1 if key=='visual_pipeline_version' else None))
                              for key in FIXED_SETTINGS},
                 'preview': render.get('preview')}
        production = read(render['files']['production']['path']) if 'production' in render['files'] else {}
        rows.append({'render_id': render['id'], 'video_sha256': render['files']['video']['sha256'],
                     'pattern': pattern['id'], 'fixed': fixed,
                     'output_mapping_sha256': digest(mapping), 'transitions': transitions,
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
