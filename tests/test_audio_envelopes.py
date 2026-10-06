import hashlib
import json
import tempfile
import unittest
import wave
from pathlib import Path
from unittest.mock import patch

import numpy as np

from video_harness.audio_envelopes import load_audio_envelopes
from video_harness.audio_mix import render_mix


def _wav(path, data):
    with wave.open(str(path), "wb") as stream:
        stream.setparams((2, 2, 48000, 0, "NONE", "not compressed"))
        stream.writeframes((np.clip(data, -1, 1) * 32767).astype("<i2").tobytes())


def _sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


class AudioEnvelopeTests(unittest.TestCase):
    def _fixture(self, root, *, speech=True, loud=False):
        period = np.arange(48000) / 48000
        amplitude = .8 if loud else .08
        tone = amplitude * np.sin(2 * np.pi * 220 * period)
        _wav(root / "music.wav", np.column_stack((tone, tone)))
        speech_path = None
        if speech:
            spoken = np.zeros((96000, 2))
            spoken[:24000] = .3 if loud else .12
            _wav(root / "speech.wav", spoken)
            speech_path = root / "speech.wav"
        asset = {"asset_id": "m", "kind": "audio" if loud else "music", "path": str(root / "music.wav"),
                 "sha256": _sha(root / "music.wav")}
        cue = {"id": "bg", "asset_id": "m", "role": "sfx" if loud else "music", "output_start": 0,
               "output_end": 2, "source_start": 0, "source_end": 1,
               "loop": True, "duck": not loud, "fade_in": .1, "fade_out": .1}
        return speech_path, [cue], [asset]

    def test_curve_captures_duck_fade_loop_and_identical_pcm(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            speech, cues, assets = self._fixture(root)
            settings = {"duck_hold_seconds": .4}
            render_mix(speech, cues, assets, root / "legacy.wav", 2, settings)
            evidence = render_mix(speech, cues, assets, root / "captured.wav", 2, settings,
                                  gain_output=root / "gains")
            self.assertEqual((root / "legacy.wav").read_bytes(), (root / "captured.wav").read_bytes())
            manifest, curves = load_audio_envelopes(root / "gains", expected_assets=assets)
            curve = curves["bg"]
            self.assertEqual(curve.dtype, np.float32)
            self.assertEqual(len(curve), 96000)
            self.assertEqual(curve[0], 0)
            self.assertEqual(curve[-1], 0)
            self.assertEqual(curve[48000], 0)  # measured loop seam
            self.assertLess(curve[10000], curve[70000])  # speech duck recovers
            self.assertEqual(manifest["cues"][0]["source_period_samples"], 48000)
            self.assertEqual(manifest["global_peak_guard_gain"], evidence["peak_guard_gain"])
            self.assertEqual(manifest["mixed_wav"]["sha256"], _sha(root / "captured.wav"))
            self.assertNotIn(str(root), json.dumps(manifest))

    def test_peak_guard_and_stale_asset_rejection(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            speech, cues, assets = self._fixture(root, loud=True)
            evidence = render_mix(speech, cues, assets, root / "mix.wav", 2,
                                  gain_output=root / "gains")
            manifest, _ = load_audio_envelopes(root / "gains", expected_assets=assets)
            self.assertLess(evidence["peak_guard_gain"], 1)
            self.assertEqual(manifest["global_peak_guard_gain"], evidence["peak_guard_gain"])
            changed = dict(assets[0], path=str(root / "other.wav"))
            _wav(root / "other.wav", np.zeros((48000, 2)))
            with self.assertRaisesRegex(ValueError, "stale"):
                load_audio_envelopes(root / "gains", expected_assets=[changed])
            with self.assertRaisesRegex(ValueError, "stale"):
                load_audio_envelopes(root / "gains", expected_cues=[dict(cues[0], fade_in=.2)])

    def test_tamper_and_malformed_array_rejected_even_when_resealed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            speech, cues, assets = self._fixture(root, speech=False)
            render_mix(speech, cues, assets, root / "mix.wav", 2, gain_output=root / "gains")
            manifest_path = root / "gains" / "manifest.json"
            original = manifest_path.read_bytes()
            manifest = json.loads(original)
            manifest["cues"][0]["end_sample"] -= 1
            manifest_path.write_text(json.dumps(manifest))
            with self.assertRaisesRegex(ValueError, "fingerprint"):
                load_audio_envelopes(root / "gains")
            manifest_path.write_bytes(original)
            array_path = root / "gains" / "cue-0000.npy"
            np.save(array_path, np.array([object()], dtype=object), allow_pickle=True)
            with self.assertRaisesRegex(ValueError, "fingerprint"):
                load_audio_envelopes(root / "gains")

    def test_source_changed_during_decode_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            speech, cues, assets = self._fixture(root)
            from video_harness import audio_mix
            decode = audio_mix._decode

            def changing_decode(path, *args, **kwargs):
                result = decode(path, *args, **kwargs)
                if Path(path) == speech:
                    with speech.open("ab") as stream:
                        stream.write(b"changed")
                return result

            with patch.object(audio_mix, "_decode", side_effect=changing_decode):
                with self.assertRaisesRegex(ValueError, "speech source changed"):
                    render_mix(speech, cues, assets, root / "mix.wav", 2,
                               gain_output=root / "gains")

    def test_nonfinite_audio_setting_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            speech, cues, assets = self._fixture(root)
            with self.assertRaisesRegex(ValueError, "finite"):
                render_mix(speech, cues, assets, root / "mix.wav", 2,
                           {"duck_attack_seconds": float("nan")}, gain_output=root / "gains")

    def test_private_unrelated_settings_excluded_and_wav_bound(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            speech, cues, assets = self._fixture(root)
            render_mix(speech, cues, assets, root / "mix.wav", 2,
                       {"duck_db": -8, "private_notes": {"source": str(root / "secret.mov")},
                        "target_lufs": -16}, gain_output=root / "gains")
            manifest, _ = load_audio_envelopes(root / "gains", expected_speech=speech,
                                               expected_mixed_wav=root / "mix.wav")
            self.assertEqual(manifest["settings"], {"duck_db": -8.0})
            self.assertNotIn(str(root), (root / "gains" / "manifest.json").read_text())
            with (root / "mix.wav").open("ab") as stream:
                stream.write(b"changed")
            with self.assertRaisesRegex(ValueError, "mixed WAV is stale"):
                load_audio_envelopes(root / "gains", expected_mixed_wav=root / "mix.wav")

    def test_source_change_during_artifact_read_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            speech, cues, assets = self._fixture(root)
            render_mix(speech, cues, assets, root / "mix.wav", 2, gain_output=root / "gains")
            from video_harness import audio_envelopes
            original_sha = audio_envelopes._sha
            changed = False

            def sha_with_change(path):
                nonlocal changed
                if not changed and Path(path).suffix == ".npy":
                    changed = True
                    with speech.open("ab") as stream:
                        stream.write(b"changed")
                return original_sha(path)

            with patch.object(audio_envelopes, "_sha", side_effect=sha_with_change):
                with self.assertRaisesRegex(ValueError, "speech changed during read"):
                    load_audio_envelopes(root / "gains", expected_speech=speech)

    def test_symlink_array_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            speech, cues, assets = self._fixture(root, speech=False)
            render_mix(speech, cues, assets, root / "mix.wav", 2, gain_output=root / "gains")
            array = root / "gains" / "cue-0000.npy"
            array.rename(root / "saved.npy")
            array.symlink_to(root / "saved.npy")
            with self.assertRaisesRegex(ValueError, "symlink"):
                load_audio_envelopes(root / "gains")


    def test_rational_half_sample_boundary_matches_renderer(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            speech, cues, assets = self._fixture(root)
            cues[0]['output_start'] = '9/32000'
            render_mix(speech, cues, assets, root / 'mix.wav', 2,
                       gain_output=root / 'gains')
            manifest, curves = load_audio_envelopes(root / 'gains', expected_cues=cues,
                expected_assets=assets, expected_speech=speech, expected_mixed_wav=root / 'mix.wav')
            self.assertEqual(manifest['cues'][0]['first_sample'], 14)
            self.assertEqual(len(curves['bg']), 96000 - 14)
