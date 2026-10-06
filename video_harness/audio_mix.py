"""Local PCM cue mixer. Loudness normalization belongs to the final render stage."""

from __future__ import annotations

from pathlib import Path
import math
import subprocess
import wave

import numpy as np

from .cues import _asset_map, validate_cues, _seconds
from .audio_envelopes import file_identity, write_audio_envelopes


RATE = 48000
CHANNELS = 2


def _decode(path, start=0, duration=None):
    command = ["ffmpeg", "-v", "error", "-nostdin", "-i", str(path), "-vn"]
    if start:
        command += ["-ss", str(start)]
    if duration is not None:
        command += ["-t", str(duration)]
    command += ["-af", "aresample=48000:async=1:first_pts=0", "-ar", str(RATE),
                "-ac", str(CHANNELS), "-f", "f32le", "pipe:1"]
    result = subprocess.run(command, capture_output=True)
    if result.returncode:
        raise ValueError(f"unable to decode audio: {path}: {result.stderr.decode(errors='replace')[-500:]}")
    data = np.frombuffer(result.stdout, dtype="<f4")
    if len(data) % CHANNELS:
        raise ValueError("decoded PCM has incomplete channel frame")
    return data.reshape(-1, CHANNELS).copy()


def _rms(data):
    return float(np.sqrt(np.mean(np.square(data.astype(np.float64))))) if data.size else 0.0


def _speech_duck(speech, settings):
    """Slow activity envelope with hold and release to avoid breath pumping."""
    count = len(speech)
    window = int(.10 * RATE)
    rms = np.array([_rms(speech[i:i + window]) for i in range(0, count, window)])
    # Relative threshold with a floor; silence and low-level room tone do not
    # cause the background to jump on every breath.
    threshold = max(float(settings.get("speech_activity_floor", .003)),
                    float(np.percentile(rms, 80)) * .18 if len(rms) else 0)
    onset = rms > threshold
    active = onset.copy()
    hold = max(1, round(float(settings.get("duck_hold_seconds", .5)) / .1))
    for index in np.flatnonzero(onset):
        if onset[index]:
            active[index:min(len(active), index + hold)] = True
    attack = float(settings.get("duck_attack_seconds", .25))
    release = float(settings.get("duck_release_seconds", .7))
    depth = float(settings.get("duck_db", -9.0))
    if depth > 0 or depth < -30:
        raise ValueError("duck_db must be between -30 and 0")
    gain = np.empty(len(active), dtype=np.float32)
    value = 1.0
    low = 10 ** (depth / 20)
    for i, is_active in enumerate(active):
        target = low if is_active else 1.0
        tau = attack if is_active else release
        alpha = min(1.0, .1 / max(tau, .001))
        value += (target - value) * alpha
        gain[i] = value
    return np.repeat(gain, window)[:count], {"activity_threshold_rms": threshold,
                                                "active_windows": int(np.sum(active)),
                                                "window_seconds": .1}


