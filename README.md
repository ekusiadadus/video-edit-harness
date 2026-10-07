# Video Edit Harness

Alpha.7 supports an opt-in production workflow for registered music, sound effects, visual assets and beat proposals. Natural editing remains the default. See the [Japanese usage guide](docs/EDITING_PATTERNS_USAGE.ja.md), [implementation plan](docs/EDITING_PATTERNS_PLAN_2026.ja.md) and [verification status](docs/EDITING_PATTERNS_IMPLEMENTATION_STATUS.ja.md). Synthetic tests do not establish human review or an FCP GUI round trip.

The development checkout adds `session motion-cuts` for reviewed cut-position proposals based on observed image motion. Supply source-frame choices, ROIs and observed nonspoken intervals; uncertain motion leaves the plan unchanged. See [usage and limits](docs/MOTION_CUTS.ja.md). The development `session transitions` command creates explicit, source-bound dissolve/push candidates with composite feedback, natural comparison, exact-render visual review and baked MP4/FCP handoff. See [usage and limits](docs/TRANSITIONS.ja.md). Real-media acceptance and FCP GUI proof remain outstanding.

The development checkout also exercises beat cuts, picture-speed ramps, zooms, trails and titles together on real dance footage. New visual retime candidates retain actual shot boundaries, allowing fresh trails across speed changes within one shot while rejecting trails across cuts. See [retime limits](docs/RETIME.ja.md) and [real-media evidence](docs/EDITING_PATTERNS_IMPLEMENTATION_STATUS.ja.md). TikTok browser login, API connection and native music/effect application are separate states; local effects are not presented as TikTok-native execution.

Development comparison pages offer shorter/original/longer effect time for smooth zoom and saturation, preserving the midpoint without changing footage or BGM speed. Undo and matched interval previews remain available. See [controls and limits](docs/COMPARISON_ADJUSTMENTS.ja.md).

Development effects comparisons also propose existing BGM gain/off corrections with undo. Gain controls use sealed source-audio evidence or explicit no-normalization; normalized music-only cases expose Off. Render the candidate fully before checking its new audio. Registered, authorized tracks and their source start can also be replaced with undo (version 5). Existing picture timing stays fixed; new-song beat alignment requires fresh analysis and review. Music changes require a full render. `session beat-effects` centers selected zoom/saturation peaks on the actual music cue’s mapped beats, with a reduced-motion alternative; it does not detect choruses or strong beats. See [beat accents](docs/BEAT_EFFECTS.ja.md) and [BGM controls](docs/COMPARISON_ADJUSTMENTS.ja.md).

English | [日本語](README.ja.md)

Turn local spoken footage into coherent edits with **Codex or Claude Code**: shorter unnecessary pauses, scene-appropriate color, clear audio, matching captions and an editable Final Cut Pro timeline. You choose the story and review the result; the harness keeps source hashes, revisions and delivery evidence together.

