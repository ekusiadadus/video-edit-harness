# Video Edit Harness

Alpha.6 supports an opt-in production workflow for registered music, sound effects, visual assets and beat proposals. Natural editing remains the default. See the [Japanese usage guide](docs/EDITING_PATTERNS_USAGE.ja.md), [implementation plan](docs/EDITING_PATTERNS_PLAN_2026.ja.md) and [verification status](docs/EDITING_PATTERNS_IMPLEMENTATION_STATUS.ja.md). Synthetic tests do not establish human review or an FCP GUI round trip.

English | [日本語](README.ja.md)

Turn local spoken footage into coherent edits with **Codex or Claude Code**: shorter unnecessary pauses, scene-appropriate color, clear audio, matching captions and an editable Final Cut Pro timeline. You choose the story and review the result; the harness keeps source hashes, revisions and delivery evidence together.

[![English before/after demo](docs/demo/en/youtube-preview.gif)](https://github.com/ekusiadadus/video-edit-harness/releases/download/v0.1.0-alpha.4/youtube-demo-en.mp4)

**[Watch the English demo with sound: before → after → TikTok](https://github.com/ekusiadadus/video-edit-harness/releases/download/v0.1.0-alpha.4/youtube-demo-en.mp4)** · [Full English YouTube result](https://github.com/ekusiadadus/video-edit-harness/releases/download/v0.1.0-alpha.4/youtube-result-en.mp4) · [English 9:16 TikTok result](https://github.com/ekusiadadus/video-edit-harness/releases/download/v0.1.0-alpha.4/tiktok-demo-en.mp4) · [日本語デモ](README.ja.md)

This English demo uses an original illustration, synthetic English speech and English captions. The [Japanese demo](README.ja.md) has separate Japanese speech, captions and labels. Both are synthetic examples: the YouTube edit keeps both tips and TikTok keeps one complete tip. The comparison uses actual local renders; it is not a screen recording. Automated checks and these examples do not establish human listening approval, FCP GUI import or real-footage quality. [Provenance and offline reproduction](docs/demo/README.md).

The development checkout after alpha.6 adds `tracked_title`: measured labels follow observed boxes through `session track-effect --effect tracked_title --title-parameters-file label.json`. Lost/stale tracking, clipping and declared-region collision fail; overlapping zoom/split/comparison geometry is unsupported. This addition is absent from the published alpha.6 assets. See [tracking](docs/TRACKING.ja.md).

New visual sessions in the development checkout use `visual_pipeline_version: 2`: grade assembled footage before information overlays, then finish without another LUT. Existing unversioned projects retain pipeline 1. Tracking binds to the actual graded pre-effects stage; migration requires a new candidate and new tracking. See [pipeline and migration](docs/VIDEO_EFFECTS.ja.md). Published alpha.6 does not include this change.

## Ask for an edit

| Where | Regular YouTube | TikTok / Reels / Shorts |
|---|---|---|
| Codex skill | `$youtube /path/to/talk.mov` | `$tiktok /path/to/video.mov` |
| Claude standalone skill | `/youtube /path/to/talk.mov` | `/tiktok /path/to/video.mov` |
| Claude marketplace plugin | `/video-editing:youtube /path/to/talk.mov` | `/video-editing:tiktok /path/to/video.mov` |

Add your brief, for example: “Keep the explanation coherent, shorten unnecessary pauses and preserve sentence endings. Do not upload.” Use `video-editing` for general editing and color comparisons. These are agent invocations, not shell commands.

## Start here

Requires Python 3.11+, [uv](https://docs.astral.sh/uv/), FFmpeg and ffprobe. macOS or Linux; finishing in Final Cut Pro requires macOS. Install a Japanese/CJK font when burning Japanese captions on Linux.

```sh
git clone --branch v0.1.0-alpha.6 https://github.com/ekusiadadus/video-edit-harness.git
cd video-edit-harness
uv sync --locked
export VIDEO_EDIT_HARNESS_ROOT="$PWD"
uv run video-harness doctor
```

**Codex:** start a new session in the checkout; all three skills are already in `.agents/skills/`. For other projects, copy the desired skill folders to `~/.agents/skills/` and keep the harness path above available.

**Claude Code:** install the community plugin, then start a new session:

```sh
claude plugin marketplace add ekusiadadus/video-edit-harness
claude plugin install video-editing@video-edit-harness
```

For the exact `/youtube` and `/tiktok` spelling, use standalone skills instead. [Installation, verified ZIPs and version diagnosis](docs/SKILL_INSTALL.md). The GitHub release is a community distribution, not an official curated listing.

## Add a new video: storage, sessions and Final Cut Pro

Use a separate folder and harness session for each independent edit. A FCP **project** is a timeline; harness `project.json` describes one source and processing settings; a **session** holds plans, renders and reviews. [Detailed Japanese guide and prompts](README.ja.md).

Suggested layout on macOS (a convention, not an automatically generated structure):

```text
~/Movies/VideoProjects/2026-10-06-desk-tips/
├── source/IMG_1234.MOV         # unchanged camera original
├── harness/brief.json         # structured audience and story goals
├── harness/project.json      # copy of projects/talk.template.json, then configure
├── harness/session/          # this edit's durable session
├── fcp/desk-tips.fcpbundle    # library created in FCP
└── exports/                  # FCP master and distribution files
```

A reliably connected external SSD is another suitable location. Use the actual **absolute source path**, including `/Volumes/...` for external storage. Copy and check the originals before starting; retain them unchanged. Avoid temporary/Downloads locations for long-lived references, and do not manipulate the contents of `.fcpbundle` files. Moving or replacing a source after session creation affects media links and hash verification.

Set the template's `input_color` from the actual source; its `apple_log` default is not a detection result. Supported values are `apple_log` and `rec709`; do not force HLG/PQ/Apple Log 2 into either. A library name containing “Log” does not establish input color. Never apply Log conversion again to baked Rec.709 footage. You may store several clips in `source/`, but the current harness processes **one source per configuration/session**, not automatic folder-wide or B-roll assembly. Request separate processing and FCP assembly for multiple sources.

For a small local trial, checkout folders `media/<job>/`, `projects/<job>.json`, `sessions/<job>/` and `output/` are also available. Git ignores them; that does not back them up.

Start Codex in the harness checkout and ask (replace the example path):

```text
$youtube /Users/your-name/Movies/VideoProjects/2026-10-06-desk-tips/source/IMG_1234.MOV
Make a desk-tips video for first-time viewers. Keep both tips and the conclusion.
Shorten unnecessary pauses while preserving sentence endings, breaths and meaning.
Aim for 3–5 minutes, prioritizing a coherent explanation. Check the source aspect
ratio, fps and input color first; propose framing before changing aspect ratio.
Use natural whites and skin and English captions; spell the product name HHKB.
Save project.json, a structured brief.json and session/ under this job's harness/ folder.
Do not upload or post. If no sealed transcript exists, first make local color,
audio and framing previews. Let me review the plan and preview before the full
render, then give me the path to the FCP delivery package.
```

Use `$tiktok` for a vertical short or `$video-editing` for color comparisons. If cloud transcription is desired, specify the **source and permitted providers**, e.g. “Allow this file to be sent to OpenAI; deny Azure.” Store that policy against the source hash. [Transcription](docs/TRANSCRIPTION.md).

To revise, identify the existing `harness/session/`, actual render ID and whether your timestamps refer to the source or edited video: “Resume this session; preserve the previous version; keep the pause at edited 00:12–00:16 and correct HHK to HHKB. Make a revised preview. Do not upload or post.” Use a new folder/configuration/session for an independent edit with a different source. `session start` requires a directory that does not yet exist; use the existing directory to resume. Session previews, reviews and deliveries stay beneath that directory. `--brief-file` reads JSON, not Markdown; adapt [examples/workflow-brief.json](examples/workflow-brief.json), using actual transcript word IDs rather than example IDs. [Session commands](docs/WORKFLOW.ja.md).

In FCP, use a library per independent job (or a shared library for a related series), an event per shoot/episode, and a project per deliverable/version, such as `desk-tips_youtube_r01` and `desk-tips_shorts_r01`. These naming rules are suggestions. [Apple: libraries](https://support.apple.com/guide/final-cut-pro/verfdd5c590e/mac).

- **Manual FCP editing:** create a library in `fcp/` if needed, select an event, then choose File → New → Project (Command-N). Set resolution, fps and color for the actual footage and delivery; do not reuse one vertical SDR format for every source. [Apple: new project](https://support.apple.com/guide/final-cut-pro/verdb79783e/mac).
- **Harness handoff:** package the reviewed full render with `uv run video-harness session package SESSION RENDER_ID --target fcp --actor codex`, replacing the placeholders with actual values. Import `timeline.fcpxml` from the reported `session/deliveries/<ID>/` folder using File → Import → XML. XML creates projects and other objects according to its contents, so you do not need a blank timeline first. Confirm the destination library and imported event/project. Harness `project.json` is not a FCP import file. [Apple: XML transfer](https://support.apple.com/guide/final-cut-pro/verdbd66ae/mac).
- Check media links, timing, framing, grade, captions and audio against the reference render and delivery instructions. XML does not reproduce all finishing. Compare new XML imports in separate named projects to preserve existing FCP work; export the reviewed master and distribution files to `exports/`.

With “Copy to library storage,” FCP stores another media copy: budget for it and configure its destination in Library Properties. With “Leave files in place,” keep the external source paths stable. Changing storage locations does not move existing source files. Do not place files inside bundles manually. [Apple: storage locations](https://support.apple.com/guide/final-cut-pro/ver7db6ffe77/mac). Back up originals, harness history, FCP libraries and masters to another device; FCP automatic library backups contain the database, **not media**. [Apple: library backup](https://support.apple.com/guide/final-cut-pro/ver85d95b8a9/mac).

## Try without an API key

Download the v0.1.0-alpha.4 [English synthetic fixture](https://github.com/ekusiadadus/video-edit-harness/releases/download/v0.1.0-alpha.4/demo-fixture-en-v0.1.0-alpha.4.zip) and verify it against `DEMO-SHA256SUMS`. It includes measured word timestamps and a license.

```sh
uv run python scripts/prepare_demo.py --fixture /path/to/demo-fixture-en-v0.1.0-alpha.4.zip \
  --output output/my-sample
```

Then ask your agent:

```text
Use $youtube with output/my-sample/sample.mp4. Keep both desk tips and shorten
only the long pause. Use output/my-sample/project.json and the existing sealed
output/my-sample/transcript/transcript.json. Do not upload. Make a preview first.
```

Claude standalone users replace `$youtube` with `/youtube`; plugin users use `/video-editing:youtube`. The helper verifies the source hash, reseals the real timestamps for your local path and records cloud upload as denied. It runs no speech recognition. [CLI reproduction and demo build](docs/demo/README.md).

## What the harness manages

A durable session links **source → word-timed transcript → story plan → preview → feedback/revision → full render → reviewed delivery**. Resume and handoff retain those links. Long edits expose remaining audition IDs; a passing boundary review records full listening or reviewed and explicitly waived boundaries. Portrait exports have their own source/render/subtitle/font fingerprints and review, and the selected derivative travels with the final bundle. `completion.json` carries final evidence with the delivery folder.

Seven scene use cases and six styles compose independently of the platform. Indoor talk starts with `indoor_talk` + `natural`; outdoor daylight, night and backlight have different starting settings. Exposure, contrast, midtones, saturation, highlight rolloff and fixed spatial corrections remain adjustable. Compare the same source interval before choosing a look. [Preset catalog](docs/PRESET_CATALOG.md).

Cloud transcription uses **OpenAI, then Azure OpenAI**, only for the source and providers you authorize. Unknown or denied permission blocks upload, including after resume. There is no local Whisper/ASR. An API key alone grants no permission; API calls may incur charges. Existing sealed transcripts enable offline story edits; without one, local color/audio/framing previews still work. Children's or other protected footage stays local when upload is forbidden.

[Session commands and review](docs/WORKFLOW.ja.md) · [Vertical editing](docs/TIKTOK.md) · [Cloud transcription](docs/TRANSCRIPTION.md) · [Design decisions](docs/DECISIONS.md)

## Scope and verification

**Alpha:** flat speech timelines and registered multi-source visual EDL. Original video aspect is preserved; 9:16 derivatives use fit/padding by default and explicit center crop when reviewed. No automatic face identity, B-roll assembly or platform posting. Manually seeded tracking requires review. Apple Log LUTs include conversion to Rec.709; disable a second FCP Camera LUT. HDR/HLG and Apple Log 2 require another supported transform.

FCPXML exports cut timing and media links. LUTs, captions, spatial masks and the final FCP audio mix need separate application and review. XML/DTD validation, hashes, full decode and frame mapping prove technical properties; they do not prove natural speech, attractive grading, actual FCP import or platform playback. The synthetic demo and automated checks do not establish real-footage quality. [Release verification and remaining checks](docs/RELEASE_VALIDATION.md).

```sh
make test
uv run video-harness verify /path/to/final.mp4 --output output/final-check
```

[Release and checksums](https://github.com/ekusiadadus/video-edit-harness/releases/tag/v0.1.0-alpha.6) · [Contributing](CONTRIBUTING.md) · [MIT license](LICENSE). Source archive, wheel, three standalone skill ZIPs and a Claude plugin ZIP are provided; this release is not published to PyPI.

For visual retime candidates, inspect the assembled source stage and provide observed frame ranges:

```sh
uv run --no-sync video-harness session retime-source SESSION RENDER_ID
uv run --no-sync video-harness session retime SESSION RENDER_ID --request-file request.json --actor codex --note 'Emphasize the observed movement'
uv run --no-sync video-harness session render SESSION --candidate-id CANDIDATE_ID --full
```

Install the relevant optional extras and Rubber Band first; see [retime instructions](docs/RETIME.ja.md). The candidate invalidates old explicit cues/effects/guides and leaves the adopted edit unchanged. Added music is placed on the new timeline. `mix` / `video_only` FCP handoff preserves baked timing; editable retime remains unsupported. The development checkout also supports word-protected speech candidates with explicitly observed `nonspoken_intervals`; see the retime guide.

Requested video effects are described in [VIDEO_EFFECTS.ja.md](docs/VIDEO_EFFECTS.ja.md): restrained/pop presets and explicit timeline-bound events, verified in the rendered media.

Declared `composition_guides` guard supported title/zoom placement in fixed regions or framewise tracked boxes. Local OpenCV tracking and optional MediaPipe torso detection are available through `tracking track` and `tracking validate`. `session track-effect` proposes an unadopted tracking-driven zoom and tracked subject protection bound to the retained pre-effects picture; see [tracking scope and commands](docs/TRACKING.ja.md). Source-bound `retime prepare` / `retime render` now produce local ramp/hold MP4s with audio stretching and frame-remapped SRT; [scope and commands](docs/RETIME.ja.md). Visual sessions support unadopted retime candidates; finished-picture FCP handoff preserves the baked result. Editable FCP retime remains pending. Development speech retime uses mandatory transcript-word protection and observed nonspoken frames, retaining PCM before the final mix.

See the [TikTok API connection guide](docs/TIKTOK_API.ja.md) for desktop OAuth and read-only access to the authorized account profile and public videos. It does not post videos, download platform music, or retrieve trend rankings. Live connectivity requires separate OAuth and API verification.

Post-alpha.6 development supports measured Japanese/English title wrapping, protected phrases and number/unit grouping, with explicit overflow rejection. [Controls and limits](docs/VIDEO_EFFECTS.ja.md). This feature is not included in the published alpha.6 assets.

Post-alpha.6 development retains a pre-production speech assembly and exposes transcript-bound protected word frames through `session retime-source`. Speech retime candidate rendering remains pending. [Scope / 操作と制限](docs/RETIME.ja.md)


Development timing comparisons use `session compare-candidates SESSION NATURAL_RENDER RETIMED_RENDER --mode timing`: inspect independent full-length playback and explicit duration/retime changes for the same selected cuts. Default `effects` retains strict mapping equality and synchronized playback. Comparing reordered or different plans remains outside this mode.

Development retimed visual sessions retain `visual-retimed.wav` for the environment mix, alongside the speech session's retained PCM. Subsequent grading, overlays, effects and final MP4 muxing preserve fractional-frame audio endpoints with a 48 kHz movie timescale. Overlays and effects retain declared Rec.709 tags and copy their input audio. Synthetic decode/sample checks cover these paths; final AAC encoding, human listening and actual FCP playback remain separate checks. These changes are not in published alpha.6.

For development comparisons of result-first versus chronological edits, use `session compare-candidates SESSION FIRST_RENDER SECOND_RENDER --mode structure`. This explicit mode accepts different sealed plans under the same brief, source pool, color, base audio, FPS and preview conditions. It shows each ordered source range and reason, plus added/removed ranges including repeated uses, with independent full-length playback. Include a natural version without retiming. Retimed candidates retain their original cut evidence and disclose speed/hold operations separately. Selection exports remain proposals. The default `effects` and `timing` modes keep their existing stricter boundaries. See [comparison instructions](docs/RETIME.ja.md).

Import the page's downloaded selection with `session select-comparison SESSION --data-file comparison-selection.json --actor codex --note REASON`. It creates an unadopted candidate with the selected render's exact plan and project, even when the current plan has changed. The video SHA, current brief, source and selection time must match. Render that candidate, then explicitly adopt it and review the exact full output. Selecting an older render this way can restore its editing inputs; it never restores a human approval or publishes a video.
