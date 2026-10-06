"""Frame-grounded visual edit plans and local FFmpeg rendering."""

from __future__ import annotations

from copy import deepcopy
from fractions import Fraction
from pathlib import Path
import json
import math
import subprocess
import tempfile

from PIL import Image, ImageDraw, ImageFont

from .cues import _asset_map, _check_asset, _seconds, validate_cues


def _probe(path):
    raw = subprocess.check_output(["ffprobe", "-v", "error", "-show_streams",
                                   "-show_format", "-of", "json", str(path)])
    return json.loads(raw)


def _video_info(path):
    info = _probe(path)
    video = next((s for s in info["streams"] if s["codec_type"] == "video"), None)
    if video is None:
        raise ValueError(f"source has no video: {path}")
    rate = Fraction(video.get("r_frame_rate") or video.get("avg_frame_rate") or "0")
    average = Fraction(video.get("avg_frame_rate") or "0")
    if rate <= 0 or average <= 0 or abs(rate - average) / rate > Fraction(1, 100):
        raise ValueError("variable/unknown source frame rate is unsupported")
    if Fraction(str(video.get("start_time", 0))) != 0:
        raise ValueError("nonzero source video start_time is unsupported")
    duration = Fraction(str(video.get("duration") or info["format"]["duration"]))
    frame_count = video.get("nb_frames")
    return {"fps": rate, "duration": duration, "frame_count": int(frame_count) if frame_count not in (None, "N/A") else None,
            "width": int(video["width"]),
            "height": int(video["height"]),
            "rec709_tags": (video.get('color_primaries'),video.get('color_transfer'),video.get('color_space')) == ('bt709','bt709','bt709'),
            "has_audio": any(s["codec_type"] == "audio" for s in info["streams"])}


def _round_frame(value, fps, up=False):
    frames = value * fps
    return math.ceil(frames) if up else math.floor(frames)


def validate_visual_edl(edl, assets, verify_sources=True):
    """Validate an edit made from observed source frame ranges, not word IDs."""
    if not isinstance(edl, dict) or edl.get("version") != 4 or edl.get("edit_basis") != "visual":
        raise ValueError("visual EDL requires version 4 and edit_basis visual")
    if edl.get("status") not in {"proposed", "reviewed_selection"}:
        raise ValueError("visual EDL needs an explicit review state")
    if not isinstance(edl.get("sequence"), list) or not edl["sequence"]:
        raise ValueError("visual EDL needs a nonempty sequence")
    assets = _asset_map(assets)
    normalized = deepcopy(edl)
    seen = set()
    source_info = {}
    supplied_sources = edl.get('sources')
    if supplied_sources is not None and not isinstance(supplied_sources, dict):
        raise ValueError('visual EDL sources must be a mapping')
    for segment in normalized["sequence"]:
        if set(segment) - {"id", "asset_id", "source_start", "source_end", "reason",
                            "source_fps", "source_first_frame", "source_end_frame_exclusive"}:
            raise ValueError("unknown visual segment field")
        segment_id = segment.get("id")
        if not isinstance(segment_id, str) or not segment_id or segment_id in seen:
            raise ValueError("visual segment ids must be unique")
        seen.add(segment_id)
        asset_id = segment.get("asset_id")
        asset = _check_asset(asset_id, assets, verify_hash=verify_sources)
        saved_source = supplied_sources.get(asset_id) if supplied_sources is not None else None
        if supplied_sources is not None and saved_source is None:
            raise ValueError('visual EDL source binding missing')
        if saved_source is not None and (saved_source.get("sha256") != asset.get("sha256") or
                                         Path(saved_source.get("path", "")).resolve() != Path(asset["path"]).resolve()):
            raise ValueError("visual EDL source binding changed")
        if asset.get("kind") != "video":
            raise ValueError("visual sequence source must be video")
        if not isinstance(segment.get("reason"), str) or not segment["reason"].strip():
            raise ValueError("each visual selection needs a concrete reason")
        if asset_id not in source_info:
            source_info[asset_id] = _video_info(asset["path"])
        info = source_info[asset_id]
        if saved_source is not None and saved_source.get('fps') != str(info['fps']):
            raise ValueError('visual EDL source FPS changed')
        begin = _seconds(segment.get("source_start"), "source_start")
        end = _seconds(segment.get("source_end"), "source_end")
        if begin < 0 or end <= begin or end > info["duration"] + 1 / info["fps"]:
            raise ValueError("visual segment outside source")
        first = _round_frame(begin, info["fps"], up=True)
        last = _round_frame(end, info["fps"])
        if last <= first:
            raise ValueError("visual segment has no complete frames")
        if info["frame_count"] is not None and last > info["frame_count"]:
            raise ValueError("visual segment extends beyond final source frame")
        derived = {'source_fps': str(info['fps']), 'source_first_frame': first,
                   'source_end_frame_exclusive': last}
        for key, value in derived.items():
            if key in segment and segment[key] != value:
                raise ValueError(f'visual EDL {key} changed')
        segment["source_start"] = str(Fraction(first, 1) / info["fps"])
        segment["source_end"] = str(Fraction(last, 1) / info["fps"])
        segment["source_fps"] = str(info["fps"])
        segment["source_first_frame"] = first
        segment["source_end_frame_exclusive"] = last
    if supplied_sources is not None and set(supplied_sources) != set(source_info):
        raise ValueError('visual EDL source bindings do not match referenced assets')
    normalized["sources"] = {key: {"path": assets[key]["path"], "sha256": assets[key]["sha256"],
                                   "kind": "video", "fps": str(value["fps"])}
                             for key, value in source_info.items()}
    if normalized["status"] == "reviewed_selection":
        review = normalized.get("review")
        if not isinstance(review, dict) or review.get("actor") not in {"human", "codex", "claude_code", "automation"} or not review.get("reason"):
            raise ValueError("reviewed visual EDL needs actor and reason")
    return normalized


