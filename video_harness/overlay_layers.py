"""Sealed, lossless RGBA overlay samples for visual retiming.

The source passed to :func:`slice_overlay_layer` is the *rendered* full-timeline
layer.  This module never tries to reconstruct the overlay input clock.
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
from contextlib import ExitStack
from fractions import Fraction
from pathlib import Path


_REFERENCE_KEYS = {"path", "sha256", "bytes", "frame_count", "width", "height", "fps"}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _rate(value: object) -> Fraction:
    if isinstance(value, bool):
        raise ValueError("fps must be a positive rational number")
    try:
        rate = Fraction(str(value))
    except (ValueError, ZeroDivisionError, TypeError) as exc:
        raise ValueError("fps must be a positive rational number") from exc
    if rate <= 0:
        raise ValueError("fps must be positive")
    return rate


def _rate_text(rate: Fraction) -> str:
    return f"{rate.numerator}/{rate.denominator}"


def _integer(value: object, name: str, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise ValueError(f"{name} must be an integer in {minimum}..{maximum}")
    return value


def _probe(path: Path) -> dict:
    command = ["ffprobe", "-v", "error", "-select_streams", "v:0", "-count_frames",
               "-show_entries", "stream=codec_name,pix_fmt,width,height,avg_frame_rate,nb_read_frames",
               "-of", "json", str(path)]
    try:
        raw = subprocess.check_output(command, stderr=subprocess.PIPE)
        streams = json.loads(raw)["streams"]
        stream = streams[0]
        count = int(stream["nb_read_frames"])
        width = int(stream["width"])
        height = int(stream["height"])
        fps = _rate(stream["avg_frame_rate"])
    except (OSError, subprocess.CalledProcessError, KeyError, IndexError, ValueError, TypeError) as exc:
        raise ValueError(f"cannot count and inspect overlay layer: {path}") from exc
    if count < 1 or width < 1 or height < 1:
        raise ValueError("overlay layer has invalid geometry or frame count")
    return {"codec": stream.get("codec_name"), "pix_fmt": stream.get("pix_fmt"),
            "frame_count": count, "width": width, "height": height, "fps": fps}


def _log(stack: ExitStack, path: str | Path | None):
    if path is None:
        return stack.enter_context(open('/dev/null', 'wb'))
    log = Path(path)
    log.parent.mkdir(parents=True, exist_ok=True)
    return stack.enter_context(log.open("ab"))


def _command(log, command: list[str]) -> None:
    log.write(("COMMAND " + json.dumps(command) + "\n").encode())
    log.flush()


def _read_exact(stream, size: int) -> bytes:
    chunks = []
    remaining = size
    while remaining:
        chunk = stream.read(remaining)
        if not chunk:
            break
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def _remove_partial(path: Path) -> None:
    if path.exists():
        path.unlink()


def _check_sealed(path: Path, expected: str, expected_bytes: int | None = None) -> None:
    if expected_bytes is not None and path.stat().st_size != expected_bytes:
        raise ValueError("overlay layer size changed")
    if _sha256(path) != expected:
        raise ValueError("overlay layer SHA-256 changed")


def validate_overlay_layer_reference(reference, rate, *, count=None) -> dict:
    """Validate reference shape without accepting metadata as file proof."""
    if not isinstance(reference, dict) or set(reference) != _REFERENCE_KEYS:
        raise ValueError("overlay layer reference keys differ from sealed format")
    if (not isinstance(reference['path'], str) or not reference['path']
            or not Path(reference['path']).is_absolute()
            or not isinstance(reference['sha256'], str)
            or not re.fullmatch(r'[0-9a-f]{64}', reference['sha256'])):
        raise ValueError("overlay layer path or SHA-256 is invalid")
    actual_count = _integer(reference['frame_count'], 'frame_count', 1, 4096)
    _integer(reference['bytes'], 'bytes', 1, 2**63 - 1)
    _integer(reference['width'], 'width', 1, 2**31 - 1)
    _integer(reference['height'], 'height', 1, 2**31 - 1)
    fps = _rate(rate)
    if (not isinstance(reference['fps'], str) or reference['fps'] != _rate_text(fps)
            or (count is not None and actual_count != count)):
        raise ValueError("overlay layer count or fps differs from original cue")
    return dict(reference)


def slice_overlay_layer(source, first, end, rate, output, log_path=None) -> dict:
    """Seal output frames ``[first, end)`` from a rendered FFV1 RGBA layer."""
    source, output = Path(source), Path(output)
    fps = _rate(rate)
    _integer(first, "first", 0, 2**63 - 1)
    _integer(end, "end", 1, 2**63 - 1)
    if end <= first or end - first > 4096:
        raise ValueError("overlay slice must contain 1..4096 frames")
    if output.exists():
        raise FileExistsError(output)
    if not source.is_file():
        raise ValueError("overlay source is missing")
    before = _sha256(source)
    info = _probe(source)
    if info["codec"] != "ffv1" or info["pix_fmt"] not in {"bgra", "rgba"}:
        raise ValueError("overlay source must be FFV1 with alpha pixels")
    if info["fps"] != fps or end > info["frame_count"]:
        raise ValueError("overlay slice exceeds source frames or fps differs")
    output.parent.mkdir(parents=True, exist_ok=True)
    command = ["ffmpeg", "-hide_banner", "-nostdin", "-v", "error", "-i", str(source),
               "-vf", f"trim=start_frame={first}:end_frame={end},settb={fps.denominator}/{fps.numerator},setpts=N",
               "-an", "-c:v", "ffv1", "-level", "3", "-pix_fmt", "bgra",
               "-fps_mode", "passthrough", "-f", "matroska", str(output)]
    try:
        with ExitStack() as stack:
            log = _log(stack, log_path)
            _command(log, command)
            subprocess.run(command, stdout=log, stderr=log, check=True)
        _check_sealed(source, before)
        actual = _probe(output)
        if (actual["codec"] != "ffv1" or actual["pix_fmt"] not in {"bgra", "rgba"}
                or actual["frame_count"] != end - first or actual["fps"] != fps
                or (actual["width"], actual["height"]) != (info["width"], info["height"])):
            raise ValueError("sliced overlay did not preserve frame count, geometry and fps")
        return {"path": str(output.resolve()), "sha256": _sha256(output), "bytes": output.stat().st_size,
                "frame_count": end - first, "width": info["width"], "height": info["height"],
                "fps": _rate_text(fps)}
    except Exception:
        _remove_partial(output)
        raise


def remap_overlay_layer(reference, frames, rate, canvas_size, output, log_path=None) -> dict:
    """Emit exact decoded RGBA samples selected by a monotone source-frame map."""
    reference = validate_overlay_layer_reference(reference, rate)
    source, output = Path(reference["path"]), Path(output)
    if output.exists():
        raise FileExistsError(output)
    count = _integer(reference["frame_count"], "frame_count", 1, 4096)
    width = _integer(reference["width"], "width", 1, 2**31 - 1)
    height = _integer(reference["height"], "height", 1, 2**31 - 1)
    size = _integer(reference["bytes"], "bytes", 1, 2**63 - 1)
    fps = _rate(rate)
    if _rate(reference["fps"]) != fps:
        raise ValueError("overlay layer fps differs from output fps")
    if (not isinstance(canvas_size, (tuple, list)) or len(canvas_size) != 2
            or tuple(canvas_size) != (width, height)):
        raise ValueError("overlay layer does not match current canvas")
    if not isinstance(frames, (tuple, list)) or not 1 <= len(frames) <= 4096:
        raise ValueError("overlay remap must contain 1..4096 frames")
    previous = -1
    for frame in frames:
        _integer(frame, "source frame", 0, count - 1)
        if frame < previous:
            raise ValueError("overlay remap must be monotonic")
        previous = frame
    if not source.is_file() or not isinstance(reference["sha256"], str) or len(reference["sha256"]) != 64:
        raise ValueError("overlay layer reference is missing or invalid")
    _check_sealed(source, reference["sha256"], size)
    info = _probe(source)
    if (info["codec"] != "ffv1" or info["pix_fmt"] not in {"bgra", "rgba"}
            or info["frame_count"] != count or info["fps"] != fps
            or (info["width"], info["height"]) != (width, height)):
        raise ValueError("overlay layer codec, count, fps or geometry changed")
    output.parent.mkdir(parents=True, exist_ok=True)
    decode = ["ffmpeg", "-hide_banner", "-nostdin", "-v", "error", "-i", str(source),
              "-map", "0:v:0", "-fps_mode", "passthrough", "-f", "rawvideo",
              "-pix_fmt", "rgba", "pipe:1"]
    encode = ["ffmpeg", "-hide_banner", "-nostdin", "-v", "error", "-f", "rawvideo",
              "-pix_fmt", "rgba", "-s:v", f"{width}x{height}", "-r", _rate_text(fps),
              "-i", "pipe:0", "-an", "-c:v", "ffv1", "-level", "3", "-pix_fmt", "bgra",
              "-fps_mode", "passthrough", "-f", "matroska", str(output)]
    decoder = encoder = None
    try:
        with ExitStack() as stack:
            log = _log(stack, log_path)
            _command(log, decode)
            _command(log, encode)
            decoder = subprocess.Popen(decode, stdout=subprocess.PIPE, stderr=log)
            encoder = subprocess.Popen(encode, stdin=subprocess.PIPE, stdout=log, stderr=log)
            assert decoder.stdout is not None and encoder.stdin is not None
            frame_size = width * height * 4
            next_index = 0
            for index in range(count):
                pixels = _read_exact(decoder.stdout, frame_size)
                if len(pixels) != frame_size:
                    raise ValueError("overlay layer decoded fewer frames than sealed")
                while next_index < len(frames) and frames[next_index] == index:
                    encoder.stdin.write(pixels)
                    next_index += 1
            if decoder.stdout.read(1) or next_index != len(frames):
                raise ValueError("overlay layer decoded excess frames or remap is incomplete")
            decoder.stdout.close()
            encoder.stdin.close()
            if decoder.wait() or encoder.wait():
                raise ValueError("overlay layer decoder or encoder failed")
        _check_sealed(source, reference["sha256"], size)
        actual = _probe(output)
        if (actual["codec"] != "ffv1" or actual["pix_fmt"] not in {"bgra", "rgba"}
                or actual["frame_count"] != len(frames) or actual["fps"] != fps
                or (actual["width"], actual["height"]) != (width, height)):
            raise ValueError("remapped overlay did not preserve frame count, geometry and fps")
        return {"source_sha256": reference["sha256"], "frame_count": len(frames),
                "original_frame_count": count, "output_fps": _rate_text(fps),
                "content": "sealed_rgba_layer_remap", "path": str(output),
                "sha256": _sha256(output), "bytes": output.stat().st_size}
    except Exception:
        for process in (decoder, encoder):
            if process is not None and process.poll() is None:
                process.kill()
        for process in (decoder, encoder):
            if process is not None:
                process.wait()
        _remove_partial(output)
        raise
