"""Render a measured, transparent title card for a reviewed text cue."""

from __future__ import annotations

import hashlib
import io
import math
from pathlib import Path
import re
import unicodedata

from PIL import Image, ImageDraw, ImageFont

from .doctor import FONT_PATHS


_FIELDS = frozenset({"text", "x", "y", "font_size_fraction", "foreground",
                     "background", "motion", "font_path"})
_COLOR = re.compile(r"#[0-9A-Fa-f]{6}\Z")


def validate_text_parameters(parameters: dict) -> dict:
    """Return normalized title-card settings, rejecting unsupported values."""
    if not isinstance(parameters, dict) or set(parameters) - _FIELDS:
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
    return normalized


def render_text_asset(parameters: dict, width: int, height: int, output_png: str | Path) -> dict:
    """Save a new full-frame RGBA PNG and return its measured card bounds."""
    settings = validate_text_parameters(parameters)
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
    return {
        "bounds": [left / width, top / height,
                   (left + card_width) / width, (top + card_height) / height],
        "font_path": str(font_path),
        "font_sha256": hashlib.sha256(font_path.read_bytes()).hexdigest(),
        "png_sha256": hashlib.sha256(png).hexdigest(),
    }