def revise_visual_edl(edl, sequence, *, actor, reason):
    if actor not in {"human", "codex", "claude_code", "automation"} or not reason:
        raise ValueError("visual revision needs real actor and reason")
    revised = deepcopy(edl)
    revised["sequence"] = deepcopy(sequence)
    revised["status"] = "proposed"
    revised.pop("review", None)
    revised["revision"] = {"actor": actor, "reason": reason}
    return revised


def approve_visual_edl(edl, *, actor, reason, review_basis):
    if actor not in {"human", "codex", "claude_code", "automation"} or not reason:
        raise ValueError("visual review needs real actor and reason")
    if review_basis not in {"source_inspection", "preview_visual", "preview_visual_audio"}:
        raise ValueError("visual review basis must be explicit")
    approved = deepcopy(edl)
    approved["status"] = "reviewed_selection"
    approved["review"] = {"actor": actor, "reason": reason, "basis": review_basis}
    return approved


def _ffmpeg(command):
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode:
        raise ValueError(f"FFmpeg failed: {result.stderr[-1200:]}")


def render_visual_edl(edl, assets, output, fps=None, width=None, height=None):
    """Render a multi-source visual sequence with source audio or true silence."""
    assets = _asset_map(assets)
    plan = validate_visual_edl(edl, assets)
    output = Path(output)
    if output.exists():
        raise FileExistsError(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    first_info = _video_info(assets[plan["sequence"][0]["asset_id"]]["path"])
    rate = _seconds(fps, "fps") if fps is not None else first_info["fps"]
    width = int(width or first_info["width"])
    height = int(height or first_info["height"])
    if rate <= 0 or width <= 0 or height <= 0 or width % 2 or height % 2:
        raise ValueError("output needs positive FPS and even dimensions")
    mapping, elapsed_frames = [], 0
    observed_sources={}
    from .video_effects import _probe as picture_probe,_stream,_verified_rate
    for segment in plan['sequence']:
        asset=assets[segment['asset_id']]
        if segment['asset_id'] not in observed_sources:
            picture=_stream(picture_probe(asset['path'],count=True),'video')
            count=int(picture['nb_read_frames'])
            _verified_rate(asset['path'],picture,count)
            observed_sources[segment['asset_id']]=count
        if segment['source_end_frame_exclusive']>observed_sources[segment['asset_id']]:
            raise ValueError('Visual source frame range exceeds decoded source')
    with tempfile.TemporaryDirectory(prefix="visual-edl-") as tmp:
        root = Path(tmp)
        chunks = []
        for i, segment in enumerate(plan["sequence"]):
            source = Path(assets[segment["asset_id"]]["path"])
            info = _video_info(source)
            begin = Fraction(segment["source_start"])
            stop = Fraction(segment["source_end"])
            output_frames = round((stop - begin) * rate)
            if output_frames <= 0:
                raise ValueError("segment vanishes at output FPS")
            chunk = root / f"{i:04d}.mkv"
            source_rate=Fraction(segment['source_fps'])
            video_filter = (f"trim=start_frame={segment['source_first_frame']}:end_frame={segment['source_end_frame_exclusive']},"
                            f"settb=expr={source_rate.denominator}/{source_rate.numerator},setpts=N,"
                            f"fps={rate},scale={width}:{height}:force_original_aspect_ratio=decrease,"
                            f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,setsar=1,"
                            f"trim=end_frame={output_frames},setpts=PTS-STARTPTS")
            command = ["ffmpeg", "-v", "error", "-nostdin", "-y", "-i", str(source)]
            if info["has_audio"]:
                command += ["-filter_complex", f"[0:v]{video_filter}[v];"
                            f"[0:a:0]atrim=start={float(begin)}:end={float(stop)},"
                            "asetpts=PTS-STARTPTS,aresample=48000:async=1:first_pts=0[a]",
                            "-map", "[v]", "-map", "[a]"]
            else:
                command += ["-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo",
                            "-filter_complex", f"[0:v]{video_filter}[v];"
                            f"[1:a]atrim=duration={float(Fraction(output_frames, 1)/rate)},asetpts=PTS-STARTPTS[a]",
                            "-map", "[v]", "-map", "[a]"]
            command += ["-frames:v", str(output_frames), "-c:v", "libx264", "-pix_fmt", "yuv420p",
                        "-preset", "veryfast", "-crf", "18", "-c:a", "pcm_s16le", str(chunk)]
            _ffmpeg(command)
            chunks.append(chunk)
            from .retime_mapping import conform_source_frames
            mapping.append({"id": segment["id"], "asset_id": segment["asset_id"],
                            "source_first_frame": segment["source_first_frame"],
                            "source_end_frame_exclusive": segment["source_end_frame_exclusive"],
                            "source_fps": segment["source_fps"],
                            "output_first_frame": elapsed_frames,
                            "output_end_frame_exclusive": elapsed_frames + output_frames,
                            "output_fps": str(rate),
                            "source_frame_map":conform_source_frames(segment['source_first_frame'],segment['source_end_frame_exclusive'],
                                                                      str(source_rate),output_frames,str(rate)),
                            "frame_sampling":"normalized_cfr_fps_near"})
            elapsed_frames += output_frames
        manifest = root / "parts.txt"
        manifest.write_text("".join(f"file '{part.as_posix()}'\n" for part in chunks))
        _ffmpeg(["ffmpeg", "-v", "error", "-nostdin", "-y", "-f", "concat", "-safe", "0",
                 "-i", str(manifest), "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
                 "-t", str(float(Fraction(elapsed_frames, 1) / rate)), str(output)])
    return {"video": str(output), "duration": float(Fraction(elapsed_frames, 1) / rate),
            "frame_count": elapsed_frames, "fps": str(rate), "frame_mapping": mapping,
            "audio": "source_or_silence"}


def _title_image(text, path, width, height):
    image = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    font_path = "/System/Library/Fonts/Supplemental/Arial.ttf"
    try:
        font = ImageFont.truetype(font_path, max(18, round(height * .055)))
    except OSError:
        font = ImageFont.load_default()
    draw = ImageDraw.Draw(image)
    box = draw.textbbox((0, 0), text, font=font, stroke_width=2)
    tw, th = box[2] - box[0], box[3] - box[1]
    if tw > width * .8 or th > height * .3:
        raise ValueError("title exceeds safe area; shorten text")
    x, y = (width - tw) // 2, round(height * .1)
    draw.text((x, y), text, font=font, fill="white", stroke_width=2, stroke_fill="black")
    image.save(path)


def render_overlays(input_video, cues, assets, output, duration, preview=False, *, preserve_audio_end=False):
    """Burn local picture/title overlays while keeping existing audio untouched."""
    if type(preserve_audio_end) is not bool:
        raise ValueError("preserve_audio_end must be boolean")
    timing_options = ["-movie_timescale", "48000"] if preserve_audio_end else []
    input_video = Path(input_video)
    output = Path(output)
    if not input_video.is_file() or output.exists():
        raise ValueError("input video missing or overlay output exists")
    info = _video_info(input_video)
    width, height = info["width"], info["height"]
    assets = _asset_map(assets)
    cues = validate_cues(cues, assets, duration, info["fps"])
    if any(c["role"] not in {"image", "video", "title"} for c in cues):
        raise ValueError("render_overlays accepts visual cues only")
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="visual-overlays-") as tmp:
        root = Path(tmp)
        current = input_video
        for index, cue in enumerate(cues):
            role = cue["role"]
            source = root / f"title-{index}.png" if role == "title" else Path(assets[cue["asset_id"]]["path"])
            if role == "title":
                _title_image(cue["text"], source, width, height)
            if role == "video":
                overlay_input = ["-i", str(source)]
                source_filter = (f"trim=start={cue['source_start']}:end={cue['source_end']},"
                                 f"setpts=PTS-STARTPTS+{cue['output_start']}/TB,")
            else:
                overlay_input = ["-loop", "1", "-i", str(source)]
                source_filter = ""
            # Keep picture inside an 80% x 65% central safe box. Lower third
            # captions and outer 10% edges remain free; position is explicit.
            if role == "title":
                scale = f"scale={width}:{height}"
            else:
                scale = f"scale={int(width*.7)}:{int(height*.5)}:force_original_aspect_ratio=decrease"
            position = cue.get("position", "center")
            if position not in {"center", "top"}:
                raise ValueError("overlay position must be center or top")
            y = "H*0.25" if position == "center" else "H*0.1"
            opacity = float(cue.get("opacity", 1))
            if not 0 <= opacity <= 1:
                raise ValueError("overlay opacity must be 0..1")
            filter_graph = (f"[1:v]{source_filter}{scale},format=rgba,"
                            f"colorchannelmixer=aa={opacity}[layer];"
                            f"[0:v][layer]overlay=x=(W-w)/2:y={y}:"
                            f"enable='between(t,{cue['output_start']},{cue['output_end']})':"
                            "eof_action=pass:shortest=0[v]")
            if info['rec709_tags']:
                filter_graph += ';[v]setparams=color_primaries=bt709:color_trc=bt709:colorspace=bt709[retained_rec709]'
            picture_label = '[retained_rec709]' if info['rec709_tags'] else '[v]'
            target = root / f"overlay-{index}.mp4"
            _ffmpeg(["ffmpeg", "-v", "error", "-nostdin", "-y", "-i", str(current),
                     *overlay_input, "-filter_complex", filter_graph, "-map", picture_label,
                     "-map", "0:a?", "-c:v", "libx264", "-preset", "ultrafast" if preview else "medium",
                     "-crf", "23" if preview else "18", "-pix_fmt", "yuv420p", "-c:a", "copy",
                     "-t", str(duration), *timing_options, str(target)])
            current = target
        if cues:
            _ffmpeg(["ffmpeg", "-v", "error", "-nostdin", "-y", "-i", str(current),
                     "-map", "0", "-c", "copy", *timing_options, str(output)])
        else:
            _ffmpeg(["ffmpeg", "-v", "error", "-nostdin", "-y", "-i", str(input_video),
                     "-map", "0", "-c", "copy", *timing_options, str(output)])
    return {"output": str(output), "cues": [cue["id"] for cue in cues],
            "duration": float(duration), "preview": bool(preview),
            "safe_area": "overlays fit central 70 percent width and above lower 25 percent",
            "subject_clearance": "unverified; inspect every overlay against moving subjects and captions"}
