"""Deterministic source-frame mapping for local retime plans.

This module only compiles a plan. It does not resample audio, move captions, or
claim that a protected interval has been approved for a timing change.
"""

from __future__ import annotations

from fractions import Fraction
import math


def _integer(value: object, name: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ValueError(f"{name} must be an integer >= {minimum}")
    return value


def _speed(value: object, name: str) -> Fraction:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a finite number")
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError(f"{name} must be a finite number")
    speed = Fraction(str(value))
    if not Fraction(1, 4) <= speed <= 4:
        raise ValueError(f"{name} must be between 0.25 and 4")
    return speed


def _fps(value: object) -> Fraction:
    if not isinstance(value, str) or not value or value.strip() != value:
        raise ValueError("fps must be a positive rational string")
    try:
        rate = Fraction(value)
    except (ValueError, ZeroDivisionError) as exc:
        raise ValueError("fps must be a positive rational string") from exc
    if rate <= 0:
        raise ValueError("fps must be a positive rational string")
    return rate


def _protected(intervals: object, frame_count: int) -> list[tuple[int, int]]:
    if not isinstance(intervals, (list, tuple)):
        raise ValueError("protected_intervals must be a sequence")
    result = []
    for index, interval in enumerate(intervals):
        if not isinstance(interval, (list, tuple)) or len(interval) != 2:
            raise ValueError(f"protected_intervals[{index}] must be a pair")
        first = _integer(interval[0], f"protected_intervals[{index}][0]")
        end = _integer(interval[1], f"protected_intervals[{index}][1]")
        if first >= end or end > frame_count:
            raise ValueError(f"protected_intervals[{index}] is out of range")
        result.append((first, end))
    return result


def _overlaps(first: int, end: int, intervals: list[tuple[int, int]]) -> bool:
    return any(first < protected_end and protected_first < end
               for protected_first, protected_end in intervals)


def compile_retime(
    frame_count: int,
    fps: str,
    operations: list[dict],
    protected_intervals: list[tuple[int, int]] | tuple[tuple[int, int], ...] = (),
) -> dict:
    """Return a versioned output-to-source frame map and per-operation audit spans.

    Ramp samples use exact rational arithmetic. The final source boundary is
    exclusive, so it remains available to the following unchanged gap.
    """
    frame_count = _integer(frame_count, "frame_count", minimum=1)
    _fps(fps)
    if not isinstance(operations, list):
        raise ValueError("operations must be a list")
    protected = _protected(protected_intervals, frame_count)
    frame_map: list[int] = []
    spans: list[dict] = []
    seen_ids: set[str] = set()
    cursor = 0
    previous_position = -1

    for index, operation in enumerate(operations):
        if not isinstance(operation, dict):
            raise ValueError(f"operations[{index}] must be an object")
        kind = operation.get("kind")
        expected = ({"id", "kind", "source_first_frame", "source_end_frame_exclusive",
                     "speed_start", "speed_end", "reason"} if kind == "ramp" else
                    {"id", "kind", "source_frame", "output_frames", "reason"}
                    if kind == "freeze" else None)
        if expected is None or operation.keys() != expected:
            raise ValueError(f"operations[{index}] has an invalid kind or fields")
        op_id = operation["id"]
        reason = operation["reason"]
        if not isinstance(op_id, str) or not op_id.strip() or op_id in seen_ids:
            raise ValueError(f"operations[{index}].id must be unique and nonempty")
        if not isinstance(reason, str) or not reason.strip():
            raise ValueError(f"operations[{index}].reason must be nonempty")
        seen_ids.add(op_id)

        if kind == "ramp":
            first = _integer(operation["source_first_frame"], "source_first_frame")
            end = _integer(operation["source_end_frame_exclusive"],
                           "source_end_frame_exclusive")
            if end - first < 2 or end > frame_count:
                raise ValueError("ramp source span must contain at least two frames in range")
            speed_start = _speed(operation["speed_start"], "speed_start")
            speed_end = _speed(operation["speed_end"], "speed_end")
            if (speed_start != 1 or speed_end != 1) and _overlaps(first, end, protected):
                raise ValueError("ramp touches a protected interval")
            position = first
            if position <= previous_position or position < cursor:
                raise ValueError("operations must be sorted and nonoverlapping")
            frame_map.extend(range(cursor, first))
            output_first = len(frame_map)
            length = end - first
            output_count = round(Fraction(2 * length, 1) / (speed_start + speed_end))
            output_count = max(1, output_count)
            selected = []
            for k in range(output_count):
                t = Fraction(k, output_count)
                offset = Fraction(length, 1) * (
                    2 * speed_start * t + (speed_end - speed_start) * t * t
                ) / (speed_start + speed_end)
                selected.append(first + min(length - 1, offset.numerator // offset.denominator))
            frame_map.extend(selected)
            coverage = len(set(selected))
            spans.append({
                "id": op_id, "kind": kind, "reason": reason,
                "source_first_frame": first, "source_end_frame_exclusive": end,
                "output_first_frame": output_first,
                "output_end_frame_exclusive": len(frame_map),
                "requested_speed_start": str(speed_start),
                "requested_speed_end": str(speed_end),
                "effective_speed_start": selected[1] - selected[0] if output_count > 1 else None,
                "effective_speed_end": selected[-1] - selected[-2] if output_count > 1 else None,
                "source_coverage": {
                    "first_mapped_frame": selected[0], "last_mapped_frame": selected[-1],
                    "distinct_frames": coverage, "skipped_frames": length - coverage,
                },
            })
            cursor = end
        else:
            source_frame = _integer(operation["source_frame"], "source_frame")
            output_frames = _integer(operation["output_frames"], "output_frames", minimum=1)
            if source_frame >= frame_count:
                raise ValueError("freeze source_frame is out of range")
            if _overlaps(source_frame, source_frame + 1, protected):
                raise ValueError("freeze touches a protected interval")
            position = source_frame
            if position <= previous_position or position < cursor:
                raise ValueError("operations must be sorted and nonoverlapping")
            frame_map.extend(range(cursor, source_frame))
            output_first = len(frame_map)
            frame_map.extend([source_frame] * output_frames)
            spans.append({
                "id": op_id, "kind": kind, "reason": reason,
                "source_frame": source_frame, "output_first_frame": output_first,
                "output_end_frame_exclusive": len(frame_map),
                "effective_speed_start": 0, "effective_speed_end": 0,
                "source_coverage": {"first_mapped_frame": source_frame,
                                    "last_mapped_frame": source_frame,
                                    "distinct_frames": 1, "skipped_frames": 0},
            })
            cursor = source_frame
        previous_position = position

    frame_map.extend(range(cursor, frame_count))
    return {
        "version": 1, "fps": fps, "input_frame_count": frame_count,
        "output_frame_count": len(frame_map), "frame_map": frame_map,
        "spans": spans, "timing_changed": frame_map != list(range(frame_count)),
    }
