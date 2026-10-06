"""Local beat maps and conservative frame-aligned cue anchors."""

from __future__ import annotations

from fractions import Fraction
from pathlib import Path
import math

import numpy as np

from .audio_mix import _decode, RATE
from .cues import _seconds
from .common import fingerprint


ANALYZER_VERSION = 'local-beats-v1-exact-loop-period'


def analyze_beats(path, manual_bpm=None, manual_beats=None, use_librosa=False,
                  start=0, duration=None):
    """Return observed/manual beats plus explicit ambiguity, never confidence odds."""
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(path)
    audio = _decode(path, start=start, duration=duration)
    length = len(audio) / RATE
    if length <= 0:
        raise ValueError("empty beat source")
    warnings = []
    source_start = float(_seconds(start, "start"))
    if source_start < 0:
        raise ValueError("start must be nonnegative")
    if manual_beats is not None:
        beats = sorted(float(_seconds(value, "beat")) for value in manual_beats)
        if any(value < source_start or value >= source_start + length for value in beats) or len(set(beats)) != len(beats):
            raise ValueError("manual beats must be unique within selected source")
        method = "manual_beats"
        bpm = 60 / float(np.median(np.diff(beats))) if len(beats) > 1 else None
    elif manual_bpm is not None:
        bpm = float(_seconds(manual_bpm, "manual_bpm"))
        if not 20 <= bpm <= 300:
            raise ValueError("manual BPM outside 20..300")
        beats = list(source_start + np.arange(0, length, 60 / bpm, dtype=float))
        method = "manual_bpm"
        warnings.append("Manual BPM supplies a uniform grid, not verified music onsets or downbeats.")
    elif use_librosa:
        try:
            import librosa
        except ImportError as exc:
            raise RuntimeError("librosa optional dependency is unavailable") from exc
        mono = audio.mean(axis=1)
        tempo, positions = librosa.beat.beat_track(y=mono, sr=RATE, trim=False, units="time")
        bpm = float(np.ravel(tempo)[0]) if np.size(tempo) else None
        beats = [source_start + float(value) for value in positions]
        method = "librosa_beat_track"
        warnings.append("Automatic beat positions do not establish phrase starts or musical meter.")
    else:
        # Energy transients are hints, not a beat tracker. A quiet or uneven
        # recording yields no asserted grid until a person supplies one.
        hop = round(.02 * RATE)
        mono = np.mean(np.abs(audio), axis=1)
        energy = np.array([float(np.mean(mono[i:i + hop])) for i in range(0, len(mono), hop)])
        variation = np.maximum(0, np.diff(energy, prepend=energy[0]))
        floor = max(.005, float(np.percentile(variation, 90)) * 2.5) if len(variation) else .005
        peaks = []
        for i in range(1, len(variation) - 1):
            if variation[i] >= floor and variation[i] > variation[i - 1] and variation[i] >= variation[i + 1]:
                if not peaks or (source_start + i * hop / RATE - peaks[-1]) >= .25:
                    peaks.append(source_start + i * hop / RATE)
        beats = peaks
        bpm = 60 / float(np.median(np.diff(beats))) if len(beats) > 2 else None
        method = "transient_hints"
        warnings.append("Transient hints are not a validated beat grid; manually review before synchronization.")
    if len(beats) < 2:
        warnings.append("No stable onset interval was established; beat sync should be disabled or manual.")
    elif bpm is not None:
        gaps = np.diff(beats)
        if len(gaps) > 1 and float(np.std(gaps) / np.mean(gaps)) > .12:
            warnings.append("Tempo varies or detection is unstable; use local/manual anchors.")
        warnings.append(f"Half/double tempo ambiguity: also inspect {bpm/2:.1f} and {bpm*2:.1f} BPM.")
    source_evidence = fingerprint(path)
    return {"method": method, "source": str(path), "source_sha256": source_evidence['sha256'],
            "source_bytes": source_evidence['bytes'], "analyzer_version": ANALYZER_VERSION,
            "source_start": source_start,
            "duration": length, "bpm": bpm, "beats": beats,
            "ambiguity": warnings, "review_required": method not in {"manual_beats", "manual_bpm"}}


