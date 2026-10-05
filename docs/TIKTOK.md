# TikTok / vertical-short workflow

English | [日本語](TIKTOK.ja.md)

The dedicated `tiktok` skill prepares local TikTok, Reels and YouTube Shorts edits. Install the pinned harness and the standalone skill using the [installation guide](SKILL_INSTALL.md). For the exact Claude Code `/tiktok` command, copy `.agents/skills/tiktok` or the release's extracted `tiktok/` folder into `~/.claude/skills/tiktok` and start a new session. In Codex invoke `$tiktok`. The marketplace plugin exposes `/video-editing:tiktok`.

```text
/tiktok /absolute/path/to/video.mov
/tiktok /absolute/path/to/talk.mp4 Make a clear 30-second explanation. Preserve sentence endings. No uploads.
```

These are agent skill invocations, not shell commands. A bare file path does not authorize cloud transcription or posting. Protected footage, including a child's video marked private, stays local.

The workflow inspects the source, chooses color settings for the actual scene, and prepares a preview. A reviewed transcript and word IDs enable a focused hook → point → payoff story, preserving qualifications and meaning. Without an allowed transcript, the skill can still prepare local color, framing and audio; it does not invent timing or auto-cut speech. 15–60 seconds is a possible creative brief, not a platform limit.

After the graded or edited MP4 exists:

```sh
uv run video-harness tiktok-export /absolute/path/to/graded-video.mp4 \
  --output output/my-tiktok --framing fit
# Optional: burn a reviewed SRT that matches this exact edit.
uv run video-harness tiktok-export /absolute/path/to/graded-video.mp4 \
  --output output/my-tiktok-captioned --framing fit \
  --subtitles /absolute/path/to/subtitles.srt
```

The exporter writes a 1080×1920, square-pixel H.264 MP4 with its audio, fingerprints and technical verification. Fit/padding is the default; `center_crop` is explicit and needs shot-by-shot subject/text review. No automatic face tracking is claimed. The input must already be graded SDR/Rec.709; use the harness's Apple Log transform first when applicable.

TikTok's [official in-feed advertising specs](https://ads.tiktok.com/resources/help/article/tiktok-auction-in-feed-ads?redirected=1) recommend 9:16 and say the safe area depends on dimensions, captions and interactive formats. This is an advertising reference, not a universal organic-upload specification. The harness's 1080×1920 output and conservative caption margins are working defaults, not official UI-safe guarantees. Check the actual destination preview on the target phone before posting.

The portrait derivative does not change source-aspect FCPXML. Apply portrait framing separately in Final Cut Pro and verify it there if that handoff is needed. Full decode, dimensions, duration and audio checks are technical evidence; they do not prove visual quality, subtitle wording, human listening acceptance or TikTok playback. Uploading/posting remains a separate explicit request.
