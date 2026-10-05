---
name: tiktok
description: Edit a local video for TikTok, Reels or YouTube Shorts with a clear short-form story, appropriate grade, audio, captions and a reviewed 9:16 MP4. Use when the user invokes /tiktok or asks for a vertical short; do not upload or post by default.
---

# TikTok editing

In Claude Code, `/tiktok /path/to/video.mov [brief]` supplies the video path and optional brief in `$ARGUMENTS`. In Codex, use `$tiktok` with the same path and brief. A marketplace plugin exposes the namespaced `/video-editing:tiktok`; install this standalone skill under `.claude/skills/tiktok` for the exact `/tiktok` spelling.

Use the Video Edit Harness checkout (`v0.1.0-alpha.3`). Locate it through `VIDEO_EDIT_HARNESS_ROOT` or the project checkout. If absent, follow the [installation guide](https://github.com/ekusiadadus/video-edit-harness/blob/v0.1.0-alpha.3/docs/SKILL_INSTALL.md). Read README.md and AGENTS.md; run `uv run video-harness --help` from the harness root. This skill is editing guidance, not authorization to install dependencies, send footage, post to TikTok, or publish a screen recording.

## Understand the request and preserve the source

Resolve the actual local input path; never interpret an arbitrary URL as permission to download or upload. Inspect duration, dimensions, rotation, frame rate, color space and audio. Preserve the input. Determine the audience, message, target length and style from the request and footage. Ask only for a critical unresolved choice; continue local inspection while waiting. When unspecified, make a short preview with fit framing, natural color and clear speech; keep the original duration until a transcript-backed story is selected. A 15–60-second target can be an editorial starting point, not a TikTok upload limit or a reason to cut a sentence.

Honor no-upload/no-publication restrictions, including private footage of children. No cloud transcription, screenshots, previews, clips or stills of protected media may be uploaded. Public demonstrations use permitted synthetic media. OpenAI then Azure are the only transcription providers, and require explicit source upload authorization. Do not start local Whisper. When upload is forbidden and no sealed transcript exists, prepare local grading/framing/audio only; explain that word-anchored story edits need a permitted transcript. Never make up alignment.

## Make the short understandable

Use the `video-editing` skill in this checkout for source-bound transcription, word IDs, ordered chapter spans, omissions, revisions and render review. Give the viewer useful context early, focus on one coherent point, and retain the payoff. Remove redundant setup only when evidence supports it. Preserve negation, qualifications, names, sentence endings, breaths and emphasis. Do not add invented claims, clickbait, music rights, engagement promises, or a forced call to action. Check both audio-only clarity and the silent/caption viewing experience.

For local-only grading, copy a project template, set its actual source and color space, and choose the use case from the scene (indoor talk, outdoor daylight/night, backlight, etc.), not from the platform name. Start with `natural` or `clean_editorial`; compare another style on the same interval where useful. Run `preview PROJECT --styles ...` without a transcript. After an actual selection, use the chosen profile to render; do not assert human approval yourself. Avoid double-transforming Apple Log. Normalize measured speech as a project choice; do not amplify clipping or invent a platform LUFS rule.

## Produce 9:16 delivery

After the graded preview/full edit exists, run:

```sh
uv run video-harness tiktok-export /absolute/path/to/graded-video.mp4 \
  --output output/my-tiktok --framing fit
```

Default fit/padding preserves the whole picture. Choose `--framing center_crop` only when the user wants it and the subject/text survive inspection across the clip. There is no automatic face tracking. Do not crop hands, demonstrations or multi-person conversations blindly. This export consumes graded SDR/Rec.709 media; it does not transform raw Apple Log or HDR by itself.

When an actual reviewed SRT matches this exact input edit, add `--subtitles /absolute/path/to/subtitles.srt` to burn captions. Inspect Japanese wording, line breaks, timing, readability and overlays at the top, bottom and right. The exporter uses conservative working margins; TikTok's actual UI safe area varies with device, caption and interactive elements. These margins are not an official guarantee. Do not attach a stale SRT from another edit, invent subtitles without listening, or imply automatic captions are reviewed.

The deliverable is a local 1080×1920 H.264/AAC MP4, technical checks and source/output fingerprints. Review framing, every edit boundary, captions and audio; offer the path to the result and list any unresolved checks. Verify full decode, dimensions, aspect, duration and audio coverage. Separate agent selection, human perceptual review and platform playback. The vertical export does not modify the original-source FCPXML framing: apply and verify portrait framing separately in FCP if needed.

Do not post, schedule, upload, add platform music or claim TikTok playback without a further explicit instruction. Use [TikTok workflow notes](https://github.com/ekusiadadus/video-edit-harness/blob/v0.1.0-alpha.3/docs/TIKTOK.md) for examples and evidence limits.
