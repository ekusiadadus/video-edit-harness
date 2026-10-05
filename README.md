# Video Edit Harness

A local, reviewable workflow for spoken-video editing, color comparison, audio normalization, subtitles, and Final Cut Pro XML handoff. A session keeps its brief, transcript, word-anchored edit plan, renders, timestamped feedback, and delivery checks together. Source media and prior revisions are retained.

This is an **alpha** release. It runs on macOS or Linux with POSIX tools. Final Cut Pro (FCP) GUI import and review require macOS and an installed copy of FCP. FCPXML validation alone does not prove that FCP opened or played a project.

## Install

Requirements: Python 3.11+, [uv](https://docs.astral.sh/uv/), `ffmpeg`, and `ffprobe` on `PATH`. Cloud transcription additionally needs provider credentials and authorization to upload the specific source. No local Whisper model is installed or run.

```sh
git clone --branch v0.1.0-alpha.1 https://github.com/ekusiadadus/video-edit-harness.git
cd video-edit-harness
uv sync --locked
uv run video-harness --help
uv run video-harness session --help
```

The [release](https://github.com/ekusiadadus/video-edit-harness/releases/tag/v0.1.0-alpha.1) includes a wheel, source archive and a separate skill ZIP with SHA256SUMS. The wheel includes presets; when used outside this checkout, outputs default to the current working directory. PyPI publication is not part of this release.

To use the included `video-editing` skill in a project, copy `.agents/skills/video-editing` into that project's `.agents/skills/`. Claude Code can use the same directory through `.claude/skills/video-editing` (a relative symlink or copy) and `CLAUDE.md`. Alternatively copy the skill into `~/.agents/skills/video-editing` or `~/.claude/skills/video-editing`. Set `VIDEO_EDIT_HARNESS_ROOT` to this checkout when invoking it outside the checkout. Pin updates to a reviewed tag. The skill's instructions do not authorize any upload or publication by themselves.

See the [Japanese workflow](docs/WORKFLOW.ja.md) for a shorter guide. Skill directory conventions follow the [Codex skills documentation](https://developers.openai.com/codex/skills/) and [Claude Code skills documentation](https://code.claude.com/docs/en/skills).

For a personal skill installation, copy the `video-editing/` directory extracted from the skill ZIP into `~/.agents/skills/` (Codex) or `~/.claude/skills/` (Claude Code), then point it at your checkout:

```sh
export VIDEO_EDIT_HARNESS_ROOT="/absolute/path/to/video-edit-harness"
```

The Python wheel can also be installed into a virtual environment using `uv pip install /path/to/video_edit_harness-0.1.0a1-py3-none-any.whl`; invoke `video-harness` from that environment. The standalone skill requires the checkout for templates and agent instructions.

## Spoken-video session

Copy the project template and set `source` to the **actual, absolute path** of your footage. Set `input_color` to `rec709` or `apple_log` based on that footage; verify the audio track and preview interval. Do not put credentials in JSON. The template's paths and example word IDs are placeholders.

```sh
cp projects/talk.template.json projects/my-talk.json
# Edit projects/my-talk.json: source, input_color, preview interval, and editorial brief.
uv run video-harness session start projects/my-talk.json output/my-session \
  --brief-file examples/workflow-brief.json --actor codex
uv run video-harness session status output/my-session --deep
```

Once the source upload is authorized, set `OPENAI_API_KEY` and transcribe. Automatic routing tries OpenAI, then Azure OpenAI when configured. Azure uses `AZURE_OPENAI_API_KEY`, `AZURE_OPENAI_ENDPOINT`, `AZURE_OPENAI_TRANSCRIPTION_DEPLOYMENT`, and `AZURE_OPENAI_TIMESTAMP_DEPLOYMENT`; `AZURE_OPENAI_API_VERSION` is optional. Transcription incurs API charges. Semantic text and word timestamps come from separate API responses; inspect mismatch warnings rather than inventing alignment. An existing sealed transcript can be attached with `session transcript SESSION TRANSCRIPT_JSON`.

```sh
uv run --extra transcription-cloud video-harness session transcribe output/my-session
uv run video-harness session context output/my-session --words
```

Use the returned word IDs and times to write a story spec with ordered chapter spans. Give every omission its exact word IDs, reason, and goal IDs. `examples/workflow-story.json` illustrates the **JSON shape only**; its IDs do not refer to your footage. The same applies to the brief, revision, and review examples. Check word endings, breathing, emphasis, topic changes, and whether the story makes sense with audio alone.

```sh
uv run video-harness session plan output/my-session --spec-file my-story.json --actor codex
uv run video-harness session approve output/my-session --actor codex --note 'Selected the reviewed plan'
uv run video-harness session render output/my-session
uv run video-harness session status output/my-session
```

`approve` records the named actor's selection. Use `--actor human` only for an actual human decision; agent selection is not human approval. The first render is a preview. Review its video, audio-only output, subtitles, and frame mapping. For a bounded excerpt, `session inspect SESSION RENDER_ID --start 432 --duration 8` creates filmstrip, waveform, listening audio, and source-word context. Generated images and waveforms cannot establish listening quality.

Create a timestamped feedback page with `session review-page SESSION RENDER_ID`, then import its saved JSON using `session feedback SESSION --data-file FILE`. For edit changes, use `session revise SESSION --operations-file FILE --feedback-id ID --actor codex --note REASON`; for color, audio, or caption changes, use `session address-feedback SESSION ID --actor codex --note REASON`. These record candidate fixes; review a new render to resolve feedback. The review report must bind to the exact render SHA-256 and cover meaning, pacing, audio-only clarity, cut boundaries, captions, and color. `examples/workflow-review.json` is an unreviewed shape, not a passing report.

After the accepted preview, render and review the full version, then package for FCP:

```sh
uv run video-harness session render output/my-session --full
uv run video-harness session package output/my-session RENDER_ID --target fcp
# In FCP on macOS, import and inspect the actual package.
uv run video-harness session delivery-check output/my-session DELIVERY_ID fcp_import pass gui \
  --actor human --note 'Imported and checked source links in FCP'
uv run video-harness session finish output/my-session DELIVERY_ID --actor human
```

The package's FCPXML covers a flat, single-source timeline. Apply and verify its LUT, SRT subtitles, spatial masks, and final audio separately as needed. Record actual GUI import, playback, grade, captions, and mix with `delivery-check` before `finish`; do not record unperformed checks. A returned flat XML can be imported as a new plan with `session import-fcp`. Complex FCP timelines are outside this contract. `session handoff` and `session resume` support work across agents while preserving the session history.

## Color, audio, and checks

The seven use cases in `use_cases/` compose with six styles in `styles/`. `indoor_talk` + `natural` is the reference for spoken indoor footage. Use `video-harness resolve PROJECT` to inspect applied settings, `preview` to compare the same source interval, `review` to record a human assessment, and `adopt` only for a reviewed candidate. See [preset guidance](docs/PRESET_CATALOG.md). Static region corrections do not track faces. Apple Log LUTs include a Log-to-Rec.709 transform; disable FCP Camera LUT when using them. HDR/HLG and Apple Log 2 need another supported transform. The initial audio targets, -16 LUFS and -1.5 dBTP, are project choices, not platform requirements.

```sh
make doctor
make test
uv run video-harness resolve projects/my-talk.json
uv run video-harness verify /path/to/final.mp4 --output output/final-check
```

Technical verification includes hashes, full decode, track and duration checks, rational frame mapping, and FCPXML/DTD checks. It does not replace visual review, listening, FCP GUI import, or playback on a distribution platform. Earlier development evidence comprised **108 passing tests** and a **600-second synthetic 160×90** session (initial render about 42 seconds, subtitle rerender about 13 seconds). Those figures are one environment's development results, not ProRes performance, model accuracy, real-footage quality, or FCP GUI proof. Reproduce measurements under your own conditions.

Design rationale and evidence boundaries: [decisions](docs/DECISIONS.md). Licensed under MIT; see [LICENSE](LICENSE).
