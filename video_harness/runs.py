"""Run evidence and local single-render exclusion, inspired by per-run harness logs."""
from contextlib import contextmanager
from datetime import datetime,timezone
from pathlib import Path
import fcntl,hashlib,json,os,subprocess,uuid
from .common import ROOT,PACKAGE_ROOT,CHECKOUT_ROOT,IS_CHECKOUT,fingerprint,write,read

def now():return datetime.now(timezone.utc).isoformat()
def unique_id():return datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-'+uuid.uuid4().hex[:8]
def code_hash():
 h=hashlib.sha256()
 for p in sorted(PACKAGE_ROOT.glob('*.py')):h.update(p.name.encode());h.update(p.read_bytes())
 if IS_CHECKOUT and (CHECKOUT_ROOT/'uv.lock').is_file():h.update(b'uv.lock');h.update((CHECKOUT_ROOT/'uv.lock').read_bytes())
 return h.hexdigest()
def ledger(event):
 p=ROOT/'output/events.jsonl';p.parent.mkdir(exist_ok=True)
 with p.open('a') as f:
  fcntl.flock(f,fcntl.LOCK_EX);f.write(json.dumps({'at':now(),**event},ensure_ascii=False)+'\n');f.flush();os.fsync(f.fileno())
@contextmanager
def evidence_run(cfg,command,output,conditions):
 (ROOT/'output').mkdir(exist_ok=True)
 with (ROOT/'output/.render.lock').open('a') as lock:
  try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
  except BlockingIOError:raise ValueError('Another video render is active in this harness. Retry after it finishes.')
  out=Path(output);out.mkdir(parents=True,exist_ok=False);rid=unique_id()
  manifest=None
  try:
   versions={x:subprocess.check_output([x,'-version'],text=True).splitlines()[0] for x in ['ffmpeg','ffprobe']}
   manifest={'run_id':rid,'started_at':now(),'command':command,'source':fingerprint(cfg['source']),'project':cfg,'conditions':conditions,'code_sha256':code_hash(),'tools':versions,'quality_status':'not_reviewed'}
   write(out/'manifest.json',manifest);ledger({'event':'run_started','run_id':rid,'path':str(out)})
   yield manifest
   if fingerprint(cfg['source'])!=manifest['source']:raise ValueError('Source changed during render')
   artifacts={str(p.relative_to(out)):fingerprint(p)['sha256'] for p in sorted(out.rglob('*')) if p.is_file()}
   write(out/'result.json',{'run_id':rid,'technical_status':'pass','ended_at':now(),'quality_status':'not_reviewed','artifacts':artifacts});ledger({'event':'run_pass','run_id':rid})
  except BaseException as e:
   if not (out/'result.json').exists():write(out/'result.json',{'run_id':rid,'technical_status':'failed','error':str(e),'ended_at':now(),'quality_status':'not_reviewed'})
   ledger({'event':'run_failed','run_id':rid,'error':str(e)});raise

def review(run,candidate,decision,note,adopt=False):
 run=Path(run).resolve();manifest=read(run/'manifest.json');result=read(run/'result.json')
 if result['technical_status']!='pass':raise ValueError('Cannot review/adopt a failed run')
 for relative,digest in result.get('artifacts',{}).items():
  path=run/relative
  if not path.is_file() or fingerprint(path)['sha256']!=digest:raise ValueError(f'Run artifact changed: {relative}')
 # Candidate must be recorded in this run, not an arbitrary path.
 candidates=read(run/'candidates.json')
 if candidate not in candidates:raise ValueError('Candidate not in run')
 cfg=read(run/candidate/'resolved.json');evidence=read(run/candidate/'evaluation.json')
 if not note.strip():raise ValueError('Record a review note')
 item={'run_id':manifest['run_id'],'candidate':candidate,'decision':decision,'note':note,'at':now(),'resolved':cfg,'evaluation':evidence,'source':manifest['source']}
 reviews=run/'reviews';reviews.mkdir(exist_ok=True)
 if adopt:
  accepted=[read(p) for p in reviews.glob('*.json') if read(p).get('candidate')==candidate]
  accepted.sort(key=lambda x:x['at'])
  if not accepted or accepted[-1]['decision']!='accept':raise ValueError('Latest recorded human review must accept this candidate before adoption')
  item['review']=accepted[-1];base=ROOT/'baselines';base.mkdir(exist_ok=True);target=base/f"{manifest['run_id']}-{candidate}.json";write(target,item)
  ledger({'event':'baseline_adopted','run_id':manifest['run_id'],'candidate':candidate,'baseline':str(target)});return target
 target=reviews/f'{unique_id()}.json';write(target,item);ledger({'event':'human_review','run_id':manifest['run_id'],'candidate':candidate,'decision':decision});return target
