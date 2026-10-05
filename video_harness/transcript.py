"""Backend-neutral transcript validation and review artifacts."""

from pathlib import Path
import hashlib
import json
import math
import os

from .common import fingerprint


def _canonical(data):
 return json.dumps(data,sort_keys=True,ensure_ascii=False,separators=(',',':'),allow_nan=False).encode()


def _digest(data):
 return hashlib.sha256(_canonical(data)).hexdigest()


def _time(value,label):
 if isinstance(value,bool) or not isinstance(value,(int,float)):raise ValueError(f'Invalid {label}')
 value=float(value)
 if not math.isfinite(value):raise ValueError(f'Invalid {label}')
 return value


def _timestamp(seconds):
 milliseconds=round(seconds*1000)
 hours,remainder=divmod(milliseconds,3600000)
 minutes,remainder=divmod(remainder,60000)
 seconds,millis=divmod(remainder,1000)
 return f'{hours:02d}:{minutes:02d}:{seconds:02d}.{millis:03d}'


def _review_text(data):
 lines=['Automatic transcript — human review required',f"Source: {data['source']['path']}",f"SHA-256: {data['source']['sha256']}"]
 if 'semantic_text' in data:lines.extend(['','Semantic transcription:',data['semantic_text']])
 lines.extend(['','Segments:'])
 for row in data['segments']:
  lines.append(f"[{_timestamp(row['start'])} → {_timestamp(row['end'])}] {row['text']}")
 lines.extend(['','Words:'])
 for row in data['words']:
  confidence='unavailable' if data['backend']['settings'].get('word_probability_available') is False else f"p={row['probability']:.3f}"
  lines.append(f"{row['id']} [{_timestamp(row['start'])} → {_timestamp(row['end'])}] {row['text']} ({confidence})")
 if data['warnings']:
  lines.extend(['','Warnings:',*(f'- {warning}' for warning in data['warnings'])])
 return '\n'.join(lines)+'\n'


def _validate_body(data):
 if not isinstance(data,dict) or data.get('version')!=1 or data.get('status')!='review_required':raise ValueError('Unsupported transcript version or status')
 source=data.get('source')
 if not isinstance(source,dict) or not isinstance(source.get('path'),str) or not isinstance(source.get('bytes'),int) or source['bytes']<0 or not isinstance(source.get('sha256'),str) or len(source['sha256'])!=64:
  raise ValueError('Invalid transcript source fingerprint')
 duration=_time(data.get('duration'),'transcript duration')
 if duration<=0:raise ValueError('Invalid transcript duration')
 language=data.get('language')
 if language is not None and (not isinstance(language,str) or not language):raise ValueError('Invalid transcript language')
 if 'semantic_text' in data and not isinstance(data['semantic_text'],str):raise ValueError('Invalid semantic transcription text')
 backend=data.get('backend')
 if not isinstance(backend,dict) or backend.get('name') not in ('openai','azure') or not isinstance(backend.get('settings'),dict):raise ValueError('Invalid transcript backend')
 sdk_version=backend.get('sdk_version',backend.get('version'))
 if not isinstance(sdk_version,str) or not sdk_version:raise ValueError('Missing transcript backend SDK version')
 for key in ('words','segments'):
  rows=data.get(key)
  if not isinstance(rows,list):raise ValueError(f'Invalid transcript {key}')
  previous=0.0
  ids=set()
  for row in rows:
   if not isinstance(row,dict) or not isinstance(row.get('id'),(str,int)) or isinstance(row.get('id'),bool) or row['id'] in ids or not isinstance(row.get('text'),str) or not row['text'].strip():raise ValueError(f'Invalid transcript {key} entry')
   ids.add(row['id'])
   start=_time(row.get('start'),f'{key} start');end=_time(row.get('end'),f'{key} end')
   if start<0 or end<=start or end>duration or (key=='words' and start<previous):raise ValueError(f'Invalid transcript {key} timing')
   previous=end if key=='words' else previous
   if key=='words':
    probability=_time(row.get('probability'),'word probability')
    if not 0<=probability<=1:raise ValueError('Invalid word probability')
 warnings=data.get('warnings')
 if not isinstance(warnings,list) or any(not isinstance(w,str) for w in warnings):raise ValueError('Invalid transcript warnings')
 return data


def validate_transcript(data):
 _validate_body(data)
 if data.get('review_text_sha256')!=hashlib.sha256(_review_text(data).encode()).hexdigest():raise ValueError('Transcript review text hash mismatch')
 if data.get('result_sha256')!=_digest({k:v for k,v in data.items() if k!='result_sha256'}):raise ValueError('Transcript content hash mismatch')
 return data


def load_transcript(path,source=None):
 path=Path(path);data=validate_transcript(json.loads(path.read_text()))
 text_path=path.with_name('transcript.txt')
 if not text_path.is_file() or hashlib.sha256(text_path.read_bytes()).hexdigest()!=data['review_text_sha256']:
  raise ValueError('Transcript review text missing or changed')
 if source is not None and fingerprint(source)!=data['source']:raise ValueError('Transcript source changed; transcribe again')
 return data


def save_transcript(folder,data):
 """Seal and write a reviewed-later transcript; never replace an existing result."""
 folder=Path(folder)
 result=folder/'transcript.json'
 if result.exists():raise FileExistsError(result)
 clean={k:v for k,v in data.items() if k not in ('result_sha256','review_text_sha256')}
 clean.setdefault('status','review_required')
 clean.setdefault('warnings',[])
 _validate_body(clean)
 text=_review_text(clean)
 clean['review_text_sha256']=hashlib.sha256(text.encode()).hexdigest()
 clean['result_sha256']=_digest(clean)
 validate_transcript(clean)
 folder.mkdir(parents=True,exist_ok=True)
 text_path=folder/'transcript.txt'
 if text_path.exists():raise FileExistsError(text_path)
 temporary=folder/f'transcript.{os.getpid()}.tmp'
 with temporary.open('x') as file:file.write(json.dumps(clean,ensure_ascii=False,indent=2,allow_nan=False))
 created_text=False
 try:
  with text_path.open('x') as file:file.write(text)
  created_text=True
  if result.exists():raise FileExistsError(result)
  temporary.rename(result)
 except BaseException:
  temporary.unlink(missing_ok=True)
  if created_text:text_path.unlink(missing_ok=True)
  raise
 return result
