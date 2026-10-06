"""Translate a compiled retime through a rendered visual edit's source mapping."""

from __future__ import annotations

from bisect import bisect_right
from copy import deepcopy
from fractions import Fraction
import math

from .render_cache import digest


def _rate(value, label):
    try:
        if not isinstance(value, str) or not value or value.strip() != value:
            raise ValueError
        result = Fraction(value)
        if result <= 0:
            raise ValueError
    except (ValueError, ZeroDivisionError) as exc:
        raise ValueError(f"{label} must be a positive rational string") from exc
    return result


def _integer(value, label, minimum=0):
    if type(value) is not int or value < minimum:
        raise ValueError(f"{label} must be an integer >= {minimum}")
    return value


def _time(value):
    value = Fraction(value)
    return f"{value.numerator}/{value.denominator}s" if value.denominator != 1 else f"{value.numerator}s"


def conform_source_frames(source_first: int, source_end: int, source_fps: str,
                          output_count: int, output_fps: str) -> list[int]:
    """Map normalized CFR source frames through FFmpeg fps=...:round=near.

    The visual renderer explicitly trims by frame index and assigns exact
    rational source timestamps (settb/setpts) before its fps filter.
    """
    first = _integer(source_first, "source_first")
    end = _integer(source_end, "source_end", 1)
    count = _integer(output_count, "output_count", 1)
    if end <= first:
        raise ValueError("source frame span is empty")
    source_rate = _rate(source_fps, "source_fps")
    output_rate = _rate(output_fps, "output_fps")
    # The latest source frame i whose nearest output timestamp is <= output j.
    # This is ceil((j + 1/2) * source_fps/output_fps) - 1, clamped to the span.
    return [first + min(end - first - 1, max(0, math.ceil(
        (Fraction(j, 1) + Fraction(1, 2)) * source_rate / output_rate) - 1))
        for j in range(count)]


