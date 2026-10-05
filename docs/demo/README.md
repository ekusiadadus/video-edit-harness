# Demo provenance

The updated 29-second walkthrough uses FFmpeg-generated test-pattern video and **AI-generated Japanese speech**, synthesized by OpenAI `gpt-4o-mini-tts` with the built-in `marin` voice and an instruction for calm, connected, natural Japanese delivery. See the [official speech guide](https://developers.openai.com/api/docs/guides/text-to-speech). It compares an 11.27-second source with a 9.67-second harness render. No personal footage or private transcript is included.

The two synthetic utterances contain a deliberately inserted two-second pause. This new MP4 was actually transcribed through OpenAI cloud APIs, attached to a new session, and edited with the observed word timestamps. All 31 word anchors were retained. The frame-aligned source ranges are `[0.0, 4.1]` and `[5.7, 11.2666667]`; 1.6 seconds between the sentences were removed. The original remains unchanged. Ten-millisecond boundary fades are applied only in available padding, never over retained words.

The edited segment is the actual `warm_documentary` harness render, with a -18 LUFS normalization target. The presentation captions and surrounding cards were composed for this walkthrough and are not an agent/editor screen recording. Presentation captions follow the known TTS script; automatic transcript spelling still needs review (for example, `話し` versus `話`). No human listening approval is inferred from technical verification.

The final cards describe word retention, the voice/audio settings, and the generated FCPXML, SRT, and LUT. Final Cut Pro GUI import and playback are not demonstrated. [Recording guide](../SCREEN_RECORDING.md) describes how to capture a real Codex session.

`preview.gif` is a silent, reduced-resolution preview. Click it in either README to watch or download the 1280×720 H.264/AAC MP4 with sound. The demo is `video-edit-harness-demo-v2.mp4` in the `v0.1.0-alpha.2` release, with a separate `DEMO-SHA256SUMS` file. The original demo and alpha.1 package archives remain available in the older release.
