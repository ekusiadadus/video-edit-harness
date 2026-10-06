"""Place measured title cards beside observed tracking boxes, frame by frame."""

from __future__ import annotations

import math


_PLACEMENTS = frozenset({"above", "below", "left", "right"})
_FIELDS = frozenset({"placement", "gap_fraction", "offset_x", "offset_y"})


def _finite(value, name: str, low: float, high: float) -> float:
    if (isinstance(value, bool) or not isinstance(value, (int, float)) or
            not math.isfinite(value) or not low <= value <= high):
        raise ValueError(f"{name} must be a finite number from {low} to {high}")
    return float(value)


def _rectangle(value, name: str) -> tuple[float, float, float, float]:
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        raise ValueError(f"{name} must contain four normalized coordinates")
    x1, y1, x2, y2 = (_finite(item, name, 0, 1) for item in value)
    if x1 >= x2 or y1 >= y2:
        raise ValueError(f"{name} must have positive area")
    return x1, y1, x2, y2


def validate_follow_parameters(parameters: dict) -> dict:
    """Normalize only the placement controls accepted by a tracked title."""
    if not isinstance(parameters, dict) or set(parameters) - _FIELDS:
        raise ValueError("Follow parameters must contain only placement controls")
    placement = parameters.get("placement", "above")
    if not isinstance(placement, str) or placement not in _PLACEMENTS:
        raise ValueError("placement must be above, below, left, or right")
    return {
        "placement": placement,
        "gap_fraction": _finite(parameters.get("gap_fraction", .02), "gap_fraction", 0, .2),
        "offset_x": _finite(parameters.get("offset_x", 0), "offset_x", -.5, .5),
        "offset_y": _finite(parameters.get("offset_y", 0), "offset_y", -.5, .5),
    }


def compile_title_positions(track_rows: list[dict], first_frame: int, last_frame: int,
                            width: int, height: int, card_bounds: list[float],
                            parameters: dict) -> list[dict]:
    """Return exclusive-end frame positions; fail when observation or fit is absent.

    ``x_pixels`` and ``y_pixels`` translate the entire original full-frame PNG.
    Bounds describe the card after that integer-pixel translation.
    """
    controls = validate_follow_parameters(parameters)
    if (type(first_frame) is not int or type(last_frame) is not int or
            first_frame < 0 or last_frame <= first_frame):
        raise ValueError("Frame interval must be nonempty and exclusive-end")
    if (type(width) is not int or type(height) is not int or
            width <= 0 or height <= 0):
        raise ValueError("Frame dimensions must be positive integers")
    initial = _rectangle(card_bounds, "card_bounds")
    if not isinstance(track_rows, list) or len(track_rows) != last_frame - first_frame:
        raise ValueError("Tracking rows must exactly cover the requested frames")

    card_width = initial[2] - initial[0]
    card_height = initial[3] - initial[1]
    output = []
    for expected, row in enumerate(track_rows, first_frame):
        if (not isinstance(row, dict) or type(row.get("frame")) is not int or
                row["frame"] != expected or row.get("state") not in {"manual", "tracked"}):
            raise ValueError(f"Missing, lost, or unordered tracking row at frame {expected}")
        box = _rectangle(row.get("box"), f"tracking box at frame {expected}")
        x1, y1, x2, y2 = box
        gap = controls["gap_fraction"]
        placement = controls["placement"]
        if placement == "above":
            left = (x1 + x2 - card_width) / 2
            top = y1 - gap - card_height
        elif placement == "below":
            left = (x1 + x2 - card_width) / 2
            top = y2 + gap
        elif placement == "left":
            left = x1 - gap - card_width
            top = (y1 + y2 - card_height) / 2
        else:
            left = x2 + gap
            top = (y1 + y2 - card_height) / 2
        left += controls["offset_x"]
        top += controls["offset_y"]
        shift_x = round(left * width - initial[0] * width)
        shift_y = round(top * height - initial[1] * height)
        bounds = ((initial[0] * width + shift_x) / width,
                  (initial[1] * height + shift_y) / height,
                  (initial[2] * width + shift_x) / width,
                  (initial[3] * height + shift_y) / height)
        if any(not 0 <= value <= 1 for value in bounds):
            raise ValueError(f"Measured title card leaves the frame at frame {expected}")
        output.append({"frame": expected, "bounds": list(bounds),
                       "x_pixels": shift_x, "y_pixels": shift_y})
    return output
