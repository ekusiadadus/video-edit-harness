"""Local frame-exact retiming with explicit source-bound proposals."""
from fractions import Fraction
import hashlib
import json
from pathlib import Path
import subprocess
import shutil
import tempfile
import wave

import numpy as np

from .common import fingerprint
from .time_mapping import compile_retime
from .video_effects import _probe, _stream, _verified_rate


def prepare_retime(source, request, actor, reason):
    from .session import actor_name, require_note
    actor_name(actor);require_note(reason)
    if not isinstance(request,dict) or set(request)-{'operations','protected_intervals','captions','audio_backend'} or 'operations' not in request:
        raise ValueError('Retime request needs operations and optional protected_intervals/captions')
    if request.get('audio_backend','rubberband') not in {'rubberband','phase_vocoder'}:
        raise ValueError('Audio backend must be rubberband or phase_vocoder')
    source=Path(source).resolve(strict=True);ref=fingerprint(source)
    info=_probe(source,count=True);video=_stream(info,'video')
    if not video:raise ValueError('Retime source needs video')
    if video.get('color_transfer') in {'smpte2084','arib-std-b67'}:
        raise ValueError('HDR retiming needs an explicit color pipeline; use a Rec.709 stage')
    if any(float(row.get('rotation',0))%360 for row in video.get('side_data_list',[])):
        raise ValueError('Bake display rotation before retiming')
    if video.get('sample_aspect_ratio') not in {None,'N/A','1:1'}:
        raise ValueError('Convert non-square pixels before retiming')
    count=int(video['nb_read_frames']);rate=_verified_rate(source,video,count)
    mapping=compile_retime(count,str(rate),request['operations'],request.get('protected_intervals',[]))
    captions=remap_captions(request.get('captions',[]),mapping)
    if fingerprint(source)!=ref:raise ValueError('Source changed during retime preparation')
    return {'version':1,'source':ref,'request':request,'mapping':mapping,'captions':captions,
            'actor':actor,'reason':reason,'review_required':True,'adopted':False}


def remap_captions(captions, mapping):
    """Move observed source-frame captions through the exact discrete video map."""
    if not isinstance(captions,list):raise ValueError('Captions must be an array')
    result=[];seen=set();frames=mapping['frame_map'];rate=Fraction(mapping['fps'])
    for caption in captions:
        if not isinstance(caption,dict) or set(caption)!={'id','text','source_first_frame','source_end_frame_exclusive'}:
            raise ValueError('Caption needs id, text and source-frame bounds')
        if not isinstance(caption['id'],str) or not caption['id'].strip() or caption['id'] in seen:
            raise ValueError('Caption IDs must be unique and nonempty')
        if not isinstance(caption['text'],str) or not caption['text'].strip():raise ValueError('Caption text must be nonempty')
        first=caption['source_first_frame'];end=caption['source_end_frame_exclusive']
        if type(first) is not int or type(end) is not int or not 0<=first<end<=mapping['input_frame_count']:
            raise ValueError('Caption bounds must be observed source frames')
        seen.add(caption['id'])
        selected=[i for i,f in enumerate(frames) if first<=f<end]
        result.append({**caption,'output_first_frame':selected[0] if selected else None,
                       'output_end_frame_exclusive':selected[-1]+1 if selected else None,
                       'output_start':str(Fraction(selected[0],1)/rate) if selected else None,
                       'output_end':str(Fraction(selected[-1]+1,1)/rate) if selected else None,
                       'status':'mapped' if selected else 'omitted_by_retime'})
    return sorted(result,key=lambda caption: caption['output_first_frame'] if caption['output_first_frame'] is not None else mapping['output_frame_count'])