[![English before/after demo](docs/demo/en/youtube-preview.gif)](https://github.com/ekusiadadus/video-edit-harness/releases/download/v0.1.0-alpha.4/youtube-demo-en.mp4)

**[Watch the English demo with sound: before → after → TikTok](https://github.com/ekusiadadus/video-edit-harness/releases/download/v0.1.0-alpha.4/youtube-demo-en.mp4)** · [Full English YouTube result](https://github.com/ekusiadadus/video-edit-harness/releases/download/v0.1.0-alpha.4/youtube-result-en.mp4) · [English 9:16 TikTok result](https://github.com/ekusiadadus/video-edit-harness/releases/download/v0.1.0-alpha.4/tiktok-demo-en.mp4) · [日本語デモ](README.ja.md)

This English demo uses an original illustration, synthetic English speech and English captions. The [Japanese demo](README.ja.md) has separate Japanese speech, captions and labels. Both are synthetic examples: the YouTube edit keeps both tips and TikTok keeps one complete tip. The comparison uses actual local renders; it is not a screen recording. Automated checks and these examples do not establish human listening approval, FCP GUI import or real-footage quality. [Provenance and offline reproduction](docs/demo/README.md).

Alpha.7 adds `tracked_title`: measured labels follow observed boxes through `session track-effect --effect tracked_title --title-parameters-file label.json`. Lost/stale tracking, clipping and declared-region collision fail; overlapping zoom/split/comparison geometry is unsupported. See [tracking](docs/TRACKING.ja.md).

New visual sessions in alpha.7 use `visual_pipeline_version: 2`: grade assembled footage before information overlays, then finish without another LUT. Existing unversioned projects retain pipeline 1. Tracking binds to the actual graded pre-effects stage; migration requires a new candidate and new tracking. See [pipeline and migration](docs/VIDEO_EFFECTS.ja.md).

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
git clone --branch v0.1.0-alpha.7 https://github.com/ekusiadadus/video-edit-harness.git
cd video-edit-harness
uv sync --locked
export VIDEO_EDIT_HARNESS_ROOT="$PWD"
uv run video-harness doctor
```

In the development checkout after alpha.7, doctor reports audio/video retime support for visual and speech sessions separately from editable FCP support. TikTok diagnostics distinguish saved authorization from unexpired access and scope-specific readiness; they do not verify the remote account. Follow [the connection guide](docs/TIKTOK_API.ja.md) and keep credentials in Keychain or the environment.

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

**Alpha:** flat speech timelines and registered multi-source visual EDL. Original video aspect is preserved; 9:16 derivatives use fit/padding by default and explicit center crop when reviewed. No automatic face identity or B-roll assembly. The user uploads the delivered MP4 to the platform personally. Manually seeded tracking requires review. Apple Log LUTs include conversion to Rec.709; disable a second FCP Camera LUT. HDR/HLG and Apple Log 2 require another supported transform.

FCPXML exports cut timing and media links. Flat timeline export uses a Rec.709 project working space and a separate source format, preserving camera/log interpretation; this does not bake a color conversion into the source. LUTs, captions, spatial masks and the final FCP audio mix need separate application and review. XML/DTD validation, hashes, full decode and frame mapping prove technical properties; they do not prove natural speech, attractive grading, actual FCP import or platform playback. The synthetic demo and automated checks do not establish real-footage quality. [Release verification and remaining checks](docs/RELEASE_VALIDATION.md).

```sh
make test
uv run video-harness verify /path/to/final.mp4 --output output/final-check
```

[Release and checksums](https://github.com/ekusiadadus/video-edit-harness/releases/tag/v0.1.0-alpha.7) · [Contributing](CONTRIBUTING.md) · [MIT license](LICENSE). Source archive, wheel, three standalone skill ZIPs and a Claude plugin ZIP are provided; this release is not published to PyPI.

For visual retime candidates, inspect the assembled source stage and provide observed frame ranges:

```sh
uv run --no-sync video-harness session retime-source SESSION RENDER_ID
uv run --no-sync video-harness session retime SESSION RENDER_ID --request-file request.json --actor codex --note 'Emphasize the observed movement'
uv run --no-sync video-harness session render SESSION --candidate-id CANDIDATE_ID --full
```

Install the relevant optional extras and Rubber Band first; see [retime instructions](docs/RETIME.ja.md). Alpha.7 invalidates old explicit cues/effects/guides in the candidate and leaves the adopted edit unchanged. The development visual workflow migrates compatible settings and preserves original-frame zoom/saturation pulse values and keyword-title fade/rise by default. Video overlays also select actual output RGBA samples sealed during the original render; old timestamp-only evidence needs a fresh original render. Layer hashes, canvas and baked source/placement settings must match. Looped video migration is pending; `--timeline-settings clear` explicitly removes them. Added music is placed on the new timeline. `mix` / `video_only` FCP handoff preserves baked timing; editable retime remains unsupported. Alpha.7 also supports word-protected speech candidates with explicitly observed `nonspoken_intervals`; see the retime guide.

Requested video effects are described in [VIDEO_EFFECTS.ja.md](docs/VIDEO_EFFECTS.ja.md): restrained/pop presets and explicit timeline-bound events, verified in the rendered media.

Declared `composition_guides` guard supported title/zoom placement in fixed regions or framewise tracked boxes. Local OpenCV tracking and optional MediaPipe torso detection are available through `tracking track` and `tracking validate`. `session track-effect` proposes an unadopted tracking-driven zoom and tracked subject protection bound to the retained pre-effects picture; see [tracking scope and commands](docs/TRACKING.ja.md). Source-bound `retime prepare` / `retime render` now produce local ramp/hold MP4s with audio stretching and frame-remapped SRT; [scope and commands](docs/RETIME.ja.md). Visual sessions support unadopted retime candidates; finished-picture FCP handoff preserves the baked result. Editable FCP retime remains pending. Speech retime uses mandatory transcript-word protection and observed nonspoken frames, retaining PCM before the final mix.

See the [TikTok API connection guide](docs/TIKTOK_API.ja.md) for desktop OAuth and read-only access to the authorized account profile and public videos. It does not post videos, download platform music, or retrieve trend rankings. Live connectivity requires separate OAuth and API verification. A live Symphony UI check applied a segment effect to a stock video and downloaded the MP4; music addition, editing API integration and rights for YouTube use remain unverified. This capability demo is not a finished production or proof of API connection.

Development `native-inspect` checks a downloaded finishing MP4 locally; `session native-result` retains returned bytes and an explicit source/output receipt under the proposal. Missing or near-silent audio is flagged when music was requested. These commands preserve exact-file evidence without adopting the result or inheriting the original timeline, captions or review. [Commands and limits](docs/TIKTOK_API.ja.md).

Alpha.7 supports measured Japanese/English title wrapping, protected phrases and number/unit grouping, with explicit overflow rejection. [Controls and limits](docs/VIDEO_EFFECTS.ja.md).

Alpha.7 retains a pre-production speech assembly and exposes transcript-bound protected word frames through `session retime-source`. Speech retime candidates render with observed nonspoken intervals and transcript word protection. [Scope / 操作と制限](docs/RETIME.ja.md)


Timing comparisons use `session compare-candidates SESSION NATURAL_RENDER RETIMED_RENDER --mode timing`: inspect independent full-length playback and explicit duration/retime changes for the same selected cuts. Default `effects` retains strict mapping equality and synchronized playback. Comparing reordered or different plans remains outside this mode.

Retimed visual sessions retain `visual-retimed.wav` for the environment mix, alongside the speech session's retained PCM. Subsequent grading, overlays, effects and final MP4 muxing preserve fractional-frame audio endpoints with a 48 kHz movie timescale. Overlays and effects retain declared Rec.709 tags and copy their input audio. Synthetic decode/sample checks cover these paths; final AAC encoding, human listening and actual FCP playback remain separate checks.

For comparisons of result-first versus chronological edits, use `session compare-candidates SESSION FIRST_RENDER SECOND_RENDER --mode structure`. This explicit mode accepts different sealed plans under the same brief, source pool, color, base audio, FPS and preview conditions. It shows each ordered source range and reason, plus added/removed ranges including repeated uses, with independent full-length playback. Include a natural version without retiming. Retimed candidates retain their original cut evidence and disclose speed/hold operations separately. Selection exports remain proposals. The default `effects` and `timing` modes keep their existing stricter boundaries. See [comparison instructions](docs/RETIME.ja.md).

Import the page's downloaded selection with `session select-comparison SESSION --data-file comparison-selection.json --actor codex --note REASON`. It creates an unadopted candidate with the selected render's exact plan and project, even when the current plan has changed. The video SHA, current brief, source and selection time must match. Render that candidate, then explicitly adopt it and review the exact full output. Selecting an older render this way can restore its editing inputs; it never restores a human approval or publishes a video.

Source-bound J/L cuts use `session audio-cuts` to propose actual source pre/post audio handles while preserving picture frames. Transcript-backed speech handles rebuild captions; untranscribed visual handles require an explicit nonspoken declaration and listening review. Retime combinations and editable FCP handoff remain unsupported. [操作・レビュー条件](docs/AUDIO_CUTS.ja.md).

`motion_trail` applies a requested, bounded trail from actual past frames within one shot, with copied audio and unchanged timing. It is opt-in. [Controls and review limits](docs/VIDEO_EFFECTS.ja.md).

The development `motion-templates` catalog and `session motion-template` command expand versioned compound recipes into ordinary unadopted effect candidates. `beat_focus` combines zoom and saturation; `reveal_callout` moves from zoom to a keyword label. Reduced-motion variants, strict frame bounds and sealed recipe/render provenance retain the existing comparison and review workflow. These are local baked recipes; beat analysis, depth and native Motion/TikTok templates are separate capabilities. [操作と制約](docs/MOTION_TEMPLATES.ja.md).

Experimental `tracked_background` creates per-frame local GrabCut masks from observed tracking, with manual binary-mask corrections, to suppress the background while retaining foreground. Lost/stale masks fail; exact-render contour review is required. [Controls and limits](docs/TRACKING.ja.md). An eight-frame real-footage trial retained wall/ceiling as foreground; the agent rejected the visual result, and no human review is recorded. Review full contours and correct masks manually before use. This is not universal person matting.

The development `depth prepare/infer/correct/stabilize/validate/render` commands retain source-bound relative-depth fields, with local Small-model inference and iterative manual corrections. `session depth-layer` binds a registered same-canvas RGBA image to the full render’s retained Rec.709 graded picture, proposes an unadopted candidate, and carries depth through comparison, selection, adoption and baked delivery. Exact-render `depth_contours` review is required. Portable provenance retains field hashes and redacts private depth paths; image/model files remain external. Opt-in motion-compensated temporal candidates retain confidence and cut resets; accepted real-footage contour and temporal quality remain pending. [操作と制約](docs/DEPTH_LAYERS.ja.md).

Development portrait exports support opt-in Japanese/English measured caption wrapping through `tiktok-export --caption-layout`: preserve reviewed SRT times/manual breaks, protect specified terms and inspect the actual font. Portable portrait delivery retains redacted layout provenance. [操作と制約](docs/CAPTION_LAYOUT.ja.md).

Development editable FCP visual cues retain static size, position and opacity from a shared preview pixel model. Actual FCP display calibration and audio parity remain pending. [操作と制約](docs/FCP_OVERLAY_PLACEMENT.ja.md).

Development session renders with audio cues retain measured sample gain curves, mixer inputs and the pre-normalization mix, including verified restoration from cache. An explicit `fcp_audio_automation: "measured"` with editable handoff exports bounded dB keyframes and a separate dialogue PCM, before final normalization. Retained pre-AAC WAVs permit a common normalization scalar only after all-sample verification. Return import preserves unchanged audio automation while allowing supported visual cue revisions. FCP playback calibration and dynamic normalization remain pending. Local evidence references can contain private paths. [操作と制約](docs/AUDIO_GAIN_EVIDENCE.ja.md).

Development speech captions can use `session caption-source` and `session caption-groups --spec-file` for explicit phrase boundaries anchored to actual word IDs and occurrences. Keep negation/names/units together, inspect reading-time diagnostics, and retain exact SRT evidence through cuts, speech retime and J/L audio samples. Candidates remain unadopted until review. See [caption grouping and limits](docs/CAPTION_GROUPS.ja.md); automatic semantic understanding and device readability remain unproven.

See the [four separate before/after demo specification (Japanese)](docs/COMPARISON_DEMOS.ja.md) for regular YouTube, dance, effects, and beat-sync comparisons with sound. Four local review files have been generated and technically checked; they are not public downloads or evidence of human acceptance. The user performs the upload.

Development SFX, including loops, follows visual speed ramps with pitch-preserving audio, original-clock fades, inserted silence during freezes and resumed source PCM afterward. Music retains normal playback; ducking uses the new speech clock. Source, trim, fades and compiled mapping are bound to the candidate and gain evidence. Loop repeats and seam tapers are preserved on the original clock before stretching. Composed SFX retime and editable FCP playback remain pending; use baked mix/video_only. See [retime scope](docs/RETIME.ja.md). This is post-alpha.7 development, not a newly published release.

Development video loops repeat the selected trim after one CFR conform and preserve its actual rendered RGBA samples through sealed version-2 phase replay. Visual cue fades now apply to alpha; replay keeps baked video fades without applying them twice. Zero-fade nonloop rendering is retained. Visual loops/fades require baked mix/video_only handoff; editable FCP must reject omitted animation. See [retime and limits](docs/RETIME.ja.md). Post-alpha.7 development; full viewing/listening and FCP playback remain separate checks.

Development temporal effects retain lossless original-stage samples and replay them through a first session retime, preserving trail history, comparison playback and captured stage order through holds and skipped frames. Session verification binds original/remapped layers and picture settings; changed settings require fresh original evidence. See [retime behavior and limits](docs/RETIME.ja.md).

Development image and static-title fades also preserve original RGBA samples through first retime. Holds retain the original alpha; omissions select original frames. Source/image or generated title raster, text, placement, opacity and fade changes require a fresh original render. See [retime scope](docs/RETIME.ja.md); this is not in the published alpha.7.

Local real-dance effects reviews now include natural, restrained text/color, and brief trail/zoom/title variants, plus two separate sound-on before/after MP4s. Same-source timing and decoded PCM were verified; whole-video human viewing/listening and Content ID remain pending. [Comparison conditions](docs/COMPARISON_DEMOS.ja.md).

Development effects comparisons include per-effect strength/off controls with undo and reset. Downloaded version-2 choices apply bounded changes to the selected render's retained inputs as an unadopted candidate; unchanged choices retain version 1. Render and review the new output before adoption. Captured retime effects remain protected. [操作と制約](docs/COMPARISON_ADJUSTMENTS.ja.md).

Development `session preview-effects SESSION REVISED_RENDER` exports matched, audio-bearing excerpts of changed effects from completed full comparison renders. It retains parent SHAs and exact frame bounds; removed effects use their original interval. This is an inspection aid, with separate full-render review, rather than an interval-only rerender. [Usage](docs/COMPARISON_ADJUSTMENTS.ja.md).

Development comparison pages also expose output-frame ranges and normalized smooth-zoom positions. Version-3 selections retain exact rational frame times, bounded parameter validation, undo/reset and unadopted candidates. Interval previews include both original and revised windows. Tracked/captured clocks stay protected. [操作と制約](docs/COMPARISON_ADJUSTMENTS.ja.md).

Development `session preview-changes SESSION CANDIDATE_ID` renders a changed-effect interval before the revised full render. It reuses the sealed pre-effects picture and finished audio while retaining effect phase/history and pipeline order. The artifact is unadopted and cannot satisfy full-render review; render fully before adoption. Encoding may differ at excerpt boundaries. [Usage and limits](docs/COMPARISON_ADJUSTMENTS.ja.md).

Development `native-compare BEFORE.mp4 AFTER.mp4 --output DIR` fully decodes returned files, compares first-track PCM without resampling and reduced RGB on matching frame timestamps. It separates audio differences from visible changes; it does not prove song/effect identity, API execution or rights. See [native comparison](docs/TIKTOK_API.ja.md).

Development `session beat-effects --beat-map-file music-beats.json --cue-id MUSIC_CUE --at 4.35` accepts output-time requests without an effect JSON. It selects only a uniquely nearest mapped peak within the explicit tolerance and retains requested/selected times; missing, ambiguous and protected beats reject. [Time controls](docs/BEAT_EFFECTS.ja.md).
