"""Opt-in measured caption layout keeps source SRT timing and legacy behavior."""
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image, ImageDraw, ImageFont

from video_harness.common import read
from video_harness.vertical import (caption_font, caption_images, export_vertical,
                                    load_captions, resolve_caption_layout,
                                    _caption_ink_measure)


class CaptionLayoutTests(unittest.TestCase):
    def setUp(self):
        try:
            import regex  # noqa: F401
            import budoux  # noqa: F401
        except ImportError:
            self.skipTest('text-layout optional extra required')
        self.font = ImageFont.load_default(size=52)
        self.measure = ImageDraw.Draw(Image.new('RGB', (1, 1)))

    def lines(self, text, setting):
        cue = {'start': 0., 'end': 1., 'text': text}
        recorded = []
        list(caption_images([cue], self.font, resolve_caption_layout(setting), recorded))
        return recorded[0]['lines']

    def test_latin_words_number_units_and_manual_newlines(self):
        setting = {'version': 1, 'language': 'en', 'protected_phrases': []}
        text = 'OpenAI ' * 9 + '120fps'
        lines = self.lines(text, setting)
        self.assertGreater(len(lines), 1)
        self.assertLessEqual(len(lines), 3)
        self.assertTrue(all(_caption_ink_measure(self.measure, self.font, line)[0] <= 820
                            for line in lines))
        self.assertTrue(all('OpenAI' in line or '120fps' in line for line in lines))
        self.assertEqual(sum('OpenAI' in line for line in lines), len(lines))
        self.assertEqual(self.lines('one\n\nthree', setting), ['one', '', 'three'])
        with self.assertRaisesRegex(ValueError, 'Unbreakable text'):
            self.lines('A' * 100, setting)
        with patch('video_harness.text_layout.wrap_text') as wrap:
            with self.assertRaisesRegex(ValueError, '512 Unicode codepoints'):
                self.lines('a\u0301' * 257, setting)
            wrap.assert_not_called()

    def test_japanese_punctuation_protected_term_and_grapheme(self):
        try:
            font = caption_font([{'text': '東京タワー（夜景）'}])
        except ValueError:
            self.skipTest('local CJK font required')
        setting = resolve_caption_layout({'version': 1, 'language': 'ja',
                                          'protected_phrases': ['東京タワー']})
        text = '東京タワー（夜景）' * 3 + '120人'
        recorded = []
        list(caption_images([{'start': 0., 'end': 1., 'text': text}], font, setting, recorded))
        lines = recorded[0]['lines']
        self.assertLessEqual(len(lines), 3)
        self.assertEqual(''.join(lines), text)
        self.assertTrue(all(not line.startswith(('）', '、', '。')) for line in lines))
        self.assertTrue(all(not line.endswith(('（', '「')) for line in lines))
        self.assertTrue(all('東京タワー' not in left[-3:] + right[:3]
                            for left, right in zip(lines, lines[1:])))
        with self.assertRaisesRegex(ValueError, 'Unbreakable text'):
            list(caption_images([{'start': 0., 'end': 1., 'text': '東京タワー' * 20}], font,
                resolve_caption_layout({'version': 1, 'language': 'ja',
                    'protected_phrases': ['東京タワー' * 20]})))
        emoji = self.lines('👩‍💻 ' * 10 + 'a\u0301',
                           {'version': 1, 'language': 'en', 'protected_phrases': ['👩‍💻']})
        self.assertEqual(sum('👩‍💻' in line for line in emoji), len(emoji))
        self.assertIn('a\u0301', emoji[-1])

    def test_strict_record_missing_dependency_and_legacy_default(self):
        for invalid in ({'version': True, 'language': 'en', 'protected_phrases': []},
                        {'version': 1, 'language': 'fr', 'protected_phrases': []},
                        {'version': 1, 'language': 'en', 'protected_phrases': ['']},
                        {'version': 1, 'language': 'en', 'protected_phrases': [], 'max_width': 2}):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                resolve_caption_layout(invalid)
        with patch('video_harness.vertical.importlib.import_module', side_effect=ImportError('missing')):
            with self.assertRaisesRegex(ImportError, 'text-layout extra'):
                resolve_caption_layout({'version': 1, 'language': 'en', 'protected_phrases': []})
        request = {'version': 1, 'language': 'en', 'protected_phrases': ['OpenAI']}
        resolved = resolve_caption_layout(request)
        request['protected_phrases'].append('new')
        self.assertEqual(resolved['protected_phrases'], ['OpenAI'])
        cue = {'start': 0., 'end': 1., 'text': 'Simple legacy caption'}
        self.assertEqual(list(caption_images([cue], self.font))[0][0], cue)
        self.assertEqual(list(caption_images([cue], self.font))[0][1].tobytes(),
                         list(caption_images([cue], self.font, None))[0][1].tobytes())

    def test_italic_ink_overhang_is_measured_inside_tile(self):
        candidates = ['/usr/share/fonts/truetype/dejavu/DejaVuSans-Oblique.ttf',
                      '/System/Library/Fonts/Supplemental/Arial Italic.ttf']
        path = next((candidate for candidate in candidates if Path(candidate).is_file()), None)
        if path is None:
            self.skipTest('local italic test font unavailable')
        font = ImageFont.truetype(path, 52)
        measure = ImageDraw.Draw(Image.new('RGB', (1, 1)))
        layout = resolve_caption_layout({'version': 1, 'language': 'en', 'protected_phrases': []})
        text = 'Italic words ' * 6
        recorded = []
        list(caption_images([{'start': 0., 'end': 1., 'text': text}], font, layout, recorded))
        for line in recorded[0]['lines']:
            width, left = _caption_ink_measure(measure, font, line)
            bbox = measure.textbbox((20-left, 12), line, font=font, stroke_width=1)
            self.assertLessEqual(width, 820)
            self.assertGreaterEqual(bbox[0], 20)
            self.assertLessEqual(bbox[2], 840)


@unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'FFmpeg required')
class CaptionLayoutExportTests(unittest.TestCase):
    def test_result_records_resolved_lines_without_rewriting_srt(self):
        try:
            import regex  # noqa: F401
        except ImportError:
            self.skipTest('text-layout optional extra required')
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root/'graded.mp4'
            subprocess.run(['ffmpeg','-v','error','-nostdin','-n','-f','lavfi','-i',
                'color=blue:s=160x90:r=30:d=0.5','-f','lavfi','-i',
                'sine=frequency=440:sample_rate=48000:duration=0.5',
                '-vf','setparams=color_primaries=bt709:color_trc=bt709:colorspace=bt709',
                '-color_primaries','bt709','-color_trc','bt709','-colorspace','bt709',
                '-c:v','libx264','-pix_fmt','yuv420p','-c:a','aac',str(source)],
                check=True,capture_output=True)
            subtitles = root/'captions.srt'
            original = '1\n00:00:00,000 --> 00:00:00,400\nOne line\nNext line\n'
            subtitles.write_text(original)
            result = export_vertical(source, root/'output', subtitles=subtitles,
                caption_layout={'version': 1, 'language': 'en', 'protected_phrases': ['One line']})
            self.assertEqual((root/'output'/'subtitles.srt').read_text(), original)
            self.assertEqual(result['caption_lines'], [{'start': 0., 'end': .4,
                'text': 'One line\nNext line', 'lines': ['One line', 'Next line']}])
            self.assertEqual(result['caption_layout']['max_width'], 820)
            self.assertEqual(result['caption_layout']['max_lines'], 3)
            self.assertEqual(result['caption_layout']['max_codepoints'], 512)
            self.assertTrue(result['caption_layout']['runtime']['regex'])
            self.assertIsNone(result['caption_layout']['runtime']['budoux'])
            self.assertEqual(read(root/'output'/'result.json')['caption_lines'], result['caption_lines'])
            self.assertEqual(load_captions(subtitles, .5)[0]['text'], 'One line\nNext line')
