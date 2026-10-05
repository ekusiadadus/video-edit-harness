# Changelog

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
