"""Local media checks for the labelled BEFORE/AFTER demo wrapper."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "build_demo_comparison.py"
SPEC = importlib.util.spec_from_file_location("build_demo_comparison", SCRIPT)
comparison = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(comparison)


def fixture(path: Path, *, seconds: int, color: str, fps: str = "25") -> None:
    subprocess.run(
        ["ffmpeg", "-v", "error", "-nostdin", "-y",
         "-f", "lavfi", "-i", f"color=c={color}:s=160x90:r={fps}:d={seconds}",
         "-f", "lavfi", "-i", f"sine=frequency=440:sample_rate=48000:duration={seconds}",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
         "-ar", "48000", "-ac", "2", "-shortest", str(path)],
        check=True, capture_output=True,
    )


class DemoComparisonTest(unittest.TestCase):
    def test_build_keeps_audio_and_durations(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            before, after = root / "before.mp4", root / "after.mp4"
            fixture(before, seconds=1, color="blue", fps="24000/1001")
            fixture(after, seconds=2, color="red", fps="24000/1001")
            beats = root / "beats.json"
            beats.write_text(json.dumps({"beats": [0.3, 0.5, 1.4, 1.5]}))
            result = comparison.build(before, after, beats, root / "output")
            self.assertEqual(result["selected_beat_times"], [0.3, 1.4])
            self.assertEqual(result["fps"], "24000/1001")
            self.assertAlmostEqual(result["after_pulse"]["duration"], 2, delta=1 / 24)
            self.assertAlmostEqual(result["comparison"]["duration"], 3, delta=2 / 24)
            for name in ("after-pulse.mp4", "comparison.mp4"):
                info = comparison._probe(root / "output" / name)
                self.assertTrue(any(s["codec_name"] == "h264" for s in info["streams"]))
                self.assertTrue(any(s["codec_name"] == "aac" for s in info["streams"]))
            self.assertTrue((root / "output" / "manifest.json").is_file())

    def test_rejects_missing_embedded_audio_and_out_of_bounds_beats(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            with_audio = root / "with.mp4"
            fixture(with_audio, seconds=1, color="blue")
            no_audio = root / "silent.mp4"
            subprocess.run(["ffmpeg", "-v", "error", "-nostdin", "-y", "-i",
                            str(with_audio), "-an", "-c:v", "copy", str(no_audio)],
                           check=True, capture_output=True)
            beats = root / "beats.json"
            beats.write_text("[0.3]")
            with self.assertRaisesRegex(ValueError, "embedded audio"):
                comparison.build(no_audio, with_audio, beats, root / "output")
            beats.write_text("[2]")
            other_audio = root / "other.mp4"
            fixture(other_audio, seconds=1, color="red")
            with self.assertRaisesRegex(ValueError, "outside"):
                comparison.build(with_audio, other_audio, beats, root / "output")


if __name__ == "__main__":
    unittest.main()
