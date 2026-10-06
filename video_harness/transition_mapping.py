"""Compile reviewed, source-bound visual transitions without touching media."""

from __future__ import annotations

from copy import deepcopy
from fractions import Fraction
import math

from .render_cache import digest
from .retime_mapping import conform_source_frames


def _integer(value, name, minimum=0):
    if type(value) is not int or value < minimum:
        raise ValueError(f"{name} must be an integer >= {minimum}")
    return value


def _rate(value, name):
    if not isinstance(value, str) or not value or value.strip() != value:
        raise ValueError(f"{name} must be a positive rational string")
    try:
        rate = Fraction(value)
    except (ValueError, ZeroDivisionError) as exc:
        raise ValueError(f"{name} must be a positive rational string") from exc
    if rate <= 0:
        raise ValueError(f"{name} must be a positive rational string")
    return rate


def _fraction(value):
    return f"{value.numerator}/{value.denominator}"


def _nonempty(value, name):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be nonempty text")
    return value


def _bindings(sources):
    if not isinstance(sources, dict) or not sources:
        raise ValueError("sources must be a nonempty asset mapping")
    bindings = {}
    for asset_id, source in sources.items():
        _nonempty(asset_id, "asset_id")
        if not isinstance(source, dict) or set(source) != {"path", "sha256", "bytes", "fps", "frame_count"}:
            raise ValueError("source binding requires path, sha256, bytes, fps, frame_count")
        path = _nonempty(source["path"], "source path")
        sha = _nonempty(source["sha256"], "source sha256")
        if len(sha) != 64 or any(c not in "0123456789abcdef" for c in sha):
            raise ValueError("source sha256 must be lowercase hexadecimal")
        size = _integer(source["bytes"], "source bytes", 1)
        _rate(source["fps"], "source fps")
        count = _integer(source["frame_count"], "source frame_count", 1)
        bindings[asset_id] = {"path": path, "sha256": sha, "bytes": size,
                              "fps": source["fps"], "frame_count": count}
    return bindings


def _rows(mapping, bindings):
    if not isinstance(mapping, dict) or mapping.get("version") != 4 or mapping.get("edit_basis") != "visual":
        raise ValueError("mapping must be visual version 4")
    if "retime" in mapping or "transitions" in mapping or "transition" in mapping:
        raise ValueError("retimed or already transitioned mapping is unsupported")
    count = _integer(mapping.get("frame_count"), "mapping frame_count", 1)
    fps = _rate(mapping.get("fps"), "mapping fps")
    try:
        duration = Fraction(str(mapping.get("duration")))
    except (ValueError, TypeError, ZeroDivisionError) as exc:
        raise ValueError("mapping duration is invalid") from exc
    if abs(duration - Fraction(count, 1) / fps) > Fraction(1, 1000000):
        raise ValueError("mapping duration differs from frame_count and fps")
    rows = mapping.get("sequence")
    if not isinstance(rows, list) or len(rows) < 2:
        raise ValueError("mapping needs at least two selected visual segments")
    cursor = 0
    ids = set()
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("mapping sequence row must be an object")
        identity = _nonempty(row.get("id"), "segment id")
        if identity in ids:
            raise ValueError("mapping segment ids must be unique")
        ids.add(identity)
        asset_id = _nonempty(row.get("asset_id"), "asset_id")
        if asset_id not in bindings:
            raise ValueError("mapping source binding missing")
        source = bindings[asset_id]
        if row.get("source_path") != source["path"] or row.get("source_sha256") != source["sha256"]:
            raise ValueError("mapping source path or SHA differs from binding")
        source_rate = _rate(row.get("source_fps"), "row source fps")
        if source_rate != _rate(source["fps"], "source fps"):
            raise ValueError("mapping source FPS differs from binding")
        if _rate(row.get("output_fps"), "row output fps") != fps:
            raise ValueError("mapping output FPS differs from mapping")
        first = _integer(row.get("output_first_frame"), "output first frame")
        end = _integer(row.get("output_end_frame_exclusive"), "output end frame", 1)
        source_first = _integer(row.get("source_first_frame"), "source first frame")
        source_end = _integer(row.get("source_end_frame_exclusive"), "source end frame", 1)
        if first != cursor or end <= first or source_end <= source_first or source_end > source["frame_count"]:
            raise ValueError("mapping rows must partition frame_count with valid source spans")
        canonical = conform_source_frames(source_first, source_end, source["fps"], end - first, mapping["fps"])
        actual = row.get("source_frame_map")
        if not isinstance(actual, list) or any(type(f) is not int for f in actual) or actual != canonical:
            raise ValueError("mapping source_frame_map differs from canonical conform")
        cursor = end
    if cursor != count:
        raise ValueError("mapping rows do not cover frame_count")
    return rows, count, fps


