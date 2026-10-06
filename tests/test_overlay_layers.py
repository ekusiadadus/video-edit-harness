"""Pixel and contract tests for sealed rendered overlay layers."""

import hashlib
import subprocess
from pathlib import Path

import tempfile
import unittest

from video_harness.overlay_layers import remap_overlay_layer, slice_overlay_layer


def _source(path: Path, colors: list[tuple[int, int, int, int]], fps="3/1"):
    pixels = b"".join(bytes(color) * 4 for color in colors)  # 2x2 RGBA frames
    subprocess.run(["ffmpeg", "-hide_banner", "-v", "error", "-f", "rawvideo",
                    "-pix_fmt", "rgba", "-s:v", "2x2", "-r", fps, "-i", "pipe:0",
                    "-c:v", "ffv1", "-level", "3", "-pix_fmt", "bgra", "-f", "matroska",
                    str(path)], input=pixels, check=True, capture_output=True)


def _pixels(path: Path) -> list[bytes]:
    raw = subprocess.check_output(["ffmpeg", "-hide_banner", "-v", "error", "-i", str(path),
                                   "-map", "0:v:0", "-fps_mode", "passthrough", "-f", "rawvideo",
                                   "-pix_fmt", "rgba", "pipe:1"])
    assert len(raw) % 16 == 0
    return [raw[i:i + 16] for i in range(0, len(raw), 16)]


def _setup(tmp_path):
    colors = [(10, 20, 30, 40), (50, 60, 70, 80), (90, 100, 110, 120),
              (130, 140, 150, 160)]
    source = tmp_path / "full.mkv"
    _source(source, colors)
    reference = slice_overlay_layer(source, 1, 4, "3/1", tmp_path / "slice.mkv")
    return source, reference, colors


class OverlayLayerTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)

    def test_slice_and_remap_preserve_exact_rgba(self):
        source, reference, _ = _setup(self.root)
        self.assertEqual(set(reference), {"path", "sha256", "bytes", "frame_count", "width", "height", "fps"})
        self.assertEqual(reference["frame_count"], 3)
        self.assertEqual(reference["fps"], "3/1")
        self.assertEqual(_pixels(Path(reference["path"])), _pixels(source)[1:4])
        output = self.root / "mapped.mkv"
        result = remap_overlay_layer(reference, [0, 2, 2], "3/1", (2, 2), output)
        originals = _pixels(source)
        self.assertEqual(_pixels(output), [originals[1], originals[3], originals[3]])
        self.assertEqual(result["content"], "sealed_rgba_layer_remap")
        self.assertEqual(result["source_sha256"], reference["sha256"])
        self.assertEqual(result["frame_count"], 3)
        self.assertEqual(result["original_frame_count"], 3)

    def test_stale_and_mismatched_references(self):
        _, reference, _ = _setup(self.root)
        changes = {"sha256": "0" * 64, "bytes": reference["bytes"] + 1,
                   "frame_count": 2, "width": 4, "fps": "4/1", "extra": "unexpected"}
        for key, value in changes.items():
            with self.subTest(key=key):
                changed = {**reference, key: value}
                output = self.root / "reject.mkv"
                with self.assertRaises(ValueError):
                    remap_overlay_layer(changed, [0], "3/1", (2, 2), output)
                self.assertFalse(output.exists())

    def test_invalid_frame_maps(self):
        _, reference, _ = _setup(self.root)
        for frames in [[1, 0], [-1], [3], [], [0] * 4097, [0, 1.0], [True]]:
            with self.subTest(length=len(frames), first=frames[:2]):
                with self.assertRaises(ValueError):
                    remap_overlay_layer(reference, frames, "3/1", (2, 2), self.root / "reject.mkv")

    def test_preview_size_and_existing_output(self):
        source, reference, _ = _setup(self.root)
        with self.assertRaisesRegex(ValueError, "canvas"):
            remap_overlay_layer(reference, [0], "3/1", (1, 1), self.root / "reject.mkv")
        with self.assertRaises(FileExistsError):
            slice_overlay_layer(source, 0, 1, "3/1", Path(reference["path"]))

    def test_mutated_layer_same_byte_count(self):
        _, reference, _ = _setup(self.root)
        path = Path(reference["path"])
        payload = bytearray(path.read_bytes())
        payload[-1] ^= 1
        path.write_bytes(payload)
        self.assertNotEqual(hashlib.sha256(payload).hexdigest(), reference["sha256"])
        with self.assertRaisesRegex(ValueError, "SHA-256"):
            remap_overlay_layer(reference, [0], "3/1", (2, 2), self.root / "reject.mkv")


if __name__ == "__main__":
    unittest.main()
