# Design decisions and evidence boundaries

This alpha keeps source media immutable and stores briefs, sealed transcripts, word-anchored plans, render hashes, feedback, review, and delivery checks in a durable session. A plan revision does not silently inherit approval. Actor labels document who made a choice; they do not prove a person reviewed footage or a particular model executed. Hashes and raw logs support technical traceability but do not judge aesthetics.

## Editing and transcript

A low-volume interval is only a cut candidate. It does not establish absent speech, a safe word ending, or a coherent transition. New candidates remain disabled until explicitly selected. Story spans and omissions use actual source word IDs and times with reasons and goals. Semantic transcription and word timestamps come from separate API responses; the harness reports disagreement instead of fabricating alignment. The route is cloud OpenAI followed by Azure OpenAI when configured. The API-hosted `whisper-1` endpoint may supply word timestamps; no local Whisper model runs. API access, billing, and quality depend on the user's environment and footage. See the [OpenAI speech guide](https://developers.openai.com/api/docs/guides/speech-to-text) and [Azure OpenAI API reference](https://learn.microsoft.com/en-us/azure/foundry/openai/reference-preview-latest).

The first render is a preview. Feedback binds to a render and source ranges; addressing an item creates a candidate fix, while review of the revised render establishes whether it is resolved. The final review binds to the full-render SHA-256 and separately covers meaning, pacing, audio-only clarity, cut boundaries, captions, and color. An agent can select a plan, but human approval and listening must be recorded only when performed.

## Color, audio, and FCP

Use cases and styles compose; measurements and brightness guidance inform review rather than produce a beauty score. Fixed region corrections do not track a subject. Apple Log conversion happens before the look; avoid a second camera LUT in FCP. Irrecoverably clipped highlights cannot be restored by the grade. The harness does not infer support for Apple Log 2 or HLG. Apple's [color correction guide](https://support.apple.com/en-ca/guide/final-cut-pro/ver761ca98b/mac) and [color curves guide](https://support.apple.com/en-ca/guide/final-cut-pro/verf87ca7b62/mac) are source references for the workflow, not validation of any particular preset.

Audio is measured before two-pass normalization. The default -16 LUFS and -1.5 dBTP targets are starting choices for the project, not YouTube rules. Delivery uses H.264/Rec.709 SDR/AAC settings aligned with [YouTube's upload recommendations](https://support.google.com/youtube/answer/1722171?hl=en); platform recompression and audience playback need their own checks. Source media, FCPXML, LUT, SRT, spatial corrections, and final mix can require separate handoff steps. Existing complex FCP projects are inspected rather than automatically rebuilt; generated cut XML supports a flat, single-source timeline.

## What has been checked

Development verification included 108 passing tests and a 600-second synthetic 160×90 session. Its initial render took about 42 seconds and a subtitle rerender about 13 seconds under one local setup. These figures establish an exercised code path and one environment's timing only. They are not ProRes benchmarks, representative quality or cost figures, model accuracy measurements, or proof of FCP GUI use. Source footage, codec, resolution, cache state, CPU, and FFmpeg build can change runtime substantially.

The technical checks include media decode, source bounds, durations, frame mapping, hashes, and FCPXML/DTD validation. Actual footage needs visual inspection and listening. FCP GUI import, playback, color, subtitle, and mix fidelity require a macOS FCP check; XML validation does not substitute for it. YouTube playback after upload is a further independent check. No real 10–15 minute talk, customer footage, or platform outcome is claimed by the synthetic run.
