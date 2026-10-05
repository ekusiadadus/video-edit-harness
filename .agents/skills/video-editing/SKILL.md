---
name: video-editing
description: Edit spoken footage with a durable, reviewable transcript-to-plan-to-render workflow, color and audio checks, and a flat Final Cut Pro XML handoff.
---

# Video editing with Video Edit Harness

This skill requires the [Video Edit Harness](https://github.com/ekusiadadus/video-edit-harness) checkout (release `v0.1.0-alpha.2`), Python 3.11+, uv, FFmpeg and ffprobe. The standalone skill ZIP contains instructions and its license; it does not bundle the harness or media.

Find the harness checkout. If `VIDEO_EDIT_HARNESS_ROOT` is set, use that directory. Otherwise, find the checkout containing `pyproject.toml`, `video_harness/`, and this skill; if the skill was copied elsewhere, ask for the checkout location. Run commands from the harness root with `uv run video-harness`. Read its README.md and AGENTS.md; use `uv run video-harness session --help` for exact command syntax.

Use the current request and existing authorization to establish scope before any cloud upload, message, or publication; ask only when that scope remains unresolved. Cloud transcription needs authorization for the particular source and credentials in environment variables. The route is OpenAI then Azure OpenAI; there is no local Whisper/ASR. Never synthesize human approval or observations. Record your real actor and keep source footage intact.

1. Copy `projects/talk.template.json` for the project. Replace `source` with the actual absolute media path, set `input_color` and preview interval, and check media tracks. Start `session start PROJECT SESSION --brief-file BRIEF --actor ACTOR`, then inspect `session status SESSION --deep`.
2. If source upload is authorized, use `uv run --extra transcription-cloud video-harness session transcribe SESSION`. Or attach a sealed existing transcript with `session transcript SESSION TRANSCRIPT_JSON`. Read the transcript, words, and mismatch warnings. Correct spelling with exact word IDs through `session correct-transcript`; never change timestamps by guessing.
3. Run `session context SESSION --words`. Build a story spec with ordered chapter spans anchored to observed word IDs and omissions with exact IDs, reasons, and goal IDs. `examples/workflow-story.json` shows structure only. Run `session plan SESSION --spec-file SPEC_JSON --actor ACTOR`. Inspect the plan, then `session approve SESSION --actor ACTOR --note REASON`. Agent selection is recorded as agent selection.
4. Render a preview with `session render SESSION`. Review video, audio-only output, subtitles, and frame mapping. Use `session inspect SESSION RENDER_ID --start SECONDS --duration SECONDS` for focused filmstrip, waveform, listening audio, and source words. Listen across cut boundaries; protect word endings, breath, emphasis, and topic changes. Visual aids alone are not a listening review.
5. Create a feedback page with `session review-page SESSION RENDER_ID` and import its JSON with `session feedback SESSION --data-file FILE`. Use `session revise` for edit operations or `session address-feedback` for other changes. Re-render and review candidate fixes. Record a six-check review (meaning, pacing, audio_only, cut_boundaries, captions, color) bound to the precise render SHA-256. Example review JSON is an unreviewed shape.
6. After acceptance, run `session render SESSION --full`; review that exact full render, then `session package SESSION RENDER_ID --target fcp`. The XML supports a flat, single-source timeline. In actual FCP on macOS, check import, playback, grade/LUT, captions, and mix. Record only performed checks with `session delivery-check`; use `session finish` when its gates pass. LUT, SRT, spatial masks, and final audio may need separate application.

Use `session handoff` and `session resume` when switching agents. Keep run logs and hashes. Distinguish synthetic/technical checks, human visual and listening review, FCP GUI proof, and distribution playback. For color comparisons, keep source interval and audio conditions fixed; adopt only a human-reviewed look. Apple Log LUTs already transform to Rec.709, so avoid a second FCP Camera LUT. See README.md and docs/PRESET_CATALOG.md.
