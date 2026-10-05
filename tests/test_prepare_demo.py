import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
import zipfile

spec=importlib.util.spec_from_file_location('prepare_demo',Path(__file__).resolve().parents[1]/'scripts/prepare_demo.py')
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)


class PublicFixture(unittest.TestCase):
    def test_unsafe_zip_and_source_mismatch_do_not_create_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            for traversal in (False,True):
                fixture=root/f'{traversal}.zip';out=root/f'out-{traversal}'
                with zipfile.ZipFile(fixture,'w') as z:
                    z.writestr('sample.mp4',b'wrong source')
                    z.writestr('timing.json','{}')
                    z.writestr('provenance.json',json.dumps({'source_kind':'synthetic','source_sha256':'0'*64}))
                    z.writestr('LICENSE','MIT')
                    if traversal:z.writestr('../private','do not extract')
                with self.assertRaises(ValueError):module.prepare(fixture,out)
                self.assertFalse(out.exists())
                self.assertFalse((root/'private').exists())
