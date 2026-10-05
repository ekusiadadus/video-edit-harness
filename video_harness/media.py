from pathlib import Path
import json,re,math,subprocess
from .common import probe,run,write

def loudness_filter(cfg,source,start,duration,out):
 audio=cfg['audio'];base=f"loudnorm=I={audio['target_lufs']}:TP={audio['true_peak_db']}:LRA={audio['loudness_range']}"
 if not audio.get('normalize'):return 'anull'
 log=run(['ffmpeg','-hide_banner','-nostdin','-ss',str(start),'-i',source,'-t',str(duration),'-map','0:a:0','-af',base+':print_format=json','-f','null','-'],out/'audio-measure.log')
 matches=re.findall(r'\{\s*"input_i".*?\}',log,re.S)
 if not matches:raise ValueError('Cannot measure loudness')
 m=json.loads(matches[-1]);write(out/'audio-measure.json',m)
 if not all(math.isfinite(float(m[k])) for k in ('input_i','input_tp','input_lra','input_thresh','target_offset')):raise ValueError('No usable audio loudness; disable normalization for silent media')
 return base+f":measured_I={m['input_i']}:measured_TP={m['input_tp']}:measured_LRA={m['input_lra']}:measured_thresh={m['input_thresh']}:offset={m['target_offset']}:linear=true"

def stream_bounds(probe_data,kind):
 """Track coverage in seconds; never substitute container length for a track."""
 stream=next((s for s in probe_data['streams'] if s['codec_type']==kind),None)
 if stream is None:return None
 start=float(stream.get('start_time',probe_data.get('format',{}).get('start_time',0)))
 length=stream.get('duration')
 if length is None or length=='N/A':
  from fractions import Fraction
  if stream.get('duration_ts') is None or not stream.get('time_base'):raise ValueError(f'Cannot establish {kind} track duration')
  length=float(Fraction(str(stream['duration_ts']))*Fraction(stream['time_base']))
 length=float(length)
 if not math.isfinite(start) or not math.isfinite(length) or length<=0:raise ValueError(f'Invalid {kind} track timing')
 return (start,start+length)

def verify(path,out,expected_duration=None,require_audio=False,expected_audio_range=None):
 j=probe(path);v=next(s for s in j['streams'] if s['codec_type']=='video');a=next((s for s in j['streams'] if s['codec_type']=='audio'),None)
 if (v.get('color_primaries'),v.get('color_transfer'),v.get('color_space'))!=('bt709','bt709','bt709'):raise ValueError('Rec709 tags missing')
 if require_audio and not a:raise ValueError('Missing audio')
 if expected_duration is not None and abs(float(j['format']['duration'])-expected_duration)>.15:raise ValueError('Unexpected output duration')
 video_range=stream_bounds(j,'video');audio_range=stream_bounds(j,'audio')
 if expected_duration is not None and abs(video_range[1]-video_range[0]-expected_duration)>.15:raise ValueError('Unexpected video track duration')
 if expected_audio_range is not None:
  expected_audio_range=tuple(float(t) for t in expected_audio_range)
  if len(expected_audio_range)!=2 or not all(math.isfinite(t) for t in expected_audio_range) or not 0<=expected_audio_range[0]<expected_audio_range[1]:raise ValueError('Invalid expected audio range')
  if audio_range is None:raise ValueError('Missing expected audio')
 elif audio_range is not None:
  # Standalone verification expects full coverage unless an intentional range is supplied.
  expected_audio_range=video_range
 if audio_range is not None and any(abs(actual-expected)>.15 for actual,expected in zip(audio_range,expected_audio_range)):
  raise ValueError(f'Unexpected audio track range: {audio_range}; expected {expected_audio_range}')
 run(['ffmpeg','-v','error','-xerror','-i',str(path),'-map','0:v:0','-map','0:a:0?','-f','null','-'],out/'decode.log')
 write(out/'verification.json',{'file':str(path),'decode':'pass','probe':j,'duration_expected':expected_duration,'video_range':video_range,'audio_range':audio_range,'audio_range_expected':expected_audio_range,'timing_tolerance_seconds':.15});return j