def render_mix(speech_wav, cues, assets, output_wav, duration, audio_settings=None, *, gain_output=None):
    """Render 48 kHz stereo PCM of exact requested sample count.

    Asset gain is anchored to measured speech RMS when available. The result is
    deliberately not loudness-normalized; parent render measures/normalizes it.
    """
    settings = dict(audio_settings or {})
    for key in ("speech_activity_floor", "duck_hold_seconds", "duck_attack_seconds",
                "duck_release_seconds", "duck_db", "music_below_speech_db"):
        if key in settings and (isinstance(settings[key], bool) or
                                not math.isfinite(float(settings[key]))):
            raise ValueError(f"{key} must be finite")
    assets = _asset_map(assets)
    cues = validate_cues(cues, assets, duration)
    if any(c["role"] not in {"music", "sfx"} for c in cues):
        raise ValueError("render_mix accepts audio cues only")
    samples = round(float(duration) * RATE)
    if samples <= 0:
        raise ValueError("duration is empty")
    speech = np.zeros((samples, CHANNELS), dtype=np.float32)
    speech_identity = None
    if speech_wav is not None:
        speech_path = Path(speech_wav)
        if not speech_path.is_file():
            raise FileNotFoundError(speech_path)
        if gain_output is not None:
            speech_identity = file_identity(speech_path)
        decoded = _decode(speech_path, duration=duration)
        if gain_output is not None and file_identity(speech_path) != speech_identity:
            raise ValueError("speech source changed during decode")
        if abs(len(decoded) - samples) > 1:
            raise ValueError("speech PCM length differs from output duration")
        speech[:min(samples, len(decoded))] = decoded[:samples]
    output = speech.copy()
    speech_rms = _rms(speech)
    duck_envelope, duck_evidence = _speech_duck(speech, settings) if speech_rms else (None, None)
    evidence_cues = []
    gain_curves = {}
    asset_identities = {}
    for cue in cues:
        asset = assets[cue["asset_id"]]
        path = Path(asset.get("path") or asset.get("local_path"))
        retime_source_identity = file_identity(path) if 'audio_retime' in cue else None
        if retime_source_identity and retime_source_identity['sha256'] != cue['audio_retime']['source_sha256']:
            raise ValueError('SFX source changed since retime validation')
        if gain_output is not None:
            asset_identities[cue["asset_id"]] = file_identity(path)
            if asset_identities[cue["asset_id"]]["sha256"] != (asset.get("sha256") or asset.get("file_sha256")):
                raise ValueError(f"cue asset changed since validation: {cue['id']}")
        first = round(_seconds(cue["output_start"], 'output_start') * RATE)
        last = round(_seconds(cue["output_end"], 'output_end') * RATE)
        target = last - first
        source_len = float(_seconds(cue["source_end"], 'source_end') - _seconds(cue["source_start"], 'source_start'))
        chunk = _decode(path, float(_seconds(cue["source_start"], 'source_start')), source_len)
        if gain_output is not None and file_identity(path) != asset_identities[cue["asset_id"]]:
            raise ValueError(f"cue asset changed during decode: {cue['id']}")
        if retime_source_identity and file_identity(path) != retime_source_identity:
            raise ValueError('SFX source changed during content decode')
        if not len(chunk):
            raise ValueError(f"cue asset has no decoded audio: {cue['id']}")
        expected_chunk = round(source_len * RATE)
        if abs(len(chunk) - expected_chunk) > 1:
            raise ValueError(f"cue source range exceeds decoded asset: {cue['id']}")
        if len(chunk) < expected_chunk:
            chunk = np.pad(chunk, ((0, expected_chunk - len(chunk)), (0, 0)))
        elif len(chunk) > expected_chunk:
            chunk = chunk[:expected_chunk]
        retime_evidence = None
        if 'audio_retime' in cue:
            from .sfx_retime import render_retimed_sfx
            clip, retime_evidence = render_retimed_sfx(chunk, cue,
                log_dir=Path(output_wav).parent / (Path(output_wav).stem + f'.sfx-{len(evidence_cues)}-logs'))
            if len(clip) != target:
                raise ValueError('Retimed SFX PCM count differs from output cue')
            seam_gain = None
        elif cue["loop"]:
            # Keep the musical period exactly len(chunk) samples. A short
            # taper around each seam removes clicks without changing cue/beat
            # timing; the resulting dip still needs an audible phrase review.
            clip = np.tile(chunk, (math.ceil(target / len(chunk)), 1))[:target].copy()
            taper = min(round(.01 * RATE), len(chunk) // 4)
            seam_gain = np.ones(target, dtype=np.float32) if gain_output is not None else None
            if taper:
                for seam in range(len(chunk), target, len(chunk)):
                    left = min(taper, seam)
                    right = min(taper, target - seam)
                    left_taper = np.linspace(1, 0, left, dtype=np.float32)
                    right_taper = np.linspace(0, 1, right, dtype=np.float32)
                    clip[seam - left:seam] *= left_taper[:, None]
                    clip[seam:seam + right] *= right_taper[:, None]
                    if seam_gain is not None:
                        seam_gain[seam - left:seam] *= left_taper
                        seam_gain[seam:seam + right] *= right_taper
        else:
            if len(chunk) < target - 1:
                raise ValueError(f"cue is shorter than output range: {cue['id']}")
            clip = chunk[:target].copy()
            seam_gain = None
        cue_rms = _rms(clip)
        gain_db = float(_seconds(cue["gain_db"], 'gain_db'))
        if cue["role"] == "music" and speech_rms and cue_rms:
            separation = float(settings.get("music_below_speech_db", 18))
            if not 0 <= separation <= 36:
                raise ValueError("music_below_speech_db must be 0..36")
            relative = 20 * math.log10(speech_rms / cue_rms) - separation
            gain_db += min(0.0, relative)  # never automatically boost a quiet track
        gain = np.full(target, 10 ** (gain_db / 20), dtype=np.float32)
        fade_in = 0 if retime_evidence else min(target, round(_seconds(cue["fade_in"], 'fade_in') * RATE))
        fade_out = 0 if retime_evidence else min(target, round(_seconds(cue["fade_out"], 'fade_out') * RATE))
        if fade_in:
            gain[:fade_in] *= np.linspace(0, 1, fade_in, dtype=np.float32)
        if fade_out:
            gain[-fade_out:] *= np.linspace(1, 0, fade_out, dtype=np.float32)
        if cue["duck"] and duck_envelope is not None:
            gain *= duck_envelope[first:last]
        if gain_output is not None:
            curve = gain.copy() if seam_gain is None else seam_gain * gain
            if not np.all(np.isfinite(curve)) or np.any(curve < 0):
                raise ValueError(f"invalid effective gain: {cue['id']}")
            gain_curves[cue["id"]] = curve
        output[first:last] += clip * gain[:, None]
        evidence_cues.append({"id": cue["id"], "asset_id": cue["asset_id"],
                              "source_rms": cue_rms, "applied_gain_db": gain_db,
                              "duck": bool(cue["duck"] and duck_envelope is not None),
                              "loop": cue["loop"], "loop_period_samples": len(chunk) if cue["loop"] else None,
                              "loop_seam_taper_seconds": .01 if cue["loop"] else 0})
        if retime_evidence:
            evidence_cues[-1]['content_retime'] = retime_evidence
    peak_before = float(np.max(np.abs(output)))
    if not math.isfinite(peak_before):
        raise ValueError("mixed audio contains non-finite samples")
    guard = 1.0
    if peak_before > .98:
        guard = .98 / peak_before
        output *= guard
    path = Path(output_wav)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise FileExistsError(path)
    pcm = np.clip(output, -1, 1)
    with wave.open(str(path), "wb") as stream:
        stream.setnchannels(CHANNELS)
        stream.setsampwidth(2)
        stream.setframerate(RATE)
        stream.writeframes((pcm * 32767).astype("<i2").tobytes())
    if gain_output is not None:
        if speech_wav is not None and file_identity(speech_path) != speech_identity:
            raise ValueError("speech source changed during render")
        for asset_id, identity in asset_identities.items():
            asset_path = Path(assets[asset_id].get("path") or assets[asset_id].get("local_path"))
            if file_identity(asset_path) != identity:
                raise ValueError(f"cue asset changed during render: {asset_id}")
        write_audio_envelopes(gain_output, cues=cues, assets=asset_identities,
                              speech=speech_identity, settings=settings, samples=samples,
                              curves=gain_curves, evidence=evidence_cues,
                              peak_guard_gain=guard, mixed_wav=file_identity(path))
    return {"output": str(path), "sample_rate": RATE, "channels": CHANNELS,
            "samples": samples, "duration": samples / RATE, "speech_rms": speech_rms,
            "peak_before_guard": peak_before, "peak_guard_gain": guard,
            "duck": duck_evidence, "cues": evidence_cues,
            "normalization": "not_applied"}