def captions_srt(captions):
    def stamp(value):
        ms=round(Fraction(value)*1000);hours,ms=divmod(ms,3600000);minutes,ms=divmod(ms,60000);seconds,ms=divmod(ms,1000)
        return f'{hours:02}:{minutes:02}:{seconds:02},{ms:03}'
    rows=[]
    for caption in captions:
        if caption['status']!='mapped':continue
        rows.append(f'{len(rows)+1}\n{stamp(caption["output_start"])} --> {stamp(caption["output_end"])}\n{caption["text"]}\n')
    return '\n'.join(rows)


def _read_frame(pipe, size):
    data=bytearray()
    while len(data)<size:
        chunk=pipe.read(size-len(data))
        if not chunk:break
        data.extend(chunk)
    if len(data)!=size:raise ValueError('Video ended before the compiled source frame')
    return bytes(data)


def render_retime(source, proposal, output, *, pcm_output=None):
    source=Path(source).resolve(strict=True);target=Path(output).resolve()
    if source==target or target.exists():raise ValueError('Retime output must be a new file')
    retained_pcm=Path(pcm_output).resolve() if pcm_output is not None else None
    if retained_pcm is not None and (retained_pcm.exists() or retained_pcm in (source,target)):
        raise ValueError('Retimed PCM output must be a separate new file')
    if not isinstance(proposal,dict) or set(proposal)!={'version','source','request','mapping','captions','actor','reason','review_required','adopted'} or proposal['version']!=1:
        raise ValueError('Use a source-bound retime proposal')
    if proposal['review_required'] is not True or proposal['adopted'] is not False:raise ValueError('Retime proposal must remain unadopted')
    input_ref=fingerprint(source)
    if any(input_ref[key]!=proposal['source'].get(key) for key in ('sha256','bytes')):raise ValueError('Retime source changed')
    observed=prepare_retime(source,proposal['request'],proposal['actor'],proposal['reason'])
    observed['source']=proposal['source']
    if observed!=proposal:raise ValueError('Retime proposal mapping or captions changed')
    mapping=proposal['mapping'];rate=Fraction(mapping['fps']);count=mapping['output_frame_count']
    info=_probe(source,count=True);video=_stream(info,'video');width=int(video['width']);height=int(video['height'])
    if width%2 or height%2:raise ValueError('Retime requires even picture dimensions')
    target.parent.mkdir(parents=True,exist_ok=True)
    log=target.with_suffix('.retime.log');encoder=decoder=None
    if log.exists():raise ValueError('Retime log already exists; use a new revision basename')
    selected_hash=hashlib.sha256();pcm_created=False
    try:
        with tempfile.TemporaryDirectory(prefix='retime-',dir=target.parent) as temp, log.open('w') as stream:
            # PCM preparation uses the same source timeline as the picture.
            samples_count=round(Fraction(mapping['input_frame_count'],1)/rate*48000)
            if _stream(info,'audio'):
                pcm=subprocess.run(['ffmpeg','-v','error','-xerror','-i',str(source),'-map','0:a:0',
                    '-af','aresample=48000:async=1:first_pts=0','-ac','2','-ar','48000','-f','s16le','-'],
                    stdout=subprocess.PIPE,stderr=stream,check=True).stdout
                samples=np.frombuffer(pcm,dtype='<i2').reshape(-1,2).astype(np.float32)/32768
                samples=np.pad(samples,((0,max(0,samples_count-len(samples))),(0,0)))[:samples_count]
            else:samples=np.zeros((samples_count,2),dtype=np.float32)
            from .retime_audio import retime_audio
            sound,audio_evidence=retime_audio(samples,48000,mapping,
                backend=proposal['request'].get('audio_backend','rubberband'),log_dir=target.parent/(target.stem+'.audio-logs'))
            audio=Path(temp)/'retimed.wav'
            with wave.open(str(audio),'wb') as wav:
                wav.setnchannels(2);wav.setsampwidth(2);wav.setframerate(48000)
                wav.writeframes(np.rint(np.clip(sound,-1,32767/32768)*32768).astype('<i2').tobytes())
            decoder_command=['ffmpeg','-v','error','-xerror','-threads','1','-i',str(source),'-map','0:v:0',
                             '-fps_mode','passthrough','-f','rawvideo','-pix_fmt','rgb24','-threads','1','-']
            encoder_command=['ffmpeg','-v','error','-nostdin','-n','-threads','1','-f','rawvideo','-pix_fmt','rgb24',
                             '-s',f'{width}x{height}','-r',str(rate),'-i','pipe:0','-i',str(audio),
                             '-map','0:v:0','-map','1:a:0','-c:v','libx264','-preset','fast','-crf','18',
                             '-vf','scale=out_color_matrix=bt709,format=yuv420p,setparams=color_primaries=bt709:color_trc=bt709:colorspace=bt709',
                             '-pix_fmt','yuv420p',
                             '-colorspace','bt709','-color_trc','bt709','-color_primaries','bt709',
                             '-c:a','aac','-b:a','384k','-t',str(float(Fraction(count,1)/rate)),
                             '-movflags','+faststart',str(target)]
            stream.write(json.dumps({'decoder':decoder_command,'encoder':encoder_command})+'\n');stream.flush()
            decoder=subprocess.Popen(decoder_command,stdout=subprocess.PIPE,stderr=stream)
            encoder=subprocess.Popen(encoder_command,stdin=subprocess.PIPE,stderr=stream)
            current=-1;picture=None
            for frame in mapping['frame_map']:
                while current<frame:
                    picture=_read_frame(decoder.stdout,width*height*3);current+=1
                encoder.stdin.write(picture);selected_hash.update(picture)
            # Drain remaining input for complete source decode and process exit.
            while decoder.stdout.read(1024*1024):pass
            decoder.stdout.close();encoder.stdin.close()
            if decoder.wait()!=0 or encoder.wait()!=0:raise RuntimeError(f'Retime FFmpeg failed; see {log}')
            final=_probe(target,count=True);picture_stream=_stream(final,'video')
            if not picture_stream or int(picture_stream['nb_read_frames'])!=count or _verified_rate(target,picture_stream,count)!=rate:
                raise ValueError('Retime output differs from compiled frame count/FPS')
            audio_stream=_stream(final,'audio')
            if not audio_stream or abs(Fraction(audio_stream['duration'])-Fraction(count,1)/rate)>Fraction(1,48000):
                raise ValueError('Retimed audio duration differs from output timeline')
            subprocess.run(['ffmpeg','-v','error','-xerror','-i',str(target),'-f','null','-'],stderr=stream,check=True)
            if fingerprint(source)!=input_ref:raise ValueError('Source changed during retime render')
            if retained_pcm is not None:
                retained_pcm.parent.mkdir(parents=True,exist_ok=True)
                with retained_pcm.open('xb') as destination, audio.open('rb') as original:
                    pcm_created=True
                    shutil.copyfileobj(original,destination)
    except Exception:
        for process in (decoder,encoder):
            if process is not None:
                if process.poll() is None:process.kill()
                process.wait()
                for pipe in (process.stdout,process.stdin):
                    if pipe is not None:pipe.close()
        target.unlink(missing_ok=True)
        if pcm_created:retained_pcm.unlink(missing_ok=True)
        raise
    return {'version':1,'source':proposal['source'],'actual_input':input_ref,'output':fingerprint(target),'mapping':mapping,
            'captions':proposal['captions'],'audio':audio_evidence,
            **({'retained_pcm':fingerprint(retained_pcm)} if retained_pcm is not None else {}),
            'selected_rgb_sha256':selected_hash.hexdigest(),'actor':proposal['actor'],'reason':proposal['reason'],
            'picture_sampling':{'method':'source_frame_duplication_or_drop_no_interpolation',
                                'distinct_source_frames':len(set(mapping['frame_map'])),
                                'dropped_source_frames':mapping['input_frame_count']-len(set(mapping['frame_map'])),
                                'repeated_output_frames':count-len(set(mapping['frame_map']))},
            'review':'Technical frame mapping and decode only; human visual/listening review pending'}
