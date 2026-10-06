"""Exact source correspondence for a composed visual transition timeline."""

from copy import deepcopy
from fractions import Fraction
from math import ceil, floor

from .render_cache import digest
from .transition_mapping import compile_transitions


def _checked(mapping, compiled):
    if not isinstance(mapping, dict) or "retime" in mapping or "transition" in mapping or "transitions" in mapping:
        raise ValueError("transitions require an unretimed, untransitioned visual mapping")
    if not isinstance(compiled, dict):
        raise ValueError("compiled transition proposal must be an object")
    try:
        expected = compile_transitions(mapping, compiled["request"], compiled["source_bindings"],
                                       compiled["actor"], compiled["reason"])
    except (KeyError, TypeError) as exc:
        raise ValueError("compiled transition proposal is incomplete") from exc
    try:
        exact = digest(compiled) == digest(expected)
    except (TypeError, ValueError) as exc:
        raise ValueError("compiled transition proposal is not serializable") from exc
    if not exact:
        raise ValueError("compiled transition proposal differs from canonical compilation")
    return expected


def attach_transitions(mapping, compiled):
    """Attach only an exact recompiled proposal; keep the cut sequence as reference."""
    proposal = _checked(mapping, compiled)
    attached = deepcopy(mapping)
    attached["transitions"] = {"version": 1, "compiled": deepcopy(proposal)}
    return attached


def _validate_attached(mapping):
    if not isinstance(mapping, dict):
        raise ValueError("transition mapping must be an object")
    attachment = mapping.get("transitions")
    if (not isinstance(attachment, dict) or set(attachment) != {"version", "compiled"}
            or type(attachment["version"]) is not int or attachment["version"] != 1):
        raise ValueError("transition attachment must be version 1 with compiled proposal")
    original = deepcopy(mapping)
    del original["transitions"]
    return original, _checked(original, attachment["compiled"])


def map_transition_output(mapping, start, end):
    """Map queried output frames to all decoded source frames, including handles."""
    original, proposal = _validate_attached(mapping)
    rate = Fraction(original["fps"])
    count = original["frame_count"]
    duration = float(original["duration"])
    if not 0 <= start <= end <= duration:
        raise ValueError("Feedback time is outside this render")
    # Feedback times arrive as binary floats. Recover simple frame-boundary
    # rationals before floor/ceil so 11/24 does not select frame 10.
    first = min(floor(Fraction(str(start)).limit_denominator(1_000_000_000) * rate), count - 1)
    last = (first + 1 if start == end else
            min(ceil(Fraction(str(end)).limit_denominator(1_000_000_000) * rate), count))
    rows = original["sequence"]
    bindings = proposal["source_bindings"]
    event_frames = {frame["output_frame"]: (event, frame)
                    for event in proposal["events"] for frame in event["frames"]}
    correspondences, spans = [], []
    for index in range(first, last):
        event_frame = event_frames.get(index)
        if event_frame:
            event, composed = event_frame
            sides = (("left", event["left_segment_id"]), ("right", event["right_segment_id"]))
            refs = []
            for side, segment_id in sides:
                source = composed[side]
                refs.append({"side": side, "sequence_id": segment_id, **source})
            item = {"output_frame": index, "event_id": event["id"],
                    "type": event["type"], "progress": composed["progress"], "references": refs}
            if event["type"] == "dissolve":
                item["weights"] = deepcopy(composed["weights"])
            else:
                item["spatial_operator"] = composed["spatial_operator"]
                item["direction"] = composed["direction"]
        else:
            row = next((row for row in rows if row["output_first_frame"] <= index < row["output_end_frame_exclusive"]), None)
            if row is None:
                raise ValueError("Visual mapping does not cover queried output frame")
            source_frame = row["source_frame_map"][index - row["output_first_frame"]]
            refs = [{"side": "base", "sequence_id": row["id"], "asset_id": row["asset_id"],
                     "source_sha256": row["source_sha256"], "source_frame": source_frame}]
            item = {"output_frame": index, "references": refs}
        correspondences.append(item)
        for ref in refs:
            source = bindings[ref["asset_id"]]
            frame = ref["source_frame"]
            source_rate = Fraction(source["fps"])
            spans.append({"sequence_id": ref["sequence_id"], "side": ref["side"],
                          "event_id": item.get("event_id"), "asset_id": ref["asset_id"],
                          "source_path": source["path"], "source_sha256": ref["source_sha256"],
                          "output_first_frame": index, "output_end_frame_exclusive": index + 1,
                          "output_start": float(Fraction(index, 1) / rate),
                          "output_end": float(Fraction(index + 1, 1) / rate),
                          "source_first_frame": frame, "source_end_frame_exclusive": frame + 1,
                          "source_start": float(Fraction(frame, 1) / source_rate),
                          "source_end": float(Fraction(frame + 1, 1) / source_rate)})
    from .feedback import _map_visual
    cut_reference = _map_visual(original, start, end)
    return {"output_start": start, "output_end": end, "source_spans": spans,
            "boundaries": [{**boundary, "scope": "original cut reference only"}
                           for boundary in cut_reference["boundaries"]],
            "frame_correspondence": correspondences,
            "source_time_scope": "discrete composed frame coverage",
            "cut_reference": {"label": "original cut reference only", **cut_reference}}
