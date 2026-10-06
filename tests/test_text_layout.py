import unittest
from unittest.mock import patch

from video_harness.text_layout import wrap_text


class TextLayoutTests(unittest.TestCase):
    def test_english_uses_measured_width_and_keeps_words(self):
        measure = lambda value: sum(5 if character == "W" else 1 for character in value)
        self.assertEqual(wrap_text("W ii", "en", 6, measure), ["W", "ii"])

    def test_english_does_not_split_unbreakable_word(self):
        with self.assertRaisesRegex(ValueError, "Unbreakable text"):
            wrap_text("unbreakable", "en", 5, len)
        with self.assertRaisesRegex(ValueError, "Unbreakable text"):
            wrap_text("unfit\na a a a a a a a a a", "en", 3, len, max_lines=20)

    def test_explicit_lines_and_spaces_are_preserved(self):
        self.assertEqual(wrap_text("one  two\n\nthree", "en", 20, len),
                         ["one  two", "", "three"])
        self.assertEqual(wrap_text("one  two", "en", 4, len), ["one", "two"])

    def test_japanese_breaks_avoid_hanging_punctuation(self):
        text = "今日は「良い日」です。"
        lines = wrap_text(text, "ja", 5, len, max_lines=6)
        self.assertEqual("".join(lines), text)
        self.assertTrue(all(len(line) <= 5 for line in lines))
        self.assertTrue(all(not line.endswith("「") for line in lines[:-1]))
        self.assertTrue(all(not line.startswith(("。", "、", "」")) for line in lines[1:]))

    def test_protected_phrase_stays_on_one_line(self):
        text = "今日は東京タワーに行く"
        lines = wrap_text(text, "ja", 6, len, protected_phrases=("東京タワー",))
        self.assertEqual("".join(lines), text)
        self.assertTrue(any("東京タワー" in line for line in lines))

    def test_number_and_unit_stay_together(self):
        text = "参加者は120人です"
        lines = wrap_text(text, "ja", 5, len)
        self.assertEqual("".join(lines), text)
        self.assertTrue(any("120人" in line for line in lines))
        with self.assertRaisesRegex(ValueError, "Unbreakable text"):
            wrap_text("120人", "ja", 3, len)

    def test_video_audio_number_units_stay_together(self):
        for token in ("24 fps", "48 kHz", "16 LUFS", "30 秒", "1080 px"):
            with self.subTest(token=token):
                text = f"設定は{token}です"
                lines = wrap_text(text, "ja", len(token), len, max_lines=8)
                self.assertTrue(any(token in line for line in lines), lines)
                with self.assertRaisesRegex(ValueError, "Unbreakable text"):
                    wrap_text(token, "ja", len(token) - 1, len)

    def test_japanese_fallback_keeps_latin_words_intact(self):
        text = "編集はFinal Cut Proです"
        lines = wrap_text(text, "ja", 6, len, max_lines=8)
        self.assertTrue(any("Final" in line for line in lines))
        self.assertTrue(any("Cut" in line for line in lines))
        self.assertTrue(any("Pro" in line for line in lines))
        with self.assertRaisesRegex(ValueError, "Unbreakable text"):
            wrap_text("OpenAI", "ja", 4, len)

    def test_grapheme_cluster_is_not_split(self):
        text = "あ👩‍💻い"
        lines = wrap_text(text, "ja", 2, lambda value: len(value.replace("👩‍💻", "X")))
        self.assertEqual("".join(lines), text)
        self.assertTrue(any("👩‍💻" in line for line in lines))

    def test_english_break_does_not_remove_part_of_grapheme(self):
        with self.assertRaisesRegex(ValueError, "Unbreakable text"):
            wrap_text("a \u0301b", "en", 2, len)
        text = "a 👩‍💻"
        lines = wrap_text(text, "en", 1,
                          lambda value: len(value.replace("👩‍💻", "X")))
        self.assertEqual(lines, ["a", "👩‍💻"])

    def test_line_limit_is_an_error(self):
        with self.assertRaisesRegex(ValueError, "max_lines"):
            wrap_text("one two six", "en", 4, len, max_lines=2)
        with self.assertRaisesRegex(ValueError, "max_lines"):
            wrap_text("one\ntwo\nthree", "en", 10, len, max_lines=2)

    def test_preferred_break_cannot_cause_false_line_overflow(self):
        # A short phrase boundary needs three lines; a later grapheme break fits two.
        with patch("video_harness.text_layout._japanese_boundaries", return_value={2}):
            self.assertEqual(wrap_text("あいうえおかきく", "ja", 4, len, max_lines=2),
                             ["あいうえ", "おかきく"])


if __name__ == "__main__":
    unittest.main()
