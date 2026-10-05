import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from video_harness import media


def data(audio_start=0, audio_duration=4, video_duration=4):
    streams = [{"codec_type": "video", "start_time": "0", "duration": str(video_duration),
                "color_primaries": "bt709", "color_transfer": "bt709", "color_space": "bt709"}]
    if audio_duration is not None:
        streams.append({"codec_type": "audio", "start_time": str(audio_start), "duration": str(audio_duration)})
    return {"streams": streams, "format": {"duration": "4"}}


class MediaTimingTests(unittest.TestCase):
    def verify(self, info, **kwargs):
        with tempfile.TemporaryDirectory() as tmp, patch.object(media, "probe", return_value=info), patch.object(media, "run") as decode:
            result = media.verify(Path("fixture.mp4"), Path(tmp), expected_duration=4, **kwargs)
            decode.assert_called_once()
            return result

    def test_short_or_delayed_audio_rejected(self):
        for info in (data(audio_duration=1), data(audio_start=1, audio_duration=3)):
            with self.subTest(info=info), self.assertRaisesRegex(ValueError, "audio track range"):
                self.verify(info, require_audio=True)
        with self.assertRaisesRegex(ValueError, "audio track range"):
            self.verify(data(audio_duration=1))

    def test_explicit_intentional_audio_range(self):
        self.verify(data(audio_start=1, audio_duration=2), require_audio=True, expected_audio_range=(1, 3))
        with self.assertRaisesRegex(ValueError, "audio track range"):
            self.verify(data(audio_start=1, audio_duration=1), expected_audio_range=(1, 3))

    def test_video_length_not_hidden_by_container_or_audio(self):
        with self.assertRaisesRegex(ValueError, "video track duration"):
            self.verify(data(video_duration=1))

    def test_silent_video_and_aac_tolerance(self):
        self.verify(data(audio_duration=None))
        self.verify(data(audio_duration=4.021333), require_audio=True)
        with self.assertRaisesRegex(ValueError, "Missing audio"):
            self.verify(data(audio_duration=None), require_audio=True)

    def test_track_duration_fallback_and_invalid_timing(self):
        j = data()
        audio = j["streams"][1]
        del audio["duration"]
        audio.update(duration_ts=192000, time_base="1/48000")
        self.assertEqual(media.stream_bounds(j, "audio"), (0, 4))
        audio["duration_ts"] = "nan"
        with self.assertRaises(ValueError):
            media.stream_bounds(j, "audio")


if __name__ == "__main__":
    unittest.main()
