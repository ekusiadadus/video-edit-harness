"""Read FCPXML conservatively and create a new, single-source cut timeline."""

from __future__ import annotations

from fractions import Fraction
from pathlib import Path
from urllib.parse import unquote, urlparse
import math
import xml.etree.ElementTree as ET


def _seconds(value: object) -> Fraction:
    if value is None:
        raise ValueError("missing duration")
    try:
        result = Fraction(str(value))
    except (ValueError, ZeroDivisionError) as exc:
        raise ValueError(f"invalid time: {value!r}") from exc
    if result < 0:
        raise ValueError("negative time")
    return result


def _time(value: Fraction) -> str:
    return f"{value.numerator}/{value.denominator}s" if value.denominator != 1 else f"{value.numerator}s"


def _ceil(value: Fraction) -> int:
    return -(-value.numerator // value.denominator)


def _uri_path(uri: str) -> Path | None:
    parsed = urlparse(uri)
    if parsed.scheme != "file" or parsed.netloc not in ("", "localhost"):
        return None
    return Path(unquote(parsed.path))


def inspect_xml(path: Path) -> dict:
    """Report visible structure and media links without editing the source XML."""
    root = ET.parse(path).getroot()
    if root.tag != "fcpxml":
        raise ValueError("not an FCPXML document")
    assets = {a.get("id"): a for a in root.findall("./resources/asset")}
    media_links = []
    for asset in assets.values():
        for rep in asset.findall("media-rep"):
            uri = rep.get("src", "")
            local = _uri_path(uri)
            media_links.append({"asset": asset.get("id"), "name": asset.get("name"),
                                "uri": uri, "path": str(local) if local else None,
                                "exists": local.exists() if local else None})
    projects = []
    clips = []
    titles = []
    audio_clips = []
    captions = []
    speed_effects = []
    warnings = []
    complex_tags = {"multicam", "mc-clip", "sync-clip", "ref-clip", "audition",
                    "transition", "gap", "timeMap", "conform-rate", "filter-video",
                    "filter-audio", "filter-audio-mixer", "filter-color", "filter"}
    for node in root.iter():
        if node.tag in complex_tags:
            warnings.append(f"unsupported or complex structure: {node.tag}")
        if node.tag == "project":
            seq = node.find("sequence")
            projects.append({"name": node.get("name"), "duration": seq.get("duration") if seq is not None else None})
        elif node.tag in ("asset-clip", "clip", "video", "audio"):
            item = {"type": node.tag, "name": node.get("name"), "ref": node.get("ref"),
                    "offset": node.get("offset"), "start": node.get("start"),
                    "duration": node.get("duration"), "audioRole": node.get("audioRole"),
                    "role": node.get("role"), "lane": node.get("lane")}
            asset = assets.get(node.get("ref"))
            audio_only_asset = (asset is not None and asset.get("hasAudio") == "1"
                                and asset.get("hasVideo") in (None, "0"))
            if node.tag == "audio" or node.get("srcEnable") == "audio" or audio_only_asset:
                audio_clips.append(item)
            else:
                clips.append(item)
            if node.find("timeMap") is not None or node.find("conform-rate") is not None:
                speed_effects.append(item)
        elif node.tag == "title":
            titles.append({"name": node.get("name"), "offset": node.get("offset"),
                           "duration": node.get("duration"),
                           "text": "".join(node.itertext()).strip()})
        elif node.tag == "caption":
            captions.append({"name": node.get("name"), "offset": node.get("offset"),
                             "duration": node.get("duration"), "role": node.get("role"),
                             "text": "".join(node.itertext()).strip()})
    if root.findall("./resources/media"):
        warnings.append("media resource may contain nested sequences")
    return {"version": root.get("version"), "projects": projects, "clips": clips,
            "titles": titles, "captions": captions, "audio_clips": audio_clips,
            "speed_effects": speed_effects,
            "media_links": media_links, "warnings": sorted(set(warnings))}


def export_full_timeline(source, probe, frame_count, fps, output, name):
    """Export a verified generated picture's full frame range, including its tail.

    The generic exporter accepts the reported media end and recovers exact
    nominal-frame duration. Keep source-edit range validation unchanged.
    """
    if type(frame_count) is not int or frame_count <= 0:
        raise ValueError('Full timeline needs a positive frame count')
    video = next((row for row in probe.get('streams', []) if row.get('codec_type') == 'video'), None)
    if video is None:
        raise ValueError('Full timeline needs a video stream')
    try:
        rate = Fraction(str(fps))
        observed_rate = Fraction(video['r_frame_rate'])
        observed_count = int(video['nb_frames'])
        reported_end = _seconds(video.get('duration') or probe.get('format', {}).get('duration'))
    except (KeyError, TypeError, ValueError, ZeroDivisionError) as exc:
        raise ValueError('Full timeline needs observed frame count, FPS and duration') from exc
    if rate <= 0 or observed_rate != rate or observed_count != frame_count:
        raise ValueError('Full timeline differs from its frame mapping')
    expected_end = Fraction(frame_count, 1) / rate
    if abs(reported_end - expected_end) > 1 / rate:
        raise ValueError('Full timeline duration differs from its frame mapping')
    return export_timeline(source, probe, [(0, reported_end)], output, name)


def export_timeline(source: Path, probe: dict, keep: list[tuple[float, float]],
                    output: Path, name: str, *, ordered: bool = False) -> dict:
    """Export frame-aligned source ranges as one contiguous FCPXML 1.10 project.

    The source's natural audio travels with each asset-clip. No transforms, gain,
    effects, titles, or music are synthesized. The project working space is
    Rec.709; the separate source format does not relabel camera/log media.
    """
    source = Path(source)
    output = Path(output)
    if not source.is_file():
        raise FileNotFoundError(source)
    if output.exists():
        raise FileExistsError(output)
    if not name.strip():
        raise ValueError("project name is empty")
    if not keep:
        raise ValueError("no keep intervals")
    streams = probe.get("streams", [])
    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    audio = next((s for s in streams if s.get("codec_type") == "audio"), None)
    if video is None:
        raise ValueError("probe has no video stream")
    try:
        avg = Fraction(video["avg_frame_rate"])
        nominal = Fraction(video["r_frame_rate"])
    except (KeyError, ValueError, ZeroDivisionError) as exc:
        raise ValueError("invalid frame rate") from exc
    if avg <= 0 or nominal <= 0:
        raise ValueError("invalid frame rate")
    if abs(avg - nominal) / nominal > Fraction(1, 100):
        raise ValueError("materially variable frame rate is unsupported")
    frame = 1 / nominal
    for start_time in (video.get("start_time"), probe.get("format", {}).get("start_time")):
        if start_time is not None and Fraction(str(start_time)) != 0:
            raise ValueError("nonzero source start_time is unsupported")
    duration_value = video.get("duration") or probe.get("format", {}).get("duration")
    reported_duration = _seconds(duration_value)
    if reported_duration == 0:
        raise ValueError("zero duration")
    duration = reported_duration
    frame_count = video.get("nb_frames")
    if frame_count not in (None, "N/A"):
        try:
            frame_count = int(frame_count)
        except (TypeError, ValueError) as exc:
            raise ValueError("invalid video frame count") from exc
        if frame_count <= 0:
            raise ValueError("invalid video frame count")
        counted_duration = frame_count * frame
        if abs(counted_duration - reported_duration) <= frame:
            duration = counted_duration
        else:
            frame_count = None
    else:
        frame_count = None
    ranges = []
    previous_end = Fraction(0)
    for start_raw, end_raw in keep:
        start, end = _seconds(start_raw), _seconds(end_raw)
        if start >= end or (not ordered and start < previous_end) or end > reported_duration:
            raise ValueError("invalid, overlapping, unordered, or out-of-range keep interval")
        # Container duration can round the last video frame slightly short or long.
        # Only an interval ending at the reported source end gets this adjustment.
        effective_end = duration if frame_count is not None and end == reported_duration else end
        first, last = _ceil(start / frame), math.floor(effective_end / frame)
        if last <= first:
            raise ValueError("keep interval contains no complete source frames")
        ranges.append((first * frame, (last - first) * frame))
        previous_end = end
    try:
        width, height = int(video["width"]), int(video["height"])
    except (KeyError, ValueError, TypeError) as exc:
        raise ValueError("invalid video dimensions") from exc
    if width <= 0 or height <= 0:
        raise ValueError("invalid video dimensions")
    rotation = next((sd.get("rotation") for sd in video.get("side_data_list", [])
                     if "rotation" in sd), video.get("tags", {}).get("rotate", 0))
    try:
        rotation = int(float(rotation))
    except (TypeError, ValueError) as exc:
        raise ValueError("invalid rotation") from exc
    if rotation % 90:
        raise ValueError("unsupported non-right-angle rotation")
    if rotation % 180:
        width, height = height, width

    root = ET.Element("fcpxml", version="1.10")
    resources = ET.SubElement(root, "resources")
    ET.SubElement(resources, "format", id="fmt", frameDuration=_time(frame),
                  width=str(width), height=str(height), colorSpace="1-1-1 (Rec. 709)")
    ET.SubElement(resources, "format", id="source_fmt", frameDuration=_time(frame),
                  width=str(width), height=str(height))
    asset_attrs = {"id": "asset1", "name": source.stem, "start": "0s",
                   "duration": _time(duration), "hasVideo": "1", "format": "source_fmt"}
    if audio:
        channels = audio.get("channels")
        sample_rate = audio.get("sample_rate")
        if not channels or not sample_rate:
            raise ValueError("audio stream lacks channel count or sample rate")
        asset_attrs.update(hasAudio="1", audioSources="1", audioChannels=str(channels),
                           audioRate=str(sample_rate))
    asset = ET.SubElement(resources, "asset", asset_attrs)
    ET.SubElement(asset, "media-rep", kind="original-media", src=source.resolve().as_uri())
    library = ET.SubElement(root, "library")
    event = ET.SubElement(library, "event", name=name)
    project = ET.SubElement(event, "project", name=name)
    total = sum((length for _, length in ranges), Fraction(0))
    sequence_attrs = {"format": "fmt", "duration": _time(total), "tcStart": "0s", "tcFormat": "NDF"}
    if audio:
        # Project output is stereo for mono/stereo source components. FCP 12.4
        # warns on a top-level mono layout and exports it back as stereo.
        # Preserve the original mono asset/channel configuration above.
        sequence_attrs["audioLayout"] = "stereo" if int(audio["channels"]) <= 2 else "surround"
        sequence_attrs["audioRate"] = "48k" if int(audio["sample_rate"]) == 48000 else "44.1k" if int(audio["sample_rate"]) == 44100 else "96k" if int(audio["sample_rate"]) == 96000 else ""
        if not sequence_attrs["audioRate"]:
            raise ValueError("unsupported sequence audio sample rate")
    spine = ET.SubElement(ET.SubElement(project, "sequence", sequence_attrs), "spine")
    offset = Fraction(0)
    for start, length in ranges:
        ET.SubElement(spine, "asset-clip", ref="asset1", name=source.stem,
                      offset=_time(offset), start=_time(start), duration=_time(length))
        offset += length
    output.parent.mkdir(parents=True, exist_ok=True)
    xml = ET.tostring(root, encoding="utf-8", xml_declaration=True)
    xml = xml.replace(b"?>\n", b"?>\n<!DOCTYPE fcpxml>\n", 1)
    # Exclusive creation protects an existing edit even if another process creates it now.
    with output.open("xb") as handle:
        handle.write(xml)
    return {"output": str(output), "project": name, "duration": _time(total),
            "frame_duration": _time(frame), "ranges": len(ranges),
            "has_audio": bool(audio), "width": width, "height": height}
