"""Synthetic SFX retime contracts; these tests make no listening claim."""

from copy import deepcopy
from fractions import Fraction
import hashlib
from pathlib import Path
import tempfile
import shutil
import unittest
from unittest.mock import patch
import wave

import numpy as np

from video_harness.render_cache import digest
from video_harness.sfx_retime import (make_audio_retime, render_retimed_sfx,
                                      validate_audio_retime)
from video_harness.time_mapping import compile_retime


RATE = 48000


class SfxRetimeTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.path = Path(self.temporary.name) / "marker.wav"

    def fixture(self, fps="30", *, frames=12, first=2, end=9,
                freeze_frame=5, freeze_frames=3, fade_in=0, fade_out=0):
        rate = Fraction(fps)
        count = round(Fraction(frames * RATE, 1) / rate)
        # Different values in each channel and each source frame expose a
        # restarted trim, channel swap, or silent freeze that resumes late.
        samples = np.empty((count, 2), dtype=np.float32)
        for frame in range(frames):
            lo = round(Fraction(frame * RATE, 1) / rate)
            hi = round(Fraction((frame + 1) * RATE, 1) / rate)
            samples[lo:hi, 0] = (frame + 1) / 40
            samples[lo:hi, 1] = -(frame + 1) / 80
        with wave.open(str(self.path), "wb") as stream:
            stream.setparams((2, 2, RATE, 0, "NONE", "not compressed"))
            stream.writeframes((samples * 32767).astype("<i2").tobytes())
        source_sha = hashlib.sha256(self.path.read_bytes()).hexdigest()
        assets = [{"asset_id": "hit", "kind": "audio", "path": str(self.path),
                   "sha256": source_sha}]
        cue = {"id": "hit-1", "asset_id": "hit", "role": "sfx",
               "output_start": str(Fraction(first, 1) / rate),
               "output_end": str(Fraction(end, 1) / rate),
               "source_start": "0", "source_end": str(Fraction(frames, 1) / rate),
               "fade_in": str(Fraction(fade_in, 1) / rate),
               "fade_out": str(Fraction(fade_out, 1) / rate), "loop": False}
        compiled = compile_retime(frames, fps, [{"id": "hold", "kind": "freeze",
            "source_frame": freeze_frame, "output_frames": freeze_frames,
            "reason": "Synthetic visual hold"}])
        return cue, assets, compiled, samples

    @staticmethod
    def sealed(cue, assets, compiled, backend="phase_vocoder"):
        original = deepcopy(cue)
        metadata = make_audio_retime(cue, assets, compiled, backend=backend)
        assert cue == original, "make_audio_retime must not mutate the cue"
        result = deepcopy(cue)
        result["audio_retime"] = metadata
        start = metadata["original_start_frame"]
        end = metadata["original_end_frame_exclusive"]
        included = [index for index, source in enumerate(compiled["frame_map"])
                    if start <= source < end]
        result["output_start"] = str(Fraction(included[0], 1) / Fraction(compiled["fps"]))
        result["output_end"] = str(Fraction(included[-1] + 1, 1) / Fraction(compiled["fps"]))
        return result

    def test_metadata_is_sealed_and_interval_is_inverse_half_open_membership(self):
        cue, assets, compiled, _ = self.fixture()
        result = self.sealed(cue, assets, compiled)
        metadata = result["audio_retime"]
        self.assertEqual(metadata["version"], 1)
        self.assertEqual(metadata["mapping"], compiled)
        self.assertEqual(metadata["mapping_sha256"], digest(compiled))
        self.assertEqual((metadata["original_start_frame"],
                          metadata["original_end_frame_exclusive"]), (2, 9))
        self.assertEqual(metadata["source_sha256"], assets[0]["sha256"])
        self.assertEqual(metadata["content_sha256"], digest({
            "asset_id": "hit", "source_sha256": assets[0]["sha256"],
            "source_start": "0", "source_end": "2/5",
            "fade_in": "0", "fade_out": "0"}))
        self.assertEqual((result["output_start"], result["output_end"]),
                         ("1/15", "2/5"))
        self.assertEqual(validate_audio_retime(result, assets, "30"), metadata)
        self.assertEqual(validate_audio_retime(result), metadata)
        self.assertIsNone(validate_audio_retime(cue))

    def test_rejects_tampered_mapping_even_with_updated_digest(self):
        cue, assets, compiled, _ = self.fixture()
        result = self.sealed(cue, assets, compiled)
        forged = deepcopy(result)
        forged["audio_retime"]["mapping"]["frame_map"][0] = 1
        forged["audio_retime"]["mapping_sha256"] = digest(forged["audio_retime"]["mapping"])
        for candidate in (forged, dict(result, output_end="11/30"),
                          dict(result, output_start="1/10")):
            with self.subTest(candidate=candidate["output_start"]), self.assertRaises(ValueError):
                validate_audio_retime(candidate, assets, "30")

    def test_rejects_stale_trim_fades_and_source_sha(self):
        cue, assets, compiled, _ = self.fixture()
        result = self.sealed(cue, assets, compiled)
        for field, value in (("source_start", "1/30"), ("source_end", "11/30"),
                             ("fade_in", "1/30"), ("fade_out", "1/30"),
                             ("asset_id", "other")):
            candidate = deepcopy(result)
            candidate[field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                validate_audio_retime(candidate)
        changed_asset = [dict(assets[0], sha256="0" * 64)]
        with self.assertRaises(ValueError):
            validate_audio_retime(result, changed_asset, "30")
        changed_source = deepcopy(result)
        changed_source["audio_retime"]["source_sha256"] = "0" * 64
        with self.assertRaises(ValueError):
            validate_audio_retime(changed_source)

    def test_rejects_music_and_changed_loop_policy(self):
        cue, assets, compiled, _ = self.fixture()
        for changed in (dict(cue, role="music"),):
            with self.subTest(changed=changed["role"], loop=changed["loop"]):
                with self.assertRaises(ValueError):
                    make_audio_retime(changed, assets, compiled)
        sealed = self.sealed(cue, assets, compiled)
        for changed in (dict(sealed, role="music"), dict(sealed, loop=True)):
            with self.assertRaises(ValueError):
                validate_audio_retime(changed)

    def test_loop_preserves_original_seams_and_freeze_resume_phase(self):
        from video_harness.loop_audio import loop_pcm
        cue, assets, compiled, samples = self.fixture(fade_in=1, fade_out=1)
        cue.update(loop=True, source_end='1/30')
        sealed = self.sealed(cue, assets, compiled)
        self.assertEqual(sealed['audio_retime']['version'], 2)
        self.assertEqual(sealed['audio_retime']['loop_period_samples'], 1600)
        original, _, taper = loop_pcm(samples[:1600], 7*1600)
        original[:1600] *= np.linspace(0, 1, 1600, dtype=np.float32)[:, None]
        original[-1600:] *= np.linspace(1, 0, 1600, dtype=np.float32)[:, None]
        output, evidence = render_retimed_sfx(samples[:1600], sealed)
        expected = np.concatenate((original[:3*1600], np.zeros((3*1600, 2), dtype=np.float32), original[3*1600:]))
        np.testing.assert_array_equal(output, expected)
        self.assertEqual(evidence['loop_seam_taper_samples'], taper)
        self.assertEqual(evidence['loop_policy'], 'original_period_and_seams_before_content_retime')
        for key in ('loop_period_samples', 'loop_seam_taper_samples'):
            changed = deepcopy(sealed)
            changed['audio_retime'][key] += 1
            with self.assertRaisesRegex(ValueError, 'period|taper'):
                validate_audio_retime(changed)
        with self.assertRaisesRegex(ValueError, 'loop policy'):
            validate_audio_retime(dict(sealed, loop=False))

    def test_looped_mixer_gain_evidence_retains_original_period_binding(self):
        from video_harness.audio_mix import render_mix
        from video_harness.audio_envelopes import load_audio_envelopes
        cue, assets, compiled, _ = self.fixture()
        cue.update(loop=True, source_end='1/100')
        sealed = self.sealed(cue, assets, compiled)
        root = Path(self.temporary.name)
        evidence = render_mix(None, [sealed], assets, root/'loop.wav', Fraction(15, 30), gain_output=root/'loop-gain')
        manifest, _ = load_audio_envelopes(root/'loop-gain', expected_cues=[sealed])
        self.assertEqual(manifest['cues'][0]['source_period_samples'], 480)
        self.assertEqual(evidence['cues'][0]['content_retime']['loop_period_samples'], 480)
        self.assertEqual(evidence['cues'][0]['loop_seam_taper_seconds'], .0025)
        self.assertEqual(evidence['cues'][0]['loop_seam_taper_samples'], 120)
        self.assertEqual(evidence['cues'][0]['loop_seam_taper_clock'], 'original_cue_pcm')
        self.assertTrue(manifest['cues'][0]['cue']['loop'])

    def test_shared_loop_matches_legacy_pcm_and_gain_at_partial_final_seam(self):
        from video_harness.loop_audio import loop_pcm
        for period, target in ((3, 20), (15, 46), (2000, 4011)):
            with self.subTest(period=period):
                chunk = np.random.default_rng(7).uniform(-.2, .2, (period, 2)).astype(np.float32)
                expected = np.tile(chunk, ((target+period-1)//period, 1))[:target].copy()
                gain = np.ones(target, dtype=np.float32)
                taper = min(480, period//4)
                if taper:
                    for seam in range(period, target, period):
                        left, right = min(taper, seam), min(taper, target-seam)
                        a, b = np.linspace(1, 0, left, dtype=np.float32), np.linspace(0, 1, right, dtype=np.float32)
                        expected[seam-left:seam] *= a[:, None]
                        expected[seam:seam+right] *= b[:, None]
                        gain[seam-left:seam] *= a
                        gain[seam:seam+right] *= b
                actual, curve, _ = loop_pcm(chunk, target, capture_gain=True)
                np.testing.assert_array_equal(actual, expected)
                np.testing.assert_array_equal(curve, gain)

    def test_stereo_freeze_is_silence_then_resumes_source_at_exact_frame(self):
        cue, assets, compiled, samples = self.fixture()
        sealed = self.sealed(cue, assets, compiled)
        output, evidence = render_retimed_sfx(samples, sealed)
        frame = RATE // 30
        expected = np.concatenate((samples[:3*frame],
                                   np.zeros((3*frame, 2), dtype=np.float32),
                                   samples[3*frame:7*frame]))
        self.assertEqual(output.shape, (10*frame, 2))
        self.assertEqual(output.dtype, np.float32)
        np.testing.assert_array_equal(output, expected)
        self.assertEqual(evidence["audio"]["freeze_audio_policy"],
                         "inserted_silence_then_resume_source_pcm")
        self.assertEqual(evidence["original_cue_samples"], [2*frame, 9*frame])
        self.assertEqual(evidence["fade_policy"], "original_pcm_before_content_retime")
        self.assertEqual(evidence["output_cue_samples"], [2*frame, 12*frame])

    def test_fractional_fps_uses_absolute_sample_bounds(self):
        fps = "30000/1001"
        cue, assets, compiled, samples = self.fixture(fps, frames=30, end=22,
            freeze_frame=10, freeze_frames=2)
        sealed = self.sealed(cue, assets, compiled)
        output, _ = render_retimed_sfx(samples, sealed)
        rate = Fraction(fps)
        first = round(Fraction(2 * RATE, 1) / rate)
        last = round(Fraction(24 * RATE, 1) / rate)
        self.assertEqual(len(output), last-first)
        self.assertEqual(output.shape[1], 2)

    def test_short_trimmed_source_is_rejected(self):
        cue, assets, compiled, samples = self.fixture()
        sealed = self.sealed(cue, assets, compiled)
        old_samples = 7 * (RATE // 30)
        with self.assertRaisesRegex(ValueError, "short|length|samples"):
            render_retimed_sfx(samples[:old_samples-100], sealed)

    def test_fades_are_applied_on_original_clock_before_retime(self):
        cue, assets, compiled, samples = self.fixture(fade_in=1, fade_out=1)
        sealed = self.sealed(cue, assets, compiled)
        captured = []

        def capture(source, sample_rate, mapping, **kwargs):
            captured.append(source.copy())
            count = round(Fraction(mapping["output_frame_count"] * sample_rate, 1)
                          / Fraction(mapping["fps"]))
            return np.zeros((count, 2), dtype=np.float32), {"captured": True}

        with patch("video_harness.retime_audio.retime_audio", side_effect=capture):
            output, evidence = render_retimed_sfx(samples, sealed)
        self.assertEqual(len(captured), 1)
        old = captured[0]
        frame = RATE // 30
        np.testing.assert_array_equal(old[:2*frame], 0)
        self.assertEqual(old[2*frame, 0], 0)
        self.assertGreater(old[3*frame, 0], 0)
        self.assertGreater(old[8*frame, 0], 0)
        self.assertEqual(old[9*frame-1, 0], 0)
        np.testing.assert_array_equal(old[9*frame:], 0)
        self.assertEqual(len(output), 10*frame)

    def test_mixer_seals_retime_and_preserves_frozen_silence(self):
        from video_harness.audio_mix import render_mix
        from video_harness.audio_envelopes import load_audio_envelopes
        cue, assets, compiled, _ = self.fixture(fade_in=1)
        sealed = self.sealed(cue, assets, compiled)
        root = Path(self.temporary.name)
        mix = root / 'mix.wav'
        gains = root / 'gains'
        evidence = render_mix(None, [sealed], assets, mix, Fraction(15, 30), gain_output=gains)
        with wave.open(str(mix), 'rb') as stream:
            pcm = np.frombuffer(stream.readframes(stream.getnframes()), dtype='<i2').reshape(-1, 2)
        np.testing.assert_array_equal(pcm[5*1600:8*1600], 0)
        self.assertGreater(np.max(np.abs(pcm[8*1600:9*1600])), 0)
        self.assertEqual(evidence['cues'][0]['content_retime']['fade_policy'],
                         'original_pcm_before_content_retime')
        manifest, _ = load_audio_envelopes(gains, expected_cues=[sealed])
        self.assertEqual(manifest['cues'][0]['cue']['audio_retime_sha256'], digest(sealed['audio_retime']))
        changed = deepcopy(sealed)
        changed['audio_retime']['backend'] = 'rubberband'
        with self.assertRaisesRegex(ValueError, 'stale|match'):
            load_audio_envelopes(gains, expected_cues=[changed])

    @unittest.skipUnless(shutil.which('rubberband'), 'Rubber Band CLI required')
    def test_continuous_speed_ramp_keeps_stereo_tone_pitch(self):
        cue, assets, _, _ = self.fixture(frames=60, first=0, end=60)
        compiled = compile_retime(60, '30', [{'id': 'ramp', 'kind': 'ramp',
            'source_first_frame': 0, 'source_end_frame_exclusive': 60,
            'speed_start': .5, 'speed_end': 1.5, 'reason': 'Synthetic pitch-preserving ramp'}])
        sealed = self.sealed(cue, assets, compiled, backend='rubberband')
        times = np.arange(96000) / RATE
        chunk = np.column_stack((.1*np.sin(2*np.pi*440*times), .1*np.sin(2*np.pi*660*times))).astype(np.float32)
        result, evidence = render_retimed_sfx(chunk, sealed, Path(self.temporary.name) / 'ramp-logs')
        self.assertEqual(result.shape, (96000, 2))
        for channel, expected in ((0, 440), (1, 660)):
            for first in (12000, 60000):
                piece = result[first:first+12000, channel]
                spectrum = np.abs(np.fft.rfft(piece*np.hanning(len(piece))))
                frequency = np.argmax(spectrum) * RATE / len(piece)
                self.assertLessEqual(abs(frequency-expected), 4)
        self.assertEqual(evidence['metadata_sha256'], digest(sealed['audio_retime']))

    @unittest.skipUnless(shutil.which('rubberband'), 'Rubber Band CLI required')
    def test_looped_tone_ramp_stretches_original_periods_with_pitch_preserved(self):
        cue, assets, _, _ = self.fixture(frames=60, first=0, end=60)
        cue.update(loop=True, source_end='1/5')
        mapping = compile_retime(60, '30', [{'id': 'ramp', 'kind': 'ramp',
            'source_first_frame': 0, 'source_end_frame_exclusive': 60,
            'speed_start': .5, 'speed_end': 1.5, 'reason': 'Loop content changes speed'}])
        sealed = self.sealed(cue, assets, mapping, backend='rubberband')
        times = np.arange(9600)/RATE
        chunk = np.column_stack((.1*np.sin(2*np.pi*440*times), .1*np.sin(2*np.pi*660*times))).astype(np.float32)
        result, evidence = render_retimed_sfx(chunk, sealed, Path(self.temporary.name)/'loop-ramp-logs')
        self.assertEqual(result.shape, (96000, 2))
        self.assertEqual(evidence['loop_period_samples'], 9600)
        for first in (12000, 60000):
            for channel, expected in ((0, 440), (1, 660)):
                piece = result[first:first+12000, channel]
                frequency = np.argmax(np.abs(np.fft.rfft(piece*np.hanning(len(piece))))) * RATE/len(piece)
                self.assertLessEqual(abs(frequency-expected), 4)

    def test_editable_handoff_rejects_source_rate_sfx(self):
        from video_harness.production_fcp import export_production_xml
        cue, assets, compiled, _ = self.fixture()
        sealed = self.sealed(cue, assets, compiled)
        with self.assertRaisesRegex(ValueError, 'Retimed SFX'):
            export_production_xml('/unused.xml', {'cues': [sealed]}, None,
                                  Path(self.temporary.name) / 'unsupported.fcpxml', mode='editable')


if __name__ == "__main__":
    unittest.main()
