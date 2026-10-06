"""Evidence for fair creative comparisons; never a perceptual approval."""
from copy import deepcopy

from .common import read
from .production import frozen_pattern
from .render_cache import digest


def comparison_page(rows):
    """Offline synchronized comparison; selection export is feedback, not approval."""
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
                  'region_corrections', 'composition_guides')


def comparison_evidence(renders, source):
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
                 'settings': {key: deepcopy(cfg.get(key)) for key in FIXED_SETTINGS},
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
