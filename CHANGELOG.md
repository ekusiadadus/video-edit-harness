# Changelog

## v0.1.0-alpha.7 — 2026-10-06

- Added tracked readable labels, Japanese/English measured wrapping, title collision checks and visual pipeline 2 to grade footage before overlays.
- Added transcript-word-protected speech retime, observed nonspoken intervals, retained PCM and fractional-frame audio endpoint preservation.
- Added structure comparisons and exact-render selection proposals that restore the sealed edit without automatic adoption.
- Added source-bound J/L audio handles with audible-word captions and separate audio provenance; retime combinations and editable FCP remain unsupported.
- Added opt-in causal motion trails and experimental tracked GrabCut background masks with manual binary-PNG corrections and contour review. A real dance mask trial retained background walls/lights and was rejected; automatic person matting quality is not established.
- Fixed background-mask event boundaries with exact trimmed-frame concatenation; regressions cover 30 and 30000/1001 fps, interior windows and video-edge windows.
- Refreshed README, all three skills, distribution pins and current capability limits. No posting, external service activation, human acceptance or FCP GUI proof is implied. This release does not complete the full implementation plan.

## v0.1.0-alpha.6 — 2026-10-06

- Added opt-in editing patterns, licensed asset records, music/SFX mixing, beat proposals, multi-source visual EDL, immutable session candidates and comparison pages.
- Added parameterized zoom/color effects, measured title cards and real two-input comparisons; natural editing remains the default and pop presets omit the decorative cyan frame.
- Added local OpenCV/MediaPipe tracking, source-bound tracked zoom and framewise protected-region checks. Lost frames and stale source/track references fail closed.
- Added source-bound ramp/hold rendering with Rubber Band R3 audio, remapped captions, visual-session retime candidates and baked FCP handoff. Editable FCP retime and speech-session word protection remain unsupported.
- Added portable production dependencies, rights-aware FCP handoff and read-only TikTok OAuth/API tooling. Live OAuth, platform music/effects and posting are separate capabilities; no posting is performed by default.
- Updated README, three skills, installation guidance and optional dependencies. Full human listening/visual acceptance, FCP GUI round-trip and platform playback are not established by the automated suite.

## v0.1.0-alpha.5 — 2026-10-06

- Documented per-video storage, source preservation, JSON briefs, durable sessions, revision prompts and FCP library/event/project organization in both READMEs.
- Added source-linked 2026 Final Cut Pro production guidance, optional extension research and a prioritized harness implementation backlog.
- Included a sanitized record of settings applied on one Mac, with unverified viewer state and quality checks kept explicit; installing the harness does not configure FCP automatically.
- Updated software, skill/plugin and installation versions. Existing alpha.4 synthetic demo assets remain linked and unchanged.
- Explicitly excluded local work, media, session, cache and build directories from source distributions.
- Documentation release: no new multi-source, HDR/Apple Log 2, tracking or FCP finishing-fidelity implementation.

## v0.1.0-alpha.4 — 2026-10-06

- Repair overview joins with one frame/sample-aligned encode, complete comparison sentences and visible pause captions. Preserve complete original PCM speech extents when ASR onsets are late.
- Added the standalone `/youtube` skill for regular YouTube videos, with source-bound pacing, scene-appropriate grading and full-render review.
- Included YouTube in the Claude plugin, portable skill ZIPs and English/Japanese installation guides.
- Kept vertical Shorts routed to the existing TikTok workflow and preserved source upload restrictions.
- Enforced source/provider-bound cloud permission through projects, sessions and low-level API calls.
- Added version/tool/font/command diagnosis, paginated junction auditions and recorded listening coverage.
- Linked reviewed portrait derivatives to exact renders, subtitles and fonts; added portable completion evidence.
- Restricted release manifests and checksums to current artifacts.
- Rebuilt a reproducible offline synthetic fixture, smooth Japanese AI voice, matched before/after overview and actual YouTube/TikTok outputs.
- Reorganized English/Japanese READMEs around invocations, one quickstart and offline onboarding.
- Prepared separate English and Japanese synthetic demo media, captions, labels, fixtures and README links; publication and human/FCP review remain separate release checks.

## v0.1.0-alpha.3 — 2026-10-05

- Published Claude Code plugin manifest and community marketplace entry alongside the portable Codex/Claude skill.
- Added English/Japanese skill installation and invocation guides.
- Made local-only grading explicit when cloud upload is forbidden or a transcript is unavailable.
- Added a portable Claude plugin ZIP and verified privacy-safe release contents.
- Added the standalone `/tiktok` skill and local 1080×1920 fit/crop delivery with optional reviewed subtitle burn-in.


## v0.1.0-alpha.2 — 2026-10-05

- English and Japanese READMEs with linked navigation and real screen-recording guides.
- Updated synthetic source/edit demo with OpenAI-generated Japanese `marin` speech, a freshly transcribed word-anchored edit, and explicit AI voice disclosure.
- Fixed CLI preview/render failing because a branch-local import shadowed `build_lut`.
- Included demo documentation and preview assets in source archives.

The README walkthrough is composed from actual synthetic source and render files; it is not a Codex screen recording or an FCP GUI test.

## v0.1.0-alpha.1 — 2026-10-05

First public alpha of the harness and portable `video-editing` skill.

- Durable editing sessions with briefs, word-anchored ordered chapters, immutable transcript revisions, feedback, review, resume and handoff.
- OpenAI-first, Azure-second cloud transcription; no local ASR.
- Seven grading use cases and six composable styles, Apple Log/Rec.709 input handling, LUTs and fixed region corrections.
- Separate verified video, PCM and mix caches; preserved internal audio timestamp gaps.
- Preview/full video, audio-only export, subtitles, bounded inspection assets and FCPXML packages.
- Flat single-source FCPXML import, explicit perceptual/FCP delivery gates and operational comparison.
- Source and wheel distributions, portable preset data, skill archive, checksums and CI.

Alpha limits: POSIX systems; GUI finishing requires macOS/Final Cut Pro. Complex timelines, multiple media/B-roll, tracking, automatic aesthetic approval and actual model-quality comparisons are outside this release. Synthetic tests do not establish real-footage quality or GUI fidelity.
