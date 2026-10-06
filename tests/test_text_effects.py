"""Focused geometry and validation tests for transparent title cards."""

import hashlib
from pathlib import Path
import tempfile
import unittest

from PIL import Image

from video_harness.doctor import FONT_PATHS
from video_harness.text_effects import render_text_asset, validate_text_parameters


FONT = next((path for path in FONT_PATHS if Path(path).is_file()), None)


class TextEffectsTests(unittest.TestCase):
    @unittest.skipUnless(FONT, 'No CJK font')
    def test_version_two_wraps_measured_card_without_changing_legacy_pixels(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            settings = {'text': 'Modern dance with clear rhythm', 'font_path': FONT,
                        'font_size_fraction': .12}
            a = render_text_asset({'text': '結果', 'font_path': FONT}, 640, 360, root/'a.png')
            b = render_text_asset({'text': '結果', 'font_path': FONT}, 640, 360, root/'b.png', version=1)
            self.assertEqual(a['png_sha256'], b['png_sha256'])
            result = render_text_asset({**settings, 'language': 'en', 'max_width_fraction': .6},
                                       640, 360, root/'wrapped.png', version=2)
            self.assertGreater(len(result['rendered_lines']), 1)
            self.assertEqual(' '.join(result['rendered_lines']), settings['text'])
            self.assertLessEqual(result['bounds'][2]-result['bounds'][0], .6)
            self.assertEqual(result['original_text'], settings['text'])
            with self.assertRaises(ValueError):
                render_text_asset({**settings, 'language': 'en'}, 640, 360, root/'legacy.png')

    def test_validation_rejects_unsafe_or_unreadable_parameters(self):
        for parameters in (
            {"text": ""}, {"text": "a\nb\nc\nd"}, {"text": "a\rb"},
            {"text": "a\x00b"}, {"text": "a" * 121},
            {"text": "ok", "x": True}, {"text": "ok", "y": -0.01},
            {"text": "ok", "font_size_fraction": .121},
            {"text": "ok", "foreground": "white"},
            {"text": "ok", "foreground": "#171717", "background": "#171717"},
            {"text": "ok", "motion": "zoom"},
            {"text": "ok", "unknown": 1},
            {"text": "ok", "font_path": "/no/such/font.ttf"},
        ):
            with self.subTest(parameters=parameters), self.assertRaises(ValueError):
                validate_text_parameters(parameters)

    @unittest.skipUnless(FONT, "No doctor CJK font is installed")
    def test_real_cjk_card_is_readable_and_fingerprinted(self):
        settings = validate_text_parameters({"text": "今日のキーワード\n信頼", "motion": "rise"})
        self.assertEqual(settings["motion"], "rise")
        self.assertEqual(settings["font_path"], str(Path(FONT).resolve()))
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / "title.png"
            result = render_text_asset(settings, 1280, 720, output)
            self.assertEqual(result["font_sha256"], hashlib.sha256(Path(FONT).read_bytes()).hexdigest())
            self.assertEqual(result["png_sha256"], hashlib.sha256(output.read_bytes()).hexdigest())
            with Image.open(output) as image:
                self.assertEqual(image.size, (1280, 720))
                self.assertEqual(image.mode, "RGBA")
                self.assertEqual(image.getpixel((0, 0))[3], 0)
                bounds = image.getbbox()
            self.assertIsNotNone(bounds)
            normalized = [bounds[0] / 1280, bounds[1] / 720,
                          bounds[2] / 1280, bounds[3] / 720]
            for measured, returned in zip(normalized, result["bounds"]):
                self.assertAlmostEqual(measured, returned, places=5)
            with self.assertRaises(FileExistsError):
                render_text_asset(settings, 1280, 720, output)

    @unittest.skipUnless(FONT, "No doctor CJK font is installed")
    def test_overflow_is_rejected_before_writing(self):
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / "too-wide.png"
            with self.assertRaisesRegex(ValueError, "exceeds 90%"):
                render_text_asset({"text": "幅" * 100, "font_path": FONT,
                                   "font_size_fraction": .12}, 640, 360, output)
            self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
