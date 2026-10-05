"""Verify an installed wheel outside the checkout, without source media or API access."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

wheel=Path(sys.argv[1]).resolve()
with tempfile.TemporaryDirectory(prefix='video-harness-wheel-') as tmp:
    root=Path(tmp)
    environment=os.environ.copy()
    environment.pop('PYTHONPATH',None)
    environment.pop('VIDEO_EDIT_HARNESS_ROOT',None)
    venv=root/'venv'
    subprocess.run(['uv','venv',str(venv),'--python',sys.executable],check=True,cwd=root,env=environment)
    python=venv/'bin/python'
    subprocess.run(['uv','pip','install','--python',str(python),str(wheel)],check=True,cwd=root,env=environment)
    command=venv/'bin/video-harness'
    subprocess.run([str(command),'--help'],check=True,cwd=root,env=environment,stdout=subprocess.DEVNULL)
    subprocess.run([str(command),'session','--help'],check=True,cwd=root,env=environment,stdout=subprocess.DEVNULL)
    result=subprocess.check_output([str(command),'presets'],cwd=root,env=environment,text=True)
    presets=json.loads(result)
    assert len(presets['use_cases'])==7 and len(presets['styles'])==6
    check='''from pathlib import Path
from video_harness.common import ROOT,DATA_ROOT
from video_harness.color import build_lut
from video_harness.runs import code_hash
assert ROOT == Path.cwd(), (ROOT,Path.cwd())
assert DATA_ROOT.is_dir()
assert len(code_hash()) == 64
build_lut({'input_color':'rec709','white_balance_gains':[1,1,1]},'clean_natural',Path('test.cube'))
assert Path('test.cube').is_file()
print('Installed wheel: presets, legacy LUT, code hash and workspace verified')
'''
    subprocess.run([str(python),'-c',check],check=True,cwd=root,env=environment)
