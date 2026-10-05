"""Render the offline sample from its API-measured words; no cloud calls."""
import argparse
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from video_harness.common import read, fingerprint
from video_harness.session import Session
from video_harness.transcript import load_transcript


def sentence_padding(first, last, ranges, duration):
    """Preserve known original PCM speech extents despite inaccurate ASR onsets."""
    import math
    if not isinstance(ranges,list) or len(ranges)!=2:
        raise ValueError('Public fixture needs two exact original speech ranges')
    previous=0
    padding=[]
    for words, row in zip((first,last),ranges):
        if not isinstance(row,list) or len(row)!=2 or any(isinstance(t,bool) or not isinstance(t,(int,float)) or not math.isfinite(t) for t in row):
            raise ValueError('Invalid original speech range')
        start,end=row
        if not previous<=start<end<=duration:
            raise ValueError('Original speech ranges overlap or exceed the source')
        if not start<=words[0]['start']<words[-1]['end']<=end:
            raise ValueError('Measured words fall outside the original speech recording')
        padding.append((words[0]['start']-start+.16,end-words[-1]['end']+.16))
        previous=end
    return padding


def render_sample(sample, session_folder, mode='youtube'):
    sample=Path(sample).resolve()
    transcript=load_transcript(sample/'transcript/transcript.json',sample/'sample.mp4')
    words=transcript['words']
    # The published fixture has two actual spoken sentences, separated by a long gap.
    gaps=[(right['start']-left['end'],index) for index,(left,right) in enumerate(zip(words,words[1:]))]
    gap,index=max(gaps)
    if gap<1:
        raise ValueError('Expected the verified sample sentence gap')
    first,last=words[:index+1],words[index+1:]
    provenance=read(sample/'provenance.json')
    if provenance.get('source_sha256') != fingerprint(sample/'sample.mp4')['sha256']:
        raise ValueError('Speech range provenance belongs to a different source')
    ranges=provenance.get('speech_ranges_seconds')
    padding=sentence_padding(first,last,ranges,transcript['duration'])
    spans=[{'id':'tip-one','start_word_id':first[0]['id'],'end_word_id':first[-1]['id'],
            'pad_before':padding[0][0],'pad_after':padding[0][1],'reason':'Retain the complete first practical tip'}]
    omissions=[]
    if mode=='youtube':
        spans.append({'id':'tip-two','start_word_id':last[0]['id'],'end_word_id':last[-1]['id'],
                      'pad_before':padding[1][0],'pad_after':padding[1][1],'reason':'Retain the second tip; shorten the long pause'})
    elif mode=='tiktok':
        omissions=[{'word_ids':[w['id'] for w in last],'reason':'One coherent tip for this short; second tip belongs in the longer version','goal_ids':['goal-1']}]
    else:raise ValueError('Mode must be youtube or tiktok')
    session=Session.start(sample/'project.json',session_folder,
        {'goal':'Keep complete practical advice while reducing unnecessary pauses'},actor='automation')
    session.attach_transcript(sample/'transcript/transcript.json',actor='automation')
    session.propose({'chapters':[{'id':'desk','title':'A tidy desk','goal_ids':['goal-1'],'spans':spans}],
                     'omissions':omissions},actor='automation')
    session.approve('automation','Measured fixture sentence anchors selected; not human approval')
    render=session.render(preview=False,actor='automation')
    return {'mode':mode,'render':render,'session':str(Path(session_folder).resolve()),
            'input_duration':transcript['duration'],'word_count':len(words),
            'retained_words':len(words) if mode=='youtube' else len(first),
            'quality_review':'not_human_reviewed'}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sample',type=Path,required=True)
    parser.add_argument('--session',type=Path,required=True)
    parser.add_argument('--mode',choices=['youtube','tiktok'],default='youtube')
    args=parser.parse_args()
    result=render_sample(args.sample,args.session,args.mode)
    (Path(args.session)/'sample-render.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(result,ensure_ascii=False,indent=2))
