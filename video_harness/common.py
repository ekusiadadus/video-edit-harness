from pathlib import Path
import hashlib,json,subprocess,shutil,os
PACKAGE_ROOT=Path(__file__).resolve().parent
CHECKOUT_ROOT=PACKAGE_ROOT.parent
IS_CHECKOUT=(CHECKOUT_ROOT/'pyproject.toml').is_file() and (CHECKOUT_ROOT/'use_cases').is_dir()
# Installed commands write into the caller's workspace, never site-packages.
ROOT=Path(os.environ['VIDEO_EDIT_HARNESS_ROOT']).expanduser().resolve() if os.environ.get('VIDEO_EDIT_HARNESS_ROOT') else CHECKOUT_ROOT if IS_CHECKOUT else Path.cwd()
DATA_ROOT=CHECKOUT_ROOT if IS_CHECKOUT else PACKAGE_ROOT/'data'
def read(path): return json.loads(Path(path).read_text())
def write(path,obj):
 p=Path(path);p.parent.mkdir(parents=True,exist_ok=True)
 with p.open('x') as f:f.write(json.dumps(obj,ensure_ascii=False,indent=2,allow_nan=False))
def run(cmd,log):
 p=Path(log);p.parent.mkdir(parents=True,exist_ok=True)
 with p.open('w') as f:
  f.write(json.dumps(cmd,ensure_ascii=False)+'\n');f.flush()
  subprocess.run(cmd,stdout=f,stderr=f,check=True)
 return p.read_text()
def probe(source): return json.loads(subprocess.check_output(['ffprobe','-v','error','-show_streams','-show_format','-of','json',str(source)]))
def fingerprint(source):
 p=Path(source);h=hashlib.sha256()
 with p.open('rb') as f:
  for chunk in iter(lambda:f.read(4*1024*1024),b''): h.update(chunk)
 return {'path':str(p.resolve()),'bytes':p.stat().st_size,'sha256':h.hexdigest()}
def project(path):
 cfg=read(path);src=Path(cfg['source']).expanduser()
 if not src.is_absolute():src=Path(path).resolve().parent/src
 cfg['source']=str(src.resolve())
 if not src.is_file():raise ValueError(f'Source missing: {src}')
 if cfg['input_color'] not in ('apple_log','rec709'):raise ValueError('Specify apple_log or rec709 explicitly; HLG/Log2 need their own transform.')
 return cfg