def remap_visual_mapping(original_mapping: dict, compiled_retime: dict) -> dict:
    """Bind each retimed output frame to its original video source frame.

    A visual row's source_frame_map records FFmpeg frame selection after the
    renderer normalizes source timestamps to exact CFR. Old rows can be mapped
    only at equal source/output rates with one-to-one frame counts.
    """
    if not isinstance(original_mapping, dict) or original_mapping.get("version") != 4 or original_mapping.get("edit_basis") != "visual":
        raise ValueError("original mapping must be visual version 4")
    if not isinstance(compiled_retime, dict) or compiled_retime.get("version") != 1:
        raise ValueError("compiled retime must be version 1")
    count = _integer(original_mapping.get("frame_count"), "original frame_count", 1)
    fps = _rate(original_mapping.get("fps"), "original fps")
    try:
        duration = Fraction(str(original_mapping.get("duration")))
    except (ValueError, TypeError, ZeroDivisionError) as exc:
        raise ValueError("original mapping duration is invalid") from exc
    if abs(duration - Fraction(count, 1) / fps) > Fraction(1, 1000000):
        raise ValueError("original mapping duration differs from frame dimensions")
    if compiled_retime.get("input_frame_count") != count or _rate(compiled_retime.get("fps"), "retime fps") != fps:
        raise ValueError("compiled retime input dimensions or fps differ from original mapping")
    frame_map = compiled_retime.get("frame_map")
    output_count = _integer(compiled_retime.get("output_frame_count"), "retime output_frame_count", 1)
    if not isinstance(frame_map, list) or len(frame_map) != output_count:
        raise ValueError("compiled retime frame_map length differs from output_frame_count")
    previous_base = -1
    for base in frame_map:
        if type(base) is not int or not previous_base <= base < count:
            raise ValueError("compiled retime frame indices must be nondecreasing and in bounds")
        previous_base = base
    rows = original_mapping.get("sequence")
    if not isinstance(rows, list) or not rows:
        raise ValueError("original visual sequence must be nonempty")
    ends = []
    cursor = 0
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("visual sequence row must be an object")
        first = _integer(row.get("output_first_frame"), "output_first_frame")
        end = _integer(row.get("output_end_frame_exclusive"), "output_end_frame_exclusive", 1)
        source_first = _integer(row.get("source_first_frame"), "source_first_frame")
        source_end = _integer(row.get("source_end_frame_exclusive"), "source_end_frame_exclusive", 1)
        _rate(row.get("source_fps"), "source_fps")
        if "output_fps" in row and _rate(row["output_fps"], "row output_fps") != fps:
            raise ValueError("visual sequence output fps differs from original mapping")
        if first != cursor or end <= first or source_end <= source_first:
            raise ValueError("original visual sequence has gap, overlap, or empty span")
        for field in ("asset_id", "source_path", "source_sha256"):
            if not isinstance(row.get(field), str) or not row[field]:
                raise ValueError(f"visual sequence requires {field}")
        frame_sources = row.get("source_frame_map")
        if "source_frame_map" not in row:
            if _rate(row["source_fps"], "source_fps") != fps or source_end - source_first != end - first:
                raise ValueError("visual sequence needs source_frame_map for FPS conform")
        elif (not isinstance(frame_sources, list) or len(frame_sources) != end - first or
              any(type(frame) is not int or not source_first <= frame < source_end
                  for frame in frame_sources) or
              any(b < a for a, b in zip(frame_sources, frame_sources[1:]))):
            raise ValueError("visual sequence source_frame_map is invalid")
        ends.append(end)
        cursor = end
    if cursor != count:
        raise ValueError("original visual sequence does not cover frame_count")

    references = []
    sequence = []
    for output_frame, base in enumerate(frame_map):
        row = rows[bisect_right(ends, base)]
        offset = base - row["output_first_frame"]
        source_frame = (row["source_frame_map"][offset] if "source_frame_map" in row
                        else row["source_first_frame"] + offset)
        source_fps = _rate(row["source_fps"], "source_fps")
        ref = {"output_frame": output_frame, "base_output_frame": base,
               "asset_id": row["asset_id"], "source_frame": source_frame,
               "source_fps": row["source_fps"], "source_sha256": row["source_sha256"],
               "source_path": row["source_path"]}
        references.append(ref)
        last = sequence[-1] if sequence else None
        same_source = last is not None and all(last[key] == ref[key] for key in
            ("asset_id", "source_fps", "source_sha256", "source_path"))
        if same_source and last["source_end_frame_exclusive"] == source_frame:
            last["source_end_frame_exclusive"] = source_frame + 1
            last["output_end_frame_exclusive"] = output_frame + 1
            last["source_end"] = _time(Fraction(source_frame + 1, 1) / source_fps)
            last["output_end"] = _time(Fraction(output_frame + 1, 1) / fps)
        else:
            sequence.append({"id": f"retime-{len(sequence) + 1}",
                             "asset_id": ref["asset_id"], "source_path": ref["source_path"],
                             "source_sha256": ref["source_sha256"], "source_fps": ref["source_fps"],
                             "output_fps": original_mapping["fps"],
                             "source_first_frame": source_frame,
                             "source_end_frame_exclusive": source_frame + 1,
                             "output_first_frame": output_frame,
                             "output_end_frame_exclusive": output_frame + 1,
                             "source_start": _time(Fraction(source_frame, 1) / source_fps),
                             "source_end": _time(Fraction(source_frame + 1, 1) / source_fps),
                             "output_start": _time(Fraction(output_frame, 1) / fps),
                             "output_end": _time(Fraction(output_frame + 1, 1) / fps)})
    result = deepcopy(original_mapping)
    result.update(duration=float(Fraction(output_count, 1) / fps), frame_count=output_count,
                  sequence=sequence, retime={"input_mapping_sha256": digest(original_mapping),
                                             "compiled_mapping": deepcopy(compiled_retime),
                                             "frames": references})
    return result
