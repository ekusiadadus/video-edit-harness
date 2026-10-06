"""Render a measured, transparent title card for a reviewed text cue."""

from __future__ import annotations

import hashlib
import importlib.metadata
import io
import json
import math
from pathlib import Path
import re
import unicodedata

from PIL import Image, ImageDraw, ImageFont

from .doctor import FONT_PATHS


_FIELDS = frozenset({"text", "x", "y", "font_size_fraction", "foreground",
                     "background", "motion", "font_path"})
_COLOR = re.compile(r"#[0-9A-Fa-f]{6}\Z")
_LAYOUT_FIELDS = frozenset({'language', 'max_width_fraction', 'max_lines', 'protected_phrases'})


def layout_binding() -> dict:
    """Bind the optional local layout engine and its Japanese model."""
    try:
        import budoux
        import regex
    except ImportError as error:
        raise ValueError('Install the text-layout extra for version-2 titles') from error
    model = budoux.load_default_japanese_parser().model
    return {'budoux': importlib.metadata.version('budoux'),
            'regex': importlib.metadata.version('regex'),
            'model_sha256': hashlib.sha256(json.dumps(model, sort_keys=True,
                                                     separators=(',', ':')).encode()).hexdigest()}


def validate_text_parameters(parameters: dict, *, version: int = 1) -> dict:
    """Return normalized title-card settings, rejecting unsupported values."""
    if type(version) is not int or version not in (1, 2):
        raise ValueError('Unsupported text effect version')
    if not isinstance(parameters, dict) or set(parameters) - (_FIELDS | (_LAYOUT_FIELDS if version == 2 else set())):
        raise ValueError("Text parameters must be a dictionary of supported fields")
    value = parameters.get("text")
    if not isinstance(value, str) or not value.strip() or len(value) > 120:
        raise ValueError("Text must contain 1 to 120 characters")
    if len(value.split("\n")) > 3 or any(
        character != "\n" and unicodedata.category(character) in {"Cc", "Cs"}
        for character in value
    ):
        raise ValueError("Text must contain at most three lines and no control characters")

    normalized = {"text": value}
    for name, default, low, high in (("x", .5, 0, 1), ("y", .75, 0, 1),
                                     ("font_size_fraction", .05, .02, .12)):
        number = parameters.get(name, default)
        if isinstance(number, bool) or not isinstance(number, (int, float)) or not math.isfinite(number) or not low <= number <= high:
            raise ValueError(f"{name} must be a finite number from {low} to {high}")
        normalized[name] = float(number)
    for name, default in (("foreground", "#FFFFFF"), ("background", "#171717")):
        color = parameters.get(name, default)
        if not isinstance(color, str) or not _COLOR.fullmatch(color):
            raise ValueError(f"{name} must be #RRGGBB")
        normalized[name] = color.upper()
    def luminance(color):
        channels = [component / 255 for component in bytes.fromhex(color[1:])]
        linear = [component / 12.92 if component <= .04045 else ((component + .055) / 1.055) ** 2.4
                  for component in channels]
        return sum(component * weight for component, weight in zip(linear, (.2126, .7152, .0722)))
    foreground, background = luminance(normalized['foreground']), luminance(normalized['background'])
    if (max(foreground, background) + .05) / (min(foreground, background) + .05) < 4.5:
        raise ValueError('Text foreground/background contrast must be at least 4.5:1')
    motion = parameters.get("motion", "fade")
    if motion not in ("fade", "rise"):
        raise ValueError("motion must be fade or rise")
    normalized["motion"] = motion

    requested = parameters.get("font_path")
    if requested is None:
        requested = next((path for path in FONT_PATHS if Path(path).is_file()), None)
    if not isinstance(requested, (str, Path)) or not Path(requested).is_file():
        raise ValueError("A readable TrueType/OpenType font file is required")
    font_path = Path(requested).expanduser().resolve()
    try:
        ImageFont.truetype(str(font_path), 20)
    except (OSError, ValueError) as error:
        raise ValueError("font_path must be a readable TrueType/OpenType font") from error
    normalized["font_path"] = str(font_path)
    if version == 2:
        language = parameters.get('language', 'ja')
        if language not in ('ja', 'en'):
            raise ValueError('language must be ja or en')
        limit = parameters.get('max_width_fraction', .8)
        if isinstance(limit, bool) or not isinstance(limit, (float, int)) or not math.isfinite(limit) or not .2 <= limit <= .9:
            raise ValueError('max_width_fraction must be from .2 to .9')
        count = parameters.get('max_lines', 3)
        if type(count) is not int or not 1 <= count <= 3:
            raise ValueError('max_lines must be from 1 to 3')
        phrases = parameters.get('protected_phrases', [])
        if not isinstance(phrases, list) or any(not isinstance(p, str) or not p.strip() or '\n' in p or p not in value for p in phrases):
            raise ValueError('protected_phrases must be nonempty phrases present in the text without newlines')
        normalized.update(language=language, max_width_fraction=float(limit),
                          max_lines=count, protected_phrases=phrases.copy())
    return normalized


