"""Versioned contract for locally rendered visual effects.

The catalog describes supported effects; it does not execute expressions or
select effects for an edit. ``validate_parameters`` returns a new, complete
parameter dictionary so a saved event has explicit values for every control.
"""

from __future__ import annotations

from copy import deepcopy
import math


_EFFECTS = {
    "tracked_zoom": {
        "version": 1, "intent": "Emphasize an explicitly tracked local object; reject lost or stale tracking.",
        "input_count": 1, "backend": "local_burned",
        "parameters": {
            "track_path": {"type": "file", "default": None},
            "track_sha256": {"type": "sha256", "default": None},
            "max_scale": {"type": "number", "minimum": 1, "maximum": 1.5, "default": 1.12},
            "easing": {"type": "enum", "values": ["smoothstep", "cosine"], "default": "smoothstep"},
        },
    },
    "comparison_wipe": {
        "version": 1,
        "intent": "Compare the current picture with a separately registered video; retain base audio.",
        "input_count": 2,
        "backend": "local_burned",
        "parameters": {
            "asset_id": {"type": "text", "default": None},
            "asset_sha256": {"type": "sha256", "default": None},
            "source_start": {"type": "number", "minimum": 0.0, "maximum": 86400.0, "default": 0.0},
            "divider": {"type": "number", "minimum": 0.05, "maximum": 0.95, "default": 0.5},
            "layout": {"type": "enum", "values": ["wipe", "side_by_side"], "default": "wipe"},
        },
    },
    "smooth_zoom": {
        "version": 1,
        "intent": "Gently emphasize a subject while keeping the chosen anchor in frame.",
        "input_count": 1,
        "backend": "local_burned",
        "parameters": {
            "anchor_x": {"type": "number", "minimum": 0.0, "maximum": 1.0, "default": 0.5},
            "anchor_y": {"type": "number", "minimum": 0.0, "maximum": 1.0, "default": 0.5},
            "max_scale": {"type": "number", "minimum": 1.0, "maximum": 1.5, "default": 1.12},
            "easing": {"type": "enum", "values": ["smoothstep", "cosine"], "default": "smoothstep"},
        },
    },
    "saturation_pulse": {
        "version": 1,
        "intent": "Briefly reduce saturation to direct attention without changing timing.",
        "input_count": 1,
        "backend": "local_burned",
        "parameters": {
            "minimum_saturation": {"type": "number", "minimum": 0.0, "maximum": 1.0, "default": 0.0},
            "easing": {"type": "enum", "values": ["smoothstep", "cosine"], "default": "smoothstep"},
        },
    },
}


def catalog() -> dict:
    """Return an independently mutable, JSON-serializable v1 catalog."""
    effects = deepcopy(_EFFECTS)
    effects['keyword_title'] = {
        'version': 1, 'intent': 'Emphasize an explicitly chosen keyword with a measured readable card.',
        'input_count': 1, 'backend': 'local_burned',
        'parameters': {'text': {'type': 'text', 'maximum_length': 120},
                       'x': {'type': 'number', 'minimum': 0, 'maximum': 1, 'default': .5},
                       'y': {'type': 'number', 'minimum': 0, 'maximum': 1, 'default': .75},
                       'font_size_fraction': {'type': 'number', 'minimum': .02, 'maximum': .12, 'default': .05},
                       'foreground': {'type': 'color', 'default': '#FFFFFF'},
                       'background': {'type': 'color', 'default': '#171717'},
                       'motion': {'type': 'enum', 'values': ['fade', 'rise'], 'default': 'fade'},
                       'font_path': {'type': 'file', 'default': 'first available CJK system font'}}}
    return {"version": 1, "effects": effects}


def validate_parameters(kind: str, parameters: dict | None) -> dict:
    """Validate one effect's controls and fill defaults without mutating input."""
    if kind == 'keyword_title':
        from .text_effects import validate_text_parameters
        return validate_text_parameters(parameters or {})
    if kind not in _EFFECTS:
        raise ValueError(f"Unsupported effect kind: {kind!r}")
    if parameters is None:
        parameters = {}
    if not isinstance(parameters, dict):
        raise ValueError("Effect parameters must be an object")

    specs = _EFFECTS[kind]["parameters"]
    unknown = parameters.keys() - specs.keys()
    if unknown:
        raise ValueError(f"Unknown {kind} parameter(s): {', '.join(sorted(map(str, unknown)))}")

    normalized = {}
    for name, spec in specs.items():
        value = parameters.get(name, spec["default"])
        if spec["type"] == "number":
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError(f"{kind}.{name} must be a finite number")
            try:
                number = float(value)
            except (OverflowError, ValueError) as exc:
                raise ValueError(f"{kind}.{name} must be a finite number") from exc
            if not math.isfinite(number):
                raise ValueError(f"{kind}.{name} must be a finite number")
            if not spec["minimum"] <= number <= spec["maximum"]:
                raise ValueError(
                    f"{kind}.{name} must be between {spec['minimum']} and {spec['maximum']}"
                )
            normalized[name] = number
        elif spec['type'] == 'file':
            from pathlib import Path
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f'{kind}.{name} must reference a local file')
            path=Path(value).resolve(strict=True)
            if not path.is_file():
                raise ValueError(f'{kind}.{name} must reference a file')
            normalized[name]=str(path)
        elif spec['type'] in {'text', 'sha256'}:
            if spec['type'] == 'sha256' and value is None:
                normalized[name] = None
                continue
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f'{kind}.{name} must be nonempty text')
            if spec['type'] == 'sha256':
                import re
                if not re.fullmatch('[0-9a-f]{64}', value):
                    raise ValueError(f'{kind}.{name} must be a SHA-256')
            normalized[name] = value
        else:
            if not isinstance(value, str) or value not in spec["values"]:
                raise ValueError(f"{kind}.{name} must be one of {', '.join(spec['values'])}")
            normalized[name] = value
    return normalized