def render(cfg,lut,out,start,duration,preview=False):
 out.mkdir(parents=True,exist_ok=False);src=cfg['source'];j=probe(src)
 has_audio=any(x['codec_type']=='audio' for x in j['streams'])
 default_required=cfg.get('_resolved',{}).get('use_case','indoor_talk')=='indoor_talk' if cfg.get('_resolved') else True
 if cfg['audio'].get('required',default_required) and not has_audio:raise ValueError('Audio required for this project/use case')
 total=float(j['format']['duration'])
 if start<0 or duration<=0 or start+duration>total+.01:raise ValueError('Trim outside media')
 audio_expected=None
 if has_audio:
  source_audio=stream_bounds(j,'audio');origin=float(j.get('format',{}).get('start_time',0));first=max(start,source_audio[0]-origin);last=min(start+duration,source_audio[1]-origin)
  if last<=first:raise ValueError('Selected range contains no source audio; select a different interval')
  audio_expected=(first-start,last-start)
 af=loudness_filter(cfg,src,start,duration,out) if has_audio else 'anull'
 # lut path passed via subprocess, but FFmpeg filter syntax also requires escaping.
 escaped=str(lut.resolve()).replace('\\','\\\\').replace(':','\\:').replace("'","'\\''")
 vf=f"format=gbrpf32le,lut3d=file='{escaped}':interp=tetrahedral"
 if preview:vf+=',scale=-2:720'
 # LUT output is Rec709 RGB. Explicitly set the RGB tags before the RGB->YUV matrix conversion.
 vf+=',setparams=color_primaries=bt709:color_trc=bt709:colorspace=gbr:range=full,scale=out_color_matrix=bt709:out_range=tv'
 from .regions import region_filter
 vf+=region_filter(cfg)
 vf+=',format=yuv420p,setsar=1,setparams=color_primaries=bt709:color_trc=bt709:colorspace=bt709:range=limited'
 path=out/'video.mp4'
 run(['ffmpeg','-hide_banner','-nostdin','-n','-filter_threads','4','-ss',str(start),'-i',src,'-t',str(duration),'-map','0:v:0','-map','0:a:0?','-vf',vf,'-af',af,'-c:v','libx264','-preset','fast','-crf','18','-profile:v','high','-pix_fmt','yuv420p','-color_primaries','bt709','-color_trc','bt709','-colorspace','bt709','-color_range','tv','-c:a','aac','-b:a','384k','-ar','48000','-map_metadata','-1','-metadata:s:v:0','rotate=0','-movflags','+faststart','-use_editlist','0',str(path)],out/'render.log')
 result=verify(path,out,duration,has_audio,audio_expected)
 run(['ffmpeg','-v','error','-n','-ss',str(min(2,duration/2)),'-i',str(path),'-frames:v','1',str(out/'poster.jpg')],out/'poster.log')
 if has_audio:
  run(['ffmpeg','-v','error','-n','-i',str(path),'-vn','-c:a','libmp3lame','-b:a','192k',str(out/'audio-only.mp3')],out/'audio-only.log')
  run(['ffmpeg','-v','error','-xerror','-i',str(out/'audio-only.mp3'),'-f','null','-'],out/'audio-only-decode.log')
  measurement=run(['ffmpeg','-hide_banner','-nostdin','-i',str(path),'-map','0:a:0','-af','loudnorm=print_format=json','-f','null','-'],out/'audio-output-measure.log')
  measured=json.loads(re.findall(r'\{\s*"input_i".*?\}',measurement,re.S)[-1])
  warnings=[]
  if cfg['audio'].get('normalize'):
   if abs(float(measured['input_i'])-cfg['audio']['target_lufs'])>.5:warnings.append('Integrated loudness differs from target by >0.5 LU. Review before publishing.')
   if float(measured['input_tp'])>cfg['audio']['true_peak_db']+.3:warnings.append('True peak exceeds target +0.3dB tolerance.')
  write(out/'audio-output-measure.json',{'measured':measured,'targets':cfg['audio'],'warnings':warnings})
 write(out/'settings.json',cfg);return path
