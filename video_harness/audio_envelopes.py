"""Sealed, path-free sample gain evidence for the pre-normalization cue mixer.

The curves are cue-local effective gains before the common peak guard. They do
not describe the later loudness normalization or prove FCP playback parity.
"""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
import re

import numpy as np

from .cues import _asset_map, _seconds


RATE = 48000
CHANNELS = 2
_ARRAY_NAME = re.compile(r"cue-[0-9]{4}\.npy\Z")
_HEX = re.compile(r"[0-9a-f]{64}\Z")
_TIMES = ("output_start", "output_end", "source_start", "source_end", "gain_db",
          "fade_in", "fade_out")
_SETTINGS = frozenset({"speech_activity_floor", "duck_hold_seconds", "duck_attack_seconds",
                       "duck_release_seconds", "duck_db", "music_below_speech_db"})


def _sha(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def file_identity(path):
    """Fingerprint bytes without retaining a local/private path."""
    path = Path(path)
    before = path.stat()
    sha = _sha(path)
    after = path.stat()
    if (before.st_size, before.st_mtime_ns, before.st_ino) != (after.st_size, after.st_mtime_ns, after.st_ino):
        raise ValueError("file changed during fingerprint")
    return {"sha256": sha, "bytes": after.st_size}


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                    separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()


def cue_identity(cue):
    """Only audio-affecting fields; rational strings preserve exact cue times."""
    result = {key: cue[key] for key in ("id", "asset_id", "role")}
    result["loop"] = cue.get("loop", False)
    result["duck"] = cue.get("duck", cue["role"] == "music")
    result.update({key: str(_seconds(cue.get(key, 0), key)) for key in _TIMES})
    if 'audio_retime' in cue:
        result['audio_retime_sha256'] = _digest(cue['audio_retime'])
    return result


def _valid_fp(value):
    return (isinstance(value, dict) and set(value) == {"sha256", "bytes"} and
            isinstance(value["sha256"], str) and bool(_HEX.fullmatch(value["sha256"])) and
            type(value["bytes"]) is int and value["bytes"] >= 0)


def _gain_settings(settings):
    if not isinstance(settings, dict):
        raise ValueError("invalid audio gain settings")
    selected = {}
    for key in _SETTINGS.intersection(settings):
        value = settings[key]
        if type(value) not in (int, float) or not math.isfinite(value):
            raise ValueError(f"invalid audio gain setting: {key}")
        selected[key] = float(value)
    return selected


def write_audio_envelopes(path, *, cues, assets, speech, settings, samples, curves,
                          evidence, peak_guard_gain, mixed_wav):
    """Write an immutable v1 artifact into a new directory."""
    folder = Path(path)
    if folder.exists():
        raise FileExistsError(folder)
    if type(samples) is not int or samples <= 0:
        raise ValueError("invalid sample count")
    if not math.isfinite(peak_guard_gain) or not 0 < peak_guard_gain <= 1:
        raise ValueError("invalid peak guard")
    if not _valid_fp(mixed_wav) or (speech is not None and not _valid_fp(speech)):
        raise ValueError("invalid source fingerprint")
    if set(curves) != {cue["id"] for cue in cues}:
        raise ValueError("gain curves do not match cues")
    if not all(_valid_fp(value) for value in assets.values()):
        raise ValueError("invalid asset fingerprint")
    folder.mkdir(parents=True)
    rows = []
    for index, cue in enumerate(cues):
        identity = cue_identity(cue)
        first = round(_seconds(cue["output_start"], "output_start") * RATE)
        end = round(_seconds(cue["output_end"], "output_end") * RATE)
        curve = curves[cue["id"]]
        if (type(curve) is not np.ndarray or curve.dtype != np.dtype("float32") or
                curve.ndim != 1 or len(curve) != end - first or not np.all(np.isfinite(curve)) or
                np.any(curve < 0)):
            raise ValueError("invalid gain curve")
        name = f"cue-{index:04d}.npy"
        array_path = folder / name
        np.save(array_path, curve, allow_pickle=False)
        rows.append({"cue": identity, "asset": assets[cue["asset_id"]],
                     "first_sample": first, "end_sample": end,
                     "source_period_samples": evidence[index]["loop_period_samples"],
                     "array": name, "array_sha256": _sha(array_path)})
    manifest = {"version": 1, "scope": "pre_normalization", "actor": "automation",
                "decision_reason": "Capture measured renderer gain before final normalization",
                "sample_rate": RATE, "channels": CHANNELS, "samples": samples,
                "duration": str(samples / RATE), "settings": _gain_settings(settings),
                "speech": speech, "global_peak_guard_gain": peak_guard_gain,
                "mixed_wav": mixed_wav, "cues": rows}
    manifest["manifest_sha256"] = _digest(manifest)
    (folder / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False,
                                                  sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    return manifest


def load_audio_envelopes(path, *, expected_cues=None, expected_assets=None,
                         expected_speech=None, expected_mixed_wav=None):
    """Return ``(manifest, {cue_id: float32_curve})`` after strict validation.

    Optional expected cues and assets reject a stale artifact against the
    current edit; supplied source files are fingerprinted before and after.
    """
    folder = Path(path)
    manifest_path = folder / "manifest.json"
    if manifest_path.is_symlink():
        raise ValueError("audio gain manifest symlink is unsupported")
    raw = manifest_path.read_bytes()
    manifest = json.loads(raw)
    if not isinstance(manifest, dict) or set(manifest) != {
            "version", "scope", "actor", "decision_reason", "sample_rate", "channels",
            "samples", "duration", "settings", "speech", "global_peak_guard_gain",
            "mixed_wav", "cues", "manifest_sha256"}:
        raise ValueError("invalid audio gain manifest")
    seal = manifest.pop("manifest_sha256")
    if not isinstance(seal, str) or seal != _digest(manifest):
        raise ValueError("audio gain manifest fingerprint mismatch")
    manifest["manifest_sha256"] = seal
    if (type(manifest["version"]) is not int or manifest["version"] != 1 or
            manifest["scope"] != "pre_normalization" or
            manifest["actor"] != "automation" or
            manifest["decision_reason"] != "Capture measured renderer gain before final normalization" or
            type(manifest["sample_rate"]) is not int or manifest["sample_rate"] != RATE or
            type(manifest["channels"]) is not int or manifest["channels"] != CHANNELS or
            type(manifest["samples"]) is not int or manifest["samples"] <= 0 or
            manifest["duration"] != str(manifest["samples"] / RATE) or
            not isinstance(manifest["settings"], dict) or
            not _valid_fp(manifest["mixed_wav"]) or
            (manifest["speech"] is not None and not _valid_fp(manifest["speech"])) or
            not isinstance(manifest["cues"], list)):
        raise ValueError("invalid audio gain manifest fields")
    if set(manifest["settings"]) - _SETTINGS or _gain_settings(manifest["settings"]) != manifest["settings"]:
        raise ValueError("invalid audio gain settings")
    guard = manifest["global_peak_guard_gain"]
    if type(guard) not in (float, int) or not math.isfinite(guard) or not 0 < guard <= 1:
        raise ValueError("invalid global peak guard")
    if expected_cues is not None and [cue_identity(cue) for cue in expected_cues] != [row.get("cue") for row in manifest["cues"]]:
        raise ValueError("audio gain cues are stale")
    expected_assets = _asset_map(expected_assets) if expected_assets is not None else None
    checked_files = []
    if expected_speech is not None:
        if manifest["speech"] is None or file_identity(expected_speech) != manifest["speech"]:
            raise ValueError("audio gain speech is stale")
        checked_files.append((expected_speech, manifest["speech"], "speech"))
    if expected_mixed_wav is not None:
        if file_identity(expected_mixed_wav) != manifest["mixed_wav"]:
            raise ValueError("audio gain mixed WAV is stale")
        checked_files.append((expected_mixed_wav, manifest["mixed_wav"], "mixed WAV"))
    curves = {}
    used_names = set()
    for row in manifest["cues"]:
        if not isinstance(row, dict) or set(row) != {"cue", "asset", "first_sample", "end_sample",
                                                  "source_period_samples", "array", "array_sha256"}:
            raise ValueError("invalid audio gain cue")
        cue = row["cue"]
        identity_keys = {"id", "asset_id", "role", "loop", "duck", *_TIMES}
        if not isinstance(cue, dict) or set(cue) not in (identity_keys, identity_keys | {'audio_retime_sha256'}):
            raise ValueError("invalid audio gain cue identity")
        if 'audio_retime_sha256' in cue and (cue.get('role') != 'sfx' or
                not isinstance(cue['audio_retime_sha256'], str) or not _HEX.fullmatch(cue['audio_retime_sha256'])):
            raise ValueError('invalid audio gain SFX retime binding')
        if (not isinstance(cue["id"], str) or not cue["id"] or cue["id"] in curves or
                not isinstance(cue["asset_id"], str) or cue["role"] not in ("music", "sfx") or
                type(cue["loop"]) is not bool or type(cue["duck"]) is not bool or
                not _valid_fp(row["asset"])):
            raise ValueError("invalid audio gain cue fields")
        first = round(_seconds(cue["output_start"], "output_start") * RATE)
        end = round(_seconds(cue["output_end"], "output_end") * RATE)
        period = row["source_period_samples"]
        expected_period = round(float(_seconds(cue["source_end"], "source_end") -
                                      _seconds(cue["source_start"], "source_start")) * RATE)
        if (type(row["first_sample"]) is not int or type(row["end_sample"]) is not int or
                (first, end) != (row["first_sample"], row["end_sample"]) or
                not 0 <= first < end <= manifest["samples"] or
                expected_period <= 0 or
                (cue["loop"] and (type(period) is not int or period != expected_period)) or
                (not cue["loop"] and period is not None)):
            raise ValueError("invalid audio gain cue timing")
        name = row["array"]
        if not isinstance(name, str) or not _ARRAY_NAME.fullmatch(name) or name in used_names:
            raise ValueError("invalid audio gain array name")
        used_names.add(name)
        if not isinstance(row["array_sha256"], str) or not _HEX.fullmatch(row["array_sha256"]):
            raise ValueError("invalid audio gain array fingerprint")
        if expected_assets is not None:
            asset = expected_assets.get(cue["asset_id"])
            if not isinstance(asset, dict):
                raise ValueError("audio gain asset is stale")
            asset_path = asset.get("path") or asset.get("local_path")
            registry_sha = asset.get("sha256") or asset.get("file_sha256")
            if (asset_path is None or registry_sha != row["asset"]["sha256"] or
                    file_identity(asset_path) != row["asset"]):
                raise ValueError("audio gain asset is stale")
            checked_files.append((asset_path, row["asset"], "asset"))
        array_path = folder / name
        if array_path.is_symlink():
            raise ValueError("audio gain array symlink is unsupported")
        if _sha(array_path) != row["array_sha256"]:
            raise ValueError("audio gain array fingerprint mismatch")
        array = np.load(array_path, allow_pickle=False)
        if (_sha(array_path) != row["array_sha256"] or type(array) is not np.ndarray or
                array.dtype != np.dtype("float32") or array.ndim != 1 or len(array) != end - first or
                not np.all(np.isfinite(array)) or np.any(array < 0)):
            raise ValueError("invalid audio gain array")
        curves[cue["id"]] = array
    if _sha(manifest_path) != hashlib.sha256(raw).hexdigest():
        raise ValueError("audio gain manifest changed during read")
    for checked_path, expected, kind in checked_files:
        if file_identity(checked_path) != expected:
            raise ValueError(f"audio gain {kind} changed during read")
    return manifest, curves
