"""Distribution inventory keeps private inputs out and both skill copies identical."""
import hashlib
import importlib.util
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('package_release', ROOT/'scripts/package_release.py')
package = importlib.util.module_from_spec(spec)
spec.loader.exec_module(package)


class SkillDistribution(unittest.TestCase):
    def test_explicit_inventory_and_plugin_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            skill = root/'.agents/skills/video-editing'
            (skill/'agents').mkdir(parents=True)
            (skill/'SKILL.md').write_text('---\nname: video-editing\ndescription: Test\n---\n')
            (skill/'agents/openai.yaml').write_text('interface: {}\n')
            (skill/'private.mp4').write_bytes(b'private footage must stay out')
            (skill/'.env').write_text('SECRET=never-publish')
            (root/'LICENSE').write_text('MIT')
            (root/'pyproject.toml').write_text('[project]\nversion="0.1.0a3"\n')
            (root/'.claude-plugin').mkdir()
            manifest={'name':'video-editing','version':'0.1.0-alpha.3',
                      'skills':['./.agents/skills/video-editing']}
            (root/'.claude-plugin/plugin.json').write_text(json.dumps(manifest))
            tiktok=root/'.agents/skills/tiktok'
            (tiktok/'agents').mkdir(parents=True)
            (tiktok/'SKILL.md').write_text('---\nname: tiktok\ndescription: Test\n---\n')
            (tiktok/'agents/openai.yaml').write_text('interface: {}\n')
            (tiktok/'private.mp4').write_bytes(b'never-publish')
            manifest['skills'].append('./.agents/skills/tiktok')
            (root/'.claude-plugin/plugin.json').write_text(json.dumps(manifest))
            out=root/'dist'
            with patch.object(package,'ROOT',root), patch('sys.argv',['package_release','--output',str(out)]):
                package.main()
            portable=out/'video-editing-skill-v0.1.0-alpha.3.zip'
            plugin=out/'video-editing-claude-plugin-v0.1.0-alpha.3.zip'
            with zipfile.ZipFile(portable) as a, zipfile.ZipFile(plugin) as b:
                self.assertEqual(set(a.namelist()),{'video-editing/SKILL.md','video-editing/agents/openai.yaml','video-editing/LICENSE'})
                self.assertEqual(set(b.namelist()),{'.claude-plugin/plugin.json','.agents/skills/video-editing/SKILL.md','.agents/skills/video-editing/agents/openai.yaml','.agents/skills/tiktok/SKILL.md','.agents/skills/tiktok/agents/openai.yaml','LICENSE'})
                self.assertEqual(a.read('video-editing/SKILL.md'),b.read('.agents/skills/video-editing/SKILL.md'))
                m=json.loads(b.read('.claude-plugin/plugin.json'))
                for path in m['skills']:
                    self.assertIn(path.removeprefix('./')+'/SKILL.md',b.namelist())
            with zipfile.ZipFile(out/'tiktok-skill-v0.1.0-alpha.3.zip') as a:
                self.assertEqual(set(a.namelist()),{'tiktok/SKILL.md','tiktok/agents/openai.yaml','tiktok/LICENSE'})
            for line in (out/'SHA256SUMS').read_text().splitlines():
                digest,name=line.split('  ')
                self.assertEqual(digest,hashlib.sha256((out/name).read_bytes()).hexdigest())
