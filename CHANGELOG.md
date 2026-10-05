# Changelog

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