def map_beats(beat_map, cues, fps, protected_intervals=()):
    """Map asset beat positions through trim/loop cues to nearest output frame.

    Protected speech intervals are reported, never moved or modified.
    """
    rate = _seconds(fps, "fps")
    if rate <= 0:
        raise ValueError("fps must be positive")
    protected = [(_seconds(a, "protected start"), _seconds(b, "protected end"))
                 for a, b in protected_intervals]
    if any(a < 0 or b <= a for a, b in protected):
        raise ValueError("invalid protected interval")
    mapped = []
    seam_zones = []
    for cue in cues:
        out_start = _seconds(cue["output_start"], "output_start")
        out_end = _seconds(cue["output_end"], "output_end")
        src_start = _seconds(cue.get("source_start", 0), "source_start")
        src_end = _seconds(cue["source_end"], "source_end")
        span = Fraction(round(float(src_end - src_start) * RATE), RATE)
        if span <= 0 or out_end <= out_start:
            raise ValueError("invalid beat cue range")
        if cue.get('loop', False):
            repeat = 1
            while out_start + repeat * span < out_end:
                seam = out_start + repeat * span
                seam_zones.append({'cue_id': cue['id'], 'output_time': float(seam),
                                   'taper_seconds': .01})
                repeat += 1
        for beat in beat_map["beats"]:
            position = _seconds(beat, "beat")
            if not src_start <= position < src_end:
                continue
            repeat = 0
            while True:
                output_time = out_start + (position - src_start) + repeat * span
                if output_time >= out_end:
                    break
                frame = round(output_time * rate)
                aligned = Fraction(frame, 1) / rate
                in_speech = any(a <= aligned < b for a, b in protected)
                near_seam = any(zone['cue_id'] == cue['id'] and
                                abs(float(output_time) - zone['output_time']) <= zone['taper_seconds']
                                for zone in seam_zones)
                mapped.append({"cue_id": cue["id"], "source_time": float(position),
                               "output_time": float(output_time), "frame": frame,
                               "frame_time": float(aligned),
                               "rounding_error": float(aligned - output_time),
                               "protected_speech": in_speech,
                               "loop_seam_nearby": near_seam,
                               "cut_eligible": not in_speech and not near_seam})
                if not cue.get("loop", False):
                    break
                repeat += 1
    mapped.sort(key=lambda item: (item["frame"], item["cue_id"], item["source_time"]))
    return {"fps": str(rate), "beats": mapped,
            "ambiguity": list(beat_map.get("ambiguity", [])),
            "source_sha256": beat_map.get('source_sha256'),
            "analyzer_version": beat_map.get('analyzer_version'),
            "loop_seams": seam_zones,
            "protected_intervals": [[float(a), float(b)] for a, b in protected]}


def snap_cut_times(cut_times, mapped_beats, max_shift, min_hold, protected_intervals=()):
    """Suggest cut positions without changing protected speech or close cuts."""
    candidates = [item["frame_time"] for item in mapped_beats["beats"] if item["cut_eligible"]]
    cuts = []
    previous = -float("inf")
    for raw in cut_times:
        point = float(raw)
        if any(float(a) <= point < float(b) for a, b in protected_intervals):
            chosen, reason = point, "protected speech"
        else:
            nearby = [v for v in candidates if abs(v - point) <= max_shift and v - previous >= min_hold]
            chosen = min(nearby, key=lambda value: (abs(value - point), value)) if nearby else point
            reason = "nearest reviewed beat" if nearby else "no safe nearby beat"
        if chosen - previous < min_hold:
            chosen, reason = point, "minimum hold"
        cuts.append({"original": point, "suggested": chosen, "reason": reason})
        previous = chosen
    return cuts