def render_text_asset(parameters: dict, width: int, height: int, output_png: str | Path, *, version: int = 1) -> dict:
    """Save a new full-frame RGBA PNG and return its measured card bounds."""
    settings = validate_text_parameters(parameters, version=version)
    if (isinstance(width, bool) or isinstance(height, bool) or
            not isinstance(width, int) or not isinstance(height, int) or
            width <= 0 or height <= 0):
        raise ValueError("width and height must be positive integers")
    target = Path(output_png)
    if target.exists():
        raise FileExistsError(target)
    font_path = Path(settings["font_path"])
    font_size = max(1, round(min(width, height) * settings["font_size_fraction"]))
    font = ImageFont.truetype(str(font_path), font_size)
    lines = settings["text"].split("\n")
    measure = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    padding_x = max(8, round(font_size * .45))
    binding = None
    if version == 2:
        from .text_layout import wrap_text
        binding = layout_binding()
        def ink_width(text):
            box = measure.textbbox((0, 0), text, font=font)
            return box[2] - box[0]
        lines = wrap_text(settings['text'], settings['language'],
                          width * settings['max_width_fraction'] - 2 * padding_x,
                          ink_width, max_lines=settings['max_lines'],
                          protected_phrases=settings['protected_phrases'])
    boxes = [measure.textbbox((0, 0), line or " ", font=font) for line in lines]
    line_height = max(font.getmetrics()[0] + font.getmetrics()[1],
                      max(box[3] - box[1] for box in boxes))
    line_gap = round(font_size * .18)
    padding_x = max(8, round(font_size * .45))
    padding_y = max(6, round(font_size * .30))
    card_width = math.ceil(max(box[2] - box[0] for box in boxes) + 2 * padding_x)
    card_height = math.ceil(len(lines) * line_height + (len(lines) - 1) * line_gap + 2 * padding_y)
    if card_width > width * .9 or card_height > height * .9:
        raise ValueError("Measured text card exceeds 90% of the frame; revise the cue")
    left = max(0, min(width - card_width, round(width * settings["x"] - card_width / 2)))
    top = max(0, min(height - card_height, round(height * settings["y"] - card_height / 2)))
    image = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    background = tuple(bytes.fromhex(settings["background"][1:])) + (255,)
    draw.rounded_rectangle((left, top, left + card_width - 1, top + card_height - 1),
                           radius=min(round(font_size * .3), card_height // 2), fill=background)
    for index, (line, box) in enumerate(zip(lines, boxes)):
        line_width = box[2] - box[0]
        text_x = left + round((card_width - line_width) / 2) - box[0]
        text_y = top + padding_y + index * (line_height + line_gap) - box[1]
        draw.text((text_x, text_y), line, font=font, fill=settings["foreground"])
    stream = io.BytesIO()
    image.save(stream, format="PNG")
    png = stream.getvalue()
    with target.open("xb") as file:
        file.write(png)
    result = {
        "bounds": [left / width, top / height,
                   (left + card_width) / width, (top + card_height) / height],
        "font_path": str(font_path),
        "font_sha256": hashlib.sha256(font_path.read_bytes()).hexdigest(),
        "png_sha256": hashlib.sha256(png).hexdigest(),
    }
    if version == 2:
        result.update(rendered_lines=lines, layout_binding=binding,
                      original_text=settings['text'])
    return result
