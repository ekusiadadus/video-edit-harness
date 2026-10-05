"""Public demos must bind their presentation language to the actual speech."""
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1]/'scripts'
sys.path.insert(0, str(SCRIPTS))
spec = importlib.util.spec_from_file_location('build_platform_demos', SCRIPTS/'build_platform_demos.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class DemoLanguages(unittest.TestCase):
    def test_mismatched_voice_and_transcript_fail(self):
        for voice, timing in [('ja', 'en'), ('en', 'ja'), ('fr', 'fr')]:
            with self.assertRaises(ValueError):
                module.fixture_language({'voice': {'language': voice}}, {'language': timing})
        for language in ('ja', 'en'):
            self.assertEqual(module.fixture_language({'voice': {'language': language}}, {'language': language}), language)

    def test_requested_translation_does_not_relabel_existing_audio(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); sample = root/'sample'; sample.mkdir()
            (sample/'provenance.json').write_text(json.dumps({'voice': {'language': 'ja'}}))
            (sample/'timing.json').write_text(json.dumps({'language': 'ja'}))
            with patch.object(module, 'render_sample') as render:
                with self.assertRaisesRegex(ValueError, 'actual voice'):
                    module.build(sample, root/'out', root/'docs', language='en')
                render.assert_not_called()
            self.assertFalse((root/'out').exists())
            self.assertFalse((root/'docs').exists())

    def test_english_presentation_contains_no_japanese_labels(self):
        labels = json.dumps(module.language_content('en'), ensure_ascii=False)
        self.assertFalse(any('\u3040' <= char <= '\u30ff' or '\u4e00' <= char <= '\u9fff' for char in labels))
        self.assertIn('編集前', module.language_content('ja')['before'])
