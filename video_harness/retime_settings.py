"""Move explicit visual settings through an exact, discrete retime mapping."""

from __future__ import annotations

from copy import deepcopy
from fractions import Fraction

from .composition import resolve_guides
from .cues import validate_cues
from .production import resolve_production
from .render_cache import digest
from .retime_mapping import remap_visual_mapping
from .video_effects import resolve_effects


def _frame(value, fps, count, label):
    if isinstance(value, bool):
        raise ValueError(f"{label} must be an exact frame-aligned time")
    try:
        frame = Fraction(str(value).removesuffix("s")) * fps
    except (TypeError, ValueError, ZeroDivisionError) as exc:
        raise ValueError(f"{label} must be an exact frame-aligned time") from exc
    if frame.denominator != 1 or not 0 <= frame <= count:
        raise ValueError(f"{label} must be an in-bounds exact frame-aligned time")
    return frame.numerator


def _seconds(frame, fps):
    return str(Fraction(frame, 1) / fps)


def migrate_visual_settings(cfg, original_mapping, compiled_retime):
    """Return atomic candidate changes and frame-level migration evidence.

    ``original_mapping`` must be the observed render's mapping. The caller also
    checks the proposal's input digest against the pre-retime mapping, which is
    the same object on the supported first-retime path.
    """
    if not isinstance(cfg, dict):
        raise ValueError("Visual settings config must be an object")
    if not isinstance(original_mapping, dict) or original_mapping.get("retime") is not None:
        raise ValueError("Settings migration cannot compose a previously retimed mapping")
    old_sha = digest(original_mapping)
    new_mapping = remap_visual_mapping(original_mapping, compiled_retime)
    new_sha = digest(new_mapping)
    fps = Fraction(original_mapping["fps"])
    old_count = original_mapping["frame_count"]
    frame_map = compiled_retime["frame_map"]
    changes = {}
    evidence = {"old_mapping_sha256": old_sha, "new_mapping_sha256": new_sha,
                "items": [], "version": 1}

    def interval(row, setting):
        name = f"{setting}:{row.get('id', '<missing id>')}"
        first = _frame(row.get("output_start"), fps, old_count, name + ".output_start")
        end = _frame(row.get("output_end"), fps, old_count, name + ".output_end")
        if end <= first:
            raise ValueError(f"{name} has an empty or reversed old interval")
        selected = [j for j, base in enumerate(frame_map) if first <= base < end]
        if not selected:
            raise ValueError(f"{name} interval is omitted by retime")
        if selected[-1] - selected[0] + 1 != len(selected):
            raise ValueError(f"{name} inverse frame interval is discontinuous")
        moved = deepcopy(row)
        moved["output_start"] = _seconds(selected[0], fps)
        moved["output_end"] = _seconds(selected[-1] + 1, fps)
        evidence["items"].append({"setting": setting, "id": row.get("id"),
            "old_frames": [first, end], "new_frames": [selected[0], selected[-1] + 1],
            "reason": "Complete inverse frame-map membership of old half-open interval"})
        return moved

    def source_frames(row):
        first = _frame(row["output_start"], fps, old_count, "output_start")
        end = _frame(row["output_end"], fps, old_count, "output_end")
        return first, end, [base for base in frame_map if first <= base < end]

    def require_translation(row, label):
        first, end, selected = source_frames(row)
        if selected != list(range(first, end)):
            raise ValueError(f"{label} needs source-content retiming; interval migration alone changes synchronization")

    explicit = cfg.get("cue_plan")
    if explicit is not None:
        if (not isinstance(explicit, dict) or set(explicit) != {"version", "mapping_sha256", "cues"}
                or explicit["version"] != 1 or explicit["mapping_sha256"] != old_sha
                or not isinstance(explicit["cues"], list)):
            raise ValueError("Cue plan is malformed or stale against observed mapping")
        cues = []
        for cue in explicit["cues"]:
            if not isinstance(cue, dict):
                raise ValueError("Cue plan contains a malformed cue")
            moved = interval(cue, "cue_plan")
            role = cue.get("role")
            if role in {"video", "sfx"}:
                require_translation(cue, f"cue_plan:{cue.get('id')}")
            evidence["items"][-1]["content_policy"] = (
                "normal_playback_on_new_output_clock" if role == "music" else
                "source_content_unchanged_pure_translation" if role in {"video", "sfx"} else
                "static_content_new_output_clock_fades")
            if "beat_anchor" in cue:
                anchor = _frame(cue["beat_anchor"], fps, old_count,
                                f"cue_plan:{cue.get('id')}.beat_anchor")
                if role == "music":
                    first, end, selected = source_frames(cue)
                    if not first <= anchor < end:
                        raise ValueError(f"cue_plan:{cue.get('id')} music beat anchor is outside its cue")
                    target = _frame(moved["output_start"], fps, len(frame_map), "output_start") + anchor - first
                    if target >= _frame(moved["output_end"], fps, len(frame_map), "output_end"):
                        raise ValueError(f"cue_plan:{cue.get('id')} music beat anchor no longer fits the new cue")
                    evidence["items"][-1]["anchor_policy"] = "preserved_declared_music_offset_on_new_clock"
                else:
                    targets = [j for j, base in enumerate(frame_map) if base == anchor]
                    if len(targets) != 1:
                        raise ValueError(f"cue_plan:{cue.get('id')} beat anchor is omitted or ambiguous")
                    target = targets[0]
                    evidence["items"][-1]["anchor_policy"] = "unique_original_picture_frame"
                moved["beat_anchor"] = _seconds(target, fps)
            cues.append(moved)
        changes["cue_plan"] = {"version": 1, "mapping_sha256": new_sha, "cues": cues}
        validate_cues(cues, cfg.get("assets", []), new_mapping["duration"], fps)

    setting = cfg.get("video_effects")
    if setting is not None:
        if isinstance(setting, dict) and "preset" in setting:
            # A preset has no old digest. Resolve its concrete old events before
            # retiming so the original placements are the migration source.
            old_events = resolve_effects(setting, original_mapping, cfg.get("assets", []))["events"]
        else:
            if (not isinstance(setting, dict) or set(setting) != {"version", "mapping_sha256", "events"}
                    or setting.get("version") != 1 or setting.get("mapping_sha256") != old_sha
                    or not isinstance(setting.get("events"), list)):
                raise ValueError("Effects plan is malformed or stale against observed mapping")
            if any(isinstance(row, dict) and str(row.get("type", "")).startswith("tracked_")
                   for row in setting["events"]):
                raise ValueError("Tracked effects need new tracking after retime")
            old_events = resolve_effects(setting, original_mapping, cfg.get("assets", []))["events"]
        events = []
        for event in old_events:
            if not isinstance(event, dict):
                raise ValueError("Effects plan contains a malformed event")
            if str(event.get("type", "")).startswith("tracked_"):
                raise ValueError(f"video_effects:{event.get('id')} needs new tracking after retime")
            moved = interval(event, "video_effects")
            kind = event.get("type")
            if kind in {"zoom_pulse", "smooth_zoom", "saturation_pulse"}:
                first, end, selected = source_frames(event)
                prior_phase = event.get("phase_map")
                moved["phase_map"] = {
                    "version": 1,
                    "original_frame_count": prior_phase["original_frame_count"] if prior_phase else end - first,
                    "frames": [prior_phase["frames"][base - first] if prior_phase else base - first
                               for base in selected]}
                evidence["items"][-1]["content_policy"] = "original_frame_effect_phase"
            elif kind in {"comparison_wipe", "motion_trail", "keyword_title"}:
                require_translation(event, f"video_effects:{event.get('id')}")
                evidence["items"][-1]["content_policy"] = "unchanged_phase_pure_translation"
            else:
                evidence["items"][-1]["content_policy"] = "static_framewise_effect"
            events.append(moved)
        changes["video_effects"] = {"version": 1, "mapping_sha256": new_sha, "events": events}
        resolve_effects(changes["video_effects"], new_mapping, cfg.get("assets", []))

    guides = cfg.get("composition_guides")
    if guides is not None:
        if not isinstance(guides, list):
            raise ValueError("Composition guides must be an array")
        moved_guides = []
        for guide in guides:
            if not isinstance(guide, dict):
                raise ValueError("Composition guides contain a malformed guide")
            if "track_path" in guide or "track_sha256" in guide or "rect" not in guide:
                raise ValueError(f"composition_guides:{guide.get('id')} needs new tracking after retime")
            moved_guides.append(interval(guide, "composition_guides"))
        changes["composition_guides"] = moved_guides
        resolve_guides(moved_guides, new_mapping)

    prospective = deepcopy(cfg)
    prospective.update(deepcopy(changes))
    production = resolve_production(prospective, new_mapping)
    if isinstance(production, dict):
        if changes.get("cue_plan", {}).get("cues") and not production.get("cues"):
            raise ValueError("Cue migration conflicts with the selected editing pattern")
        if changes.get("video_effects", {}).get("events") and not production.get("effects", {}).get("events"):
            raise ValueError("Effect migration conflicts with the selected editing pattern")
    return {"changes": changes, "evidence": evidence}