def _source_frame(row, output_frame, output_fps, source):
    relative = output_frame - row["output_first_frame"]
    selected = row["output_first_frame"] <= output_frame < row["output_end_frame_exclusive"]
    if selected:
        frame = row["source_frame_map"][relative]
    else:
        # CFR resampling can repeat a boundary frame, but a requested handle
        # still requires real material beyond the selected source interval.
        if (relative < 0 and row["source_first_frame"] == 0
                or relative >= len(row["source_frame_map"])
                and row["source_end_frame_exclusive"] == source["frame_count"]):
            raise ValueError("transition requires missing source pre/post handle")
        # Outside the selected range, no end-of-span clamping is permitted:
        # these are actual source handles, or compilation fails.
        frame = row["source_first_frame"] + math.ceil(
            (Fraction(relative, 1) + Fraction(1, 2)) *
            _rate(source["fps"], "source fps") / output_fps) - 1
    if not 0 <= frame < source["frame_count"]:
        raise ValueError("transition requires missing source pre/post handle")
    return {"asset_id": row["asset_id"], "source_sha256": source["sha256"],
            "source_frame": frame}


def compile_transitions(mapping: dict, request: dict, sources: dict, actor: str, reason: str) -> dict:
    """Return an unadopted frame-exact visual proposal from real source handles."""
    actor = _nonempty(actor, "actor")
    if actor not in {"human", "codex", "claude_code", "automation"}:
        raise ValueError("actor is invalid")
    reason = _nonempty(reason, "reason")
    bindings = _bindings(sources)
    rows, count, fps = _rows(mapping, bindings)
    if not isinstance(request, dict) or set(request) != {"version", "events"} or type(request["version"]) is not int or request["version"] != 1:
        raise ValueError("transition request must be version 1 with events")
    if not isinstance(request["events"], list) or not request["events"]:
        raise ValueError("transition request events must be nonempty")
    by_id = {row["id"]: i for i, row in enumerate(rows)}
    events = []
    seen = set()
    for requested in request["events"]:
        if not isinstance(requested, dict):
            raise ValueError("transition event must be an object")
        kind = requested.get("type")
        expected = {"id", "left_segment_id", "before_frames", "after_frames", "type", "reason"}
        if kind == "push":
            expected.add("direction")
        if set(requested) != expected or not isinstance(kind, str) or kind not in {"dissolve", "push"}:
            raise ValueError("transition event fields or type are invalid")
        identity = _nonempty(requested["id"], "event id")
        if identity in seen:
            raise ValueError("transition event ids must be unique")
        seen.add(identity)
        _nonempty(requested["reason"], "event reason")
        if kind == "push" and (not isinstance(requested["direction"], str)
                               or requested["direction"] not in {"left", "right", "up", "down"}):
            raise ValueError("push direction is invalid")
        left_id = _nonempty(requested["left_segment_id"], "left_segment_id")
        index = by_id.get(left_id)
        if index is None or index + 1 >= len(rows):
            raise ValueError("transition left_segment_id must identify an adjacent cut")
        left, right = rows[index:index + 2]
        before = _integer(requested["before_frames"], "before_frames", 1)
        after = _integer(requested["after_frames"], "after_frames", 1)
        if Fraction(before + after, 1) / fps > 1:
            raise ValueError("transition duration exceeds one second")
        if before + after > 120:
            raise ValueError("transition window exceeds 120 frames")
        if before > left["output_end_frame_exclusive"] - left["output_first_frame"] or after > right["output_end_frame_exclusive"] - right["output_first_frame"]:
            raise ValueError("transition window exceeds neighboring selected segments")
        cut = right["output_first_frame"]
        first, end = cut - before, cut + after
        frames = []
        total = end - first
        for j in range(first, end):
            progress = Fraction(j - first, total - 1)
            frame = {"output_frame": j,
                     "left": _source_frame(left, j, fps, bindings[left["asset_id"]]),
                     "right": _source_frame(right, j, fps, bindings[right["asset_id"]]),
                     "progress": _fraction(progress)}
            if kind == "dissolve":
                frame["weights"] = {"left": _fraction(1 - progress), "right": _fraction(progress)}
            else:
                frame["spatial_operator"] = "push"
                frame["direction"] = requested["direction"]
            frames.append(frame)
        event = {"id": identity, "type": kind, "left_segment_id": left_id,
                 "right_segment_id": right["id"], "first_frame": first,
                 "end_frame_exclusive": end, "frames": frames}
        if kind == "push":
            event["direction"] = requested["direction"]
        events.append(event)
    events.sort(key=lambda event: (event["first_frame"], event["end_frame_exclusive"]))
    for previous, current in zip(events, events[1:]):
        if previous["end_frame_exclusive"] > current["first_frame"]:
            raise ValueError("transition windows overlap")
    return {"version": 1, "input_mapping_sha256": digest(mapping),
            "request": deepcopy(request), "actor": actor, "reason": reason,
            "source_bindings": bindings, "fps": mapping["fps"], "frame_count": count,
            "audio_policy": "base_audio_unchanged", "review_required": True,
            "adopted": False, "events": events}
