"""Pitch-preserving audio for a compiled video retime mapping.

Unchanged intervals copy source PCM.  An inserted visual freeze is silent;
the original audio at that source frame resumes immediately afterward.  Ramps
use a phase vocoder driven by the compiler's continuous quadratic source-time
curve, rather than its quantized frame-map entries.
"""

from __future__ import annotations

from fractions import Fraction
import hashlib
import math
from pathlib import Path
import shlex
import shutil
import subprocess
import tempfile

import numpy as np


def _sample_boundary(frame: int, sample_rate: int, fps: Fraction) -> int:
    return round(Fraction(frame * sample_rate, 1) / fps)


def _fft_size(sample_rate: int, source_samples: int) -> int:
    # About 40 ms gives adequate frequency resolution for spoken voice while
    # keeping boundaries reasonably local.  Tiny clips need a smaller window.
    preferred = min(2048, max(256, 2 ** round(math.log2(sample_rate * .04))))
    return min(preferred, 2 ** int(math.log2(source_samples)))


def _vocoder_segment(
    source: np.ndarray, output_samples: int, speed_start: Fraction,
    speed_end: Fraction, sample_rate: int,
) -> tuple[np.ndarray, str]:
    if output_samples == len(source) and speed_start == speed_end == 1:
        return source.copy(), "pcm_copy"
    if not output_samples:
        return np.empty((0, source.shape[1]), dtype=np.float32), "empty"
    if len(source) < 64:
        raise ValueError("ramp has fewer than 64 source samples for pitch-preserving retime")

    try:
        import librosa
    except ImportError as exc:
        raise RuntimeError("audio retiming ramps require the optional librosa dependency") from exc

    n_fft = _fft_size(sample_rate, len(source))
    hop = n_fft // 4
    # One output STFT frame per output hop.  Positions are in source STFT
    # frames.  The same positions drive every channel to preserve stereo sync.
    output_centers = np.arange(0, output_samples, hop, dtype=np.float64)
    q = output_centers / output_samples
    a, b = float(speed_start), float(speed_end)
    source_positions = len(source) * (2 * a * q + (b - a) * q * q) / (a + b)
    time_steps = source_positions / hop
    spectra = np.stack(
        [librosa.stft(source[:, ch], n_fft=n_fft, hop_length=hop)
         for ch in range(source.shape[1])], axis=0,
    )
    # This follows librosa's phase-vocoder recurrence, replacing uniform
    # source time steps with the compiler's nonuniform quadratic positions.
    expected_advance = 2 * np.pi * hop * np.arange(n_fft // 2 + 1) / n_fft
    phase = np.angle(spectra[:, :, 0]).astype(np.float64)
    padded = np.pad(spectra, ((0, 0), (0, 0), (0, 2)))
    stretched = np.empty((source.shape[1], n_fft // 2 + 1, len(time_steps)),
                         dtype=np.complex64)
    for index, step in enumerate(time_steps):
        left = int(step)
        alpha = step - left
        first = padded[:, :, left]
        second = padded[:, :, left + 1]
        magnitude = (1 - alpha) * np.abs(first) + alpha * np.abs(second)
        stretched[:, :, index] = magnitude * np.exp(1j * phase)
        delta = np.angle(second) - np.angle(first) - expected_advance
        delta -= 2 * np.pi * np.round(delta / (2 * np.pi))
        phase += expected_advance + delta
    rendered = np.stack(
        [librosa.istft(stretched[ch], hop_length=hop, length=output_samples)
         for ch in range(source.shape[1])], axis=1,
    )
    return rendered.astype(np.float32), "nonuniform_phase_vocoder"


def _timemap_anchors(source_samples: int, output_samples: int,
                     speed_start: Fraction, speed_end: Fraction,
                     sample_rate: int) -> list[tuple[int, int]]:
    """Return strictly increasing integer (source, target) sample anchors."""
    count = min(1024, max(2, math.ceil(output_samples / (sample_rate * .02)) + 1))
    a, b = float(speed_start), float(speed_end)
    anchors = [(0, 0)]
    for target in np.linspace(0, output_samples, count)[1:-1]:
        target = round(float(target))
        q = target / output_samples
        source = round(source_samples * (2 * a * q + (b - a) * q * q) / (a + b))
        if source > anchors[-1][0] and target > anchors[-1][1]:
            anchors.append((source, target))
    while anchors[-1][0] >= source_samples or anchors[-1][1] >= output_samples:
        anchors.pop()
    anchors.append((source_samples, output_samples))
    return anchors


def _rubberband_segment(source: np.ndarray, output_samples: int,
                        speed_start: Fraction, speed_end: Fraction,
                        sample_rate: int, log_dir: Path | None) -> tuple[np.ndarray, dict]:
    if output_samples == len(source) and speed_start == speed_end == 1:
        return source.copy(), {"method": "pcm_copy", "sample_adjustment": 0}
    if len(source) < 64:
        raise ValueError("ramp has fewer than 64 source samples for pitch-preserving retime")
    executable = shutil.which("rubberband")
    if executable is None:
        raise RuntimeError("rubberband backend requested but rubberband executable is unavailable")
    try:
        import soundfile as sf
    except ImportError as exc:
        raise RuntimeError("rubberband backend requires the optional soundfile dependency") from exc

    version_result = subprocess.run([executable, "--version"], capture_output=True, text=True,
                                    check=True)
    version = version_result.stdout.strip() or version_result.stderr.strip()
    anchors = _timemap_anchors(len(source), output_samples, speed_start, speed_end,
                               sample_rate)
    anchor_text = "".join(f"{src} {dst}\n" for src, dst in anchors)
    anchor_sha = hashlib.sha256(anchor_text.encode("ascii")).hexdigest()
    log_path = None
    if log_dir is not None:
        log_dir.mkdir(parents=True, exist_ok=True)
        log_path = Path(tempfile.mkdtemp(prefix="rubberband-span-", dir=log_dir))
        (log_path / "timemap.txt").write_text(anchor_text, encoding="ascii")

    with tempfile.TemporaryDirectory(prefix="video-harness-rubberband-") as temporary:
        work = Path(temporary)
        input_wav, output_wav, timemap = (work / name for name in
                                          ("input.wav", "output.wav", "timemap.txt"))
        sf.write(input_wav, source, sample_rate, subtype="FLOAT")
        timemap.write_text(anchor_text, encoding="ascii")
        command = [executable, "--fine", "--time", format(output_samples / len(source), ".17g"),
                   "--timemap", str(timemap), str(input_wav), str(output_wav)]
        if log_path is not None:
            (log_path / "command.txt").write_text(shlex.join(command) + "\n", encoding="utf-8")
        completed = subprocess.run(command, capture_output=True, text=True)
        if log_path is not None:
            (log_path / "stdout.txt").write_text(completed.stdout, encoding="utf-8")
            (log_path / "stderr.txt").write_text(completed.stderr, encoding="utf-8")
        if completed.returncode:
            raise RuntimeError(f"rubberband failed (exit {completed.returncode}); "
                               f"log: {log_path or completed.stderr[-300:]}")
        rendered, actual_rate = sf.read(output_wav, dtype="float32", always_2d=True)
        if actual_rate != sample_rate or rendered.shape[1] != source.shape[1]:
            raise RuntimeError("rubberband output sample rate or channel count changed")

    actual_samples = len(rendered)
    adjustment = output_samples - actual_samples
    if abs(adjustment) > max(2, round(sample_rate * .01)):
        raise RuntimeError(f"rubberband duration differs by {adjustment} samples; "
                           f"log: {log_path}")
    if adjustment < 0:
        rendered = rendered[:output_samples]
    elif adjustment > 0:
        rendered = np.pad(rendered, ((0, adjustment), (0, 0)))
    detail = {"method": "rubberband_r3_timemap", "tool_version": version,
              "anchor_sha256": anchor_sha, "anchor_count": len(anchors),
              "actual_samples_before_adjustment": actual_samples,
              "sample_adjustment": adjustment,
              "log_dir": str(log_path) if log_path is not None else None}
    return rendered.astype(np.float32), detail


def retime_audio(samples: np.ndarray, sample_rate: int, mapping: dict, *,
                 backend: str = "phase_vocoder", log_dir: str | Path | None = None
                 ) -> tuple[np.ndarray, dict]:
    """Render samples aligned to ``compile_retime``'s output frame duration.

    ``samples`` has shape ``(sample_count, channels)`` and dtype float32.
    Extra source samples after the mapping's input duration are ignored.
    Unchanged intervals are sample-exact when source/output sample boundaries
    have equal lengths; at fractional FPS a shifted boundary can differ by one
    sample, so the boundary sample is held or dropped without interpolation.
    """
    if not isinstance(samples, np.ndarray) or samples.dtype != np.float32 or samples.ndim != 2:
        raise ValueError("samples must be a float32 array shaped (sample_count, channels)")
    if not samples.shape[0] or not samples.shape[1] or not np.isfinite(samples).all():
        raise ValueError("samples need at least one sample and channel with finite values")
    if isinstance(sample_rate, bool) or not isinstance(sample_rate, int) or sample_rate <= 0:
        raise ValueError("sample_rate must be a positive integer")
    if not isinstance(mapping, dict) or mapping.get("version") != 1:
        raise ValueError("mapping must be a compiled retime version 1")
    if backend not in ("phase_vocoder", "rubberband"):
        raise ValueError("backend must be phase_vocoder or rubberband")
    log_path = Path(log_dir) if log_dir is not None else None
    try:
        fps = Fraction(mapping["fps"])
        input_frames = mapping["input_frame_count"]
        output_frames = mapping["output_frame_count"]
        spans = mapping["spans"]
    except (KeyError, ValueError, TypeError, ZeroDivisionError) as exc:
        raise ValueError("invalid compiled retime mapping") from exc
    if fps <= 0 or not isinstance(input_frames, int) or not isinstance(output_frames, int):
        raise ValueError("invalid compiled retime dimensions")
    input_count = _sample_boundary(input_frames, sample_rate, fps)
    output_count = _sample_boundary(output_frames, sample_rate, fps)
    if len(samples) < input_count:
        raise ValueError(f"source audio is too short: need {input_count} samples")

    result = np.zeros((output_count, samples.shape[1]), dtype=np.float32)
    evidence_spans = []
    source_cursor = output_cursor = 0

    def copy_gap(source_first: int, output_first: int) -> None:
        nonlocal source_cursor, output_cursor
        src_start = _sample_boundary(source_cursor, sample_rate, fps)
        src_end = _sample_boundary(source_first, sample_rate, fps)
        out_start = _sample_boundary(output_cursor, sample_rate, fps)
        out_end = _sample_boundary(output_first, sample_rate, fps)
        source_length = src_end - src_start
        target_length = out_end - out_start
        if target_length:
            if not source_length:
                raise ValueError("unchanged interval has no source audio")
            offsets = np.minimum(np.arange(target_length), source_length - 1)
            result[out_start:out_end] = samples[src_start + offsets]

    for span in spans:
        kind = span["kind"]
        output_first = span["output_first_frame"]
        output_end = span["output_end_frame_exclusive"]
        source_first = span["source_first_frame"] if kind == "ramp" else span["source_frame"]
        source_end = span["source_end_frame_exclusive"] if kind == "ramp" else source_first
        if (source_first < source_cursor or output_first < output_cursor or
                source_end > input_frames or output_end > output_frames or
                source_first - source_cursor != output_first - output_cursor):
            raise ValueError("invalid retime span order or unchanged gap")
        copy_gap(source_first, output_first)
        out_start = _sample_boundary(output_first, sample_rate, fps)
        out_end = _sample_boundary(output_end, sample_rate, fps)
        if kind == "ramp":
            src_start = _sample_boundary(source_first, sample_rate, fps)
            src_end = _sample_boundary(source_end, sample_rate, fps)
            start_speed = Fraction(span["requested_speed_start"])
            end_speed = Fraction(span["requested_speed_end"])
            if min(start_speed, end_speed) <= 0:
                raise ValueError("ramp speeds must be positive")
            if backend == "rubberband":
                piece, detail = _rubberband_segment(samples[src_start:src_end],
                                                    out_end - out_start,
                                                    start_speed, end_speed, sample_rate,
                                                    log_path)
                method = detail["method"]
            else:
                piece, method = _vocoder_segment(samples[src_start:src_end],
                                                 out_end - out_start,
                                                 start_speed, end_speed, sample_rate)
                detail = {"method": method}
            result[out_start:out_end] = piece
            source_cursor = source_end
        elif kind == "freeze":
            method = "inserted_silence"
            detail = {"method": method}
            # The compiler leaves source_cursor at this frame.  Audio resumes
            # from the original frame in the following unchanged interval.
            source_cursor = source_first
        else:
            raise ValueError(f"unsupported retime span kind: {kind}")
        output_cursor = output_end
        evidence_spans.append({"id": span["id"], "kind": kind, **detail,
                               "output_first_sample": out_start,
                               "output_end_sample_exclusive": out_end})
    if input_frames - source_cursor != output_frames - output_cursor:
        raise ValueError("invalid trailing unchanged gap")
    copy_gap(input_frames, output_frames)
    if not np.isfinite(result).all():
        raise RuntimeError("retimed audio contains non-finite samples")
    evidence = {"input_samples_used": input_count, "output_samples": output_count,
                "channels": samples.shape[1], "sample_rate": sample_rate,
                "backend": backend,
                "samples_over_full_scale": int(np.count_nonzero(np.abs(result) > 1)),
                "freeze_audio_policy": "inserted_silence_then_resume_source_pcm",
                "spans": evidence_spans}
    return result, evidence
