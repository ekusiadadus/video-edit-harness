"""Distribution inventory keeps private inputs out and skill copies identical."""
import hashlib
import importlib.util
import json
import tempfile
import tomllib
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('package_release', ROOT/'scripts/package_release.py')
package = importlib.util.module_from_spec(spec)
spec.loader.exec_module(package)


class SkillDistribution(unittest.TestCase):
    def test_checkout_declares_matching_three_skill_release(self):
        version = tomllib.loads((ROOT/'pyproject.toml').read_text())['project']['version']
        release_version = version.replace('a', '-alpha.')
        manifest = json.loads((ROOT/'.claude-plugin/plugin.json').read_text())
        self.assertEqual(manifest['version'], release_version)
        self.assertEqual(set(manifest['skills']),
                         {f'./.agents/skills/{name}' for name in ('video-editing','tiktok','youtube')})
        for name in ('video-editing','tiktok','youtube'):
            body = (ROOT/'.agents/skills'/name/'SKILL.md').read_text()
            self.assertIn('v'+release_version, body)
            self.assertTrue((ROOT/'.agents/skills'/name/'agents/openai.yaml').is_file())

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
            (root/'pyproject.toml').write_text('[project]\nversion="0.1.0a4"\n')
            (root/'.claude-plugin').mkdir()
            manifest={'name':'video-editing','version':'0.1.0-alpha.4',
                      'skills':['./.agents/skills/video-editing']}
            (root/'.claude-plugin/plugin.json').write_text(json.dumps(manifest))
            for name in ('tiktok','youtube'):
                platform=root/'.agents/skills'/name
                (platform/'agents').mkdir(parents=True)
                (platform/'SKILL.md').write_text(f'---\nname: {name}\ndescription: Test\n---\n')
                (platform/'agents/openai.yaml').write_text('interface: {}\n')
                (platform/'private.mp4').write_bytes(b'never-publish')
                manifest['skills'].append(f'./.agents/skills/{name}')
            (root/'.claude-plugin/plugin.json').write_text(json.dumps(manifest))
            out=root/'dist'
            out.mkdir()
            (out/'obsolete-release.zip').write_bytes(b'old release')
            (out/'video_edit_harness-0.1.0a4-unrelated.whl').write_bytes(b'not a planned artifact')
            with patch.object(package,'ROOT',root), patch('sys.argv',['package_release','--output',str(out)]):
                package.main()
            portable=out/'video-editing-skill-v0.1.0-alpha.4.zip'
            plugin=out/'video-editing-claude-plugin-v0.1.0-alpha.4.zip'
            with zipfile.ZipFile(portable) as a, zipfile.ZipFile(plugin) as b:
                self.assertEqual(set(a.namelist()),{'video-editing/SKILL.md','video-editing/agents/openai.yaml','video-editing/LICENSE'})
                self.assertEqual(set(b.namelist()),{'.claude-plugin/plugin.json','.agents/skills/video-editing/SKILL.md','.agents/skills/video-editing/agents/openai.yaml','.agents/skills/tiktok/SKILL.md','.agents/skills/tiktok/agents/openai.yaml','.agents/skills/youtube/SKILL.md','.agents/skills/youtube/agents/openai.yaml','LICENSE'})
                self.assertEqual(a.read('video-editing/SKILL.md'),b.read('.agents/skills/video-editing/SKILL.md'))
                m=json.loads(b.read('.claude-plugin/plugin.json'))
                for path in m['skills']:
                    self.assertIn(path.removeprefix('./')+'/SKILL.md',b.namelist())
            for name in ('tiktok','youtube'):
                with zipfile.ZipFile(out/f'{name}-skill-v0.1.0-alpha.4.zip') as a, zipfile.ZipFile(plugin) as b:
                    self.assertEqual(set(a.namelist()),{f'{name}/SKILL.md',f'{name}/agents/openai.yaml',f'{name}/LICENSE'})
                    self.assertEqual(a.read(f'{name}/SKILL.md'),b.read(f'.agents/skills/{name}/SKILL.md'))
            for line in (out/'SHA256SUMS').read_text().splitlines():
                digest,name=line.split('  ')
                self.assertEqual(digest,hashlib.sha256((out/name).read_bytes()).hexdigest())
                self.assertNotEqual(name,'obsolete-release.zip')
            release_manifest=json.loads((out/'RELEASE-MANIFEST.json').read_text())
            self.assertEqual(release_manifest['version'],'v0.1.0-alpha.4')
            self.assertEqual({item['name'] for item in release_manifest['artifacts']},
                             {f'{name}-skill-v0.1.0-alpha.4.zip' for name in ('video-editing','tiktok','youtube')} |
                             {'video-editing-claude-plugin-v0.1.0-alpha.4.zip'})
