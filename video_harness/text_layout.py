"""Wrap title text at measured ink widths without changing its typography."""

from __future__ import annotations

import math
import re
from collections.abc import Callable, Iterable


_OPENING = frozenset("（([{「『【〔〈《〝‘“")
_CLOSING = frozenset("、。，．！？!?,.:;：；％%）)]}」』】〕〉》〟’”…")
_NUMBER_UNIT = re.compile(
    r"[0-9０-９]+(?:[,.，．][0-9０-９]+)* ?(?:"
    r"億円|万円|時間|メートル|キロ|センチ|ミリ|"
    r"円|人|個|本|枚|件|回|年|月|日|時|分|秒|歳|才|倍|割|％|%|℃|°|"
    r"fps|kHz|Hz|LUFS|dBTP|dB|px|km|cm|mm|kg|mg|GB|MB|TB|m|g|L|l"
    r")(?![A-Za-z])",
    re.IGNORECASE,
)
_LATIN_WORD = re.compile(r"[A-Za-z][A-Za-z0-9_]*")


def _grapheme_boundaries(text: str) -> set[int]:
    try:
        import regex
    except ImportError as error:
        raise ImportError(
            "Text layout requires the text-layout extra; "
            "install with `uv sync --extra text-layout`."
        ) from error
    return {0, *(match.end() for match in regex.finditer(r"\X", text))}


def _japanese_boundaries(text: str, graphemes: set[int]) -> set[int]:
    try:
        import budoux
    except ImportError as error:
        raise ImportError(
            "Japanese text layout requires the text-layout extra; "
            "install with `uv sync --extra text-layout`."
        ) from error

    parser = budoux.load_default_japanese_parser()
    position = 0
    preferred: set[int] = set()
    for chunk in parser.parse(text):
        position += len(chunk)
        if position in graphemes:
            preferred.add(position)
    return preferred


def _forbidden_boundaries(text: str, phrases: Iterable[str]) -> set[int]:
    forbidden: set[int] = set()
    for phrase in phrases:
        if not isinstance(phrase, str) or not phrase:
            raise ValueError("protected_phrases must contain nonempty strings")
        start = 0
        while (index := text.find(phrase, start)) != -1:
            forbidden.update(range(index + 1, index + len(phrase)))
            start = index + 1
    for match in _NUMBER_UNIT.finditer(text):
        forbidden.update(range(match.start() + 1, match.end()))
    for match in _LATIN_WORD.finditer(text):
        forbidden.update(range(match.start() + 1, match.end()))
    return forbidden


def _width(measure: Callable[[str], float], value: str) -> float:
    width = measure(value)
    if isinstance(width, bool) or not isinstance(width, (int, float)) or not math.isfinite(width) or width < 0:
        raise ValueError("measure must return a finite, nonnegative ink width")
    return width


def _segment_options(
    segment: str,
    language: str,
    max_width: float,
    measure: Callable[[str], float],
    phrases: tuple[str, ...],
) -> tuple[dict[int, list[tuple[int, str, bool]]], dict[int, int]]:
    """Find legal breaks and the fewest lines needed from each grapheme start."""
    all_graphemes = _grapheme_boundaries(segment)
    if language == "ja":
        preferred = _japanese_boundaries(segment, all_graphemes)
        boundaries = all_graphemes
    else:
        preferred = {match.start() for match in re.finditer(r" +", segment)}
        boundaries = preferred & all_graphemes
    forbidden = _forbidden_boundaries(segment, phrases)
    options: dict[int, list[tuple[int, str, bool]]] = {}
    needed: dict[int, int] = {}
    impossible = len(segment) + 2
    if not segment:
        return {0: [(0, "", True)]}, {0: 1}

    for start in sorted(all_graphemes, reverse=True):
        if start == len(segment):
            continue
        remainder = segment[start:]
        if _width(measure, remainder) <= max_width:
            options[start] = [(len(segment), remainder, True)]
            needed[start] = 1
            continue
        candidates: list[tuple[int, str, bool]] = []
        for boundary in boundaries:
            if not start < boundary < len(segment) or boundary in forbidden:
                continue
            end = boundary
            while end > start and segment[end - 1] == " ":
                end -= 1
            next_start = boundary
            while next_start < len(segment) and segment[next_start] == " ":
                next_start += 1
            if (end == start or next_start == len(segment) or
                    end not in all_graphemes or next_start not in all_graphemes):
                continue
            value = segment[start:end]
            if language == "ja" and (value[-1] in _OPENING or segment[next_start] in _CLOSING):
                continue
            if _width(measure, value) <= max_width:
                candidates.append((next_start, value, boundary in preferred))
        options[start] = candidates
        needed[start] = min((1 + needed.get(next_start, impossible)
                             for next_start, _, _ in candidates), default=impossible)
    return options, needed


def wrap_text(
    text: str,
    language: str,
    max_width: float,
    measure: Callable[[str], float],
    max_lines: int = 3,
    protected_phrases: Iterable[str] = (),
) -> list[str]:
    """Return measured lines, preserving source text except spaces at inserted breaks.

    ``measure`` must measure the rendered ink width of the complete candidate line.
    Japanese wrapping prefers BudouX boundaries and uses grapheme boundaries when
    no phrase boundary fits. Protected phrases and number-unit tokens stay intact.
    """
    if not isinstance(text, str):
        raise ValueError("text must be a string")
    if language not in {"en", "ja"}:
        raise ValueError("language must be 'en' or 'ja'")
    if isinstance(max_width, bool) or not isinstance(max_width, (int, float)) or not math.isfinite(max_width) or max_width <= 0:
        raise ValueError("max_width must be a finite positive number")
    if isinstance(max_lines, bool) or not isinstance(max_lines, int) or max_lines < 1:
        raise ValueError("max_lines must be a positive integer")
    if not callable(measure):
        raise ValueError("measure must be callable")
    phrases = tuple(protected_phrases)
    segments = text.replace("\r\n", "\n").split("\n")
    layouts = [_segment_options(segment, language, max_width, measure, phrases)
               for segment in segments]
    if any(needed[0] >= len(segment) + 2
           for segment, (_, needed) in zip(segments, layouts)):
        raise ValueError(
            f"Unbreakable text exceeds max_width={max_width}; increase the width "
            "or revise the text/protected phrases."
        )
    if sum(needed[0] for _, needed in layouts) > max_lines:
        raise ValueError(
            f"Text exceeds max_lines={max_lines}; increase the line limit "
            "or revise the text/width."
        )

    lines: list[str] = []
    for index, segment in enumerate(segments):
        options, needed = layouts[index]
        future_min = sum(future_needed[0] for _, future_needed in layouts[index + 1:])
        start = 0
        while True:
            available = max_lines - len(lines) - future_min
            feasible = [(next_start, value, preferred)
                        for next_start, value, preferred in options[start]
                        if 1 + (0 if next_start == len(segment)
                                else needed[next_start]) <= available]
            next_start, value, _ = max(
                feasible, key=lambda item: (item[2], item[0]))
            lines.append(value)
            if next_start == len(segment):
                break
            start = next_start
    return lines
