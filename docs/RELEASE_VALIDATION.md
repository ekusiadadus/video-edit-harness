# Alpha.4 verification / 検証範囲

The implementation candidate is version `0.1.0a4`; the proposed release tag is `v0.1.0-alpha.4`. A candidate or draft release is not a completed public release. Check the GitHub release page and CI for the current publication state.

## Verified locally

- 133 automated tests passed on macOS/Python 3.11, covering source/provider upload gates, retained transcript timing, session revisions, portrait binding/tamper rejection, known PCM speech-boundary preservation, 26-boundary pagination, render-bound coverage, moved delivery verification, completion-field contradictions and conservative process recovery when `ps` is unavailable.
- The wheel installed into an isolated virtual environment outside the checkout; CLI, session commands, preset data, LUT generation and workspace paths passed smoke checks.
- Three standalone skill formats passed validation. Claude's marketplace manifest passed its local validator. The release inventory includes only the named current artifacts; unrelated old ZIPs are excluded.
- A separate 608.33-second, 1280×720/30 fps repeated synthetic fixture retained 2,050 tokens in 100 spans. The full render took 170.63 seconds in this environment, produced 492.03 seconds, and resumed with the same output hash. Its 99 boundaries exposed 24 generated auditions and 75 remaining IDs. Audio repetition used an exact PCM sample/frame grid; word timing was deterministically replayed from the measured short fixture, not newly transcribed. A naive AAC loop with duration drift was rejected before the measured run. This is a synthetic scale check, not natural-talk, ProRes or human-listening proof.
- A fresh fixture copy prepared successfully from the strict public ZIP inventory. Its source hash matches measured timing and provenance, and cloud upload stays denied.
- Real local CLI renders retained 41 tokens/both tips for YouTube and 17 tokens/one complete tip for TikTok. The derivative uses fit/padding, matching captions and font fingerprints. Both actual MP4 integration bundles reached **synthetic_complete** and passed portable verification. This is a fixture workflow result, not human approval.
- Separate English/Japanese speech, captions, illustration text and presentation labels were built. Language mismatches fail before generating outputs. English timing was re-measured per original sentence WAV after whole-source timing omitted two zero-duration words; exact PCM offsets map 30 measured words back to the unchanged input. The Japanese fixture retains 41 measured tokens. Both language variants passed full decode/format checks.
- The repaired Japanese sound-enabled overview is 34.93 seconds (English 36.4 seconds); the YouTube result is 10.47 seconds and the portrait result 4.8 seconds. Full decode, dimensions, audio, 30 fps, square pixels and BT.709 checks passed. Frames were inspected for title clipping and caption overlap and corrected. Overview concatenation now decodes and encodes one stream with zero-based frame/sample timing; strict packet DTS and full-frame regression checks passed. Before/after comparisons retain complete sentences and explicitly label the intentional pause. Actual source and output hashes are in the release's demo manifest/checksums.

## Agent execution

**Codex CLI 0.160.0:** the real model loaded the local `youtube` skill, read actual fixture word IDs, planned both tips, produced an initial preview, revised the first span by +0.20 seconds, approved as `codex`, created another preview and a full render, and preserved handoff/resume continuity. All 41 tokens remain. Plan/video hashes changed. Frame alignment produced a +0.2333-second rendered difference. It did not claim human listening or finish. The first attempt exposed a sandbox denial of `ps`; the harness was corrected to tolerate unavailable process identity while preserving conservative recovery, and the same session resumed successfully.

**Claude Code 2.1.272:** local skill discovery and manifest validation succeeded. Real `/tiktok` model execution was attempted but OAuth had expired and could not refresh. No model turn completed; a successful Claude editing journey is **not verified**. Re-login and repeat the fixture workflow before claiming it.

## Still requires direct evidence

- Human listening to the demo and real 10–15-minute indoor speech: word endings, breath, pacing, naturalness and audio-only understanding.
- Real full-resolution talk performance. Earlier 600-second 160×90 synthetic measurements were development checks; they are not ProRes or practical indoor-talk proof.
- Actual Final Cut Pro GUI import/playback/LUT/caption/mix finishing. The current computer-use surface lists FCP but does not permit selecting it (`Invalid app`); XML/DTD tests do not replace GUI proof.
- Actual YouTube/TikTok destination/device playback. No platform post or protected-media upload was performed.
- Fresh installs from the eventual public tag and re-downloaded assets after publication. Candidate-local archive checks do not establish public URL availability.

The fourth stage of the implementation plan remains an acceptance/publication gate until these applicable checks are completed. The first three stages and automated correctness fixes can be reviewed in the candidate without implying those external checks have passed.

Raw local evidence is kept in ignored `output/implementation-alpha4/`: runtime/distribution tests, integration counterexamples and regressions, agent event logs, render manifests, portable bundles, frame inspections, `long-fixture/report.json` with resource logs and wheel build logs. These raw agent logs are not release assets; public distribution is explicitly enumerated and contains no children's footage, personal source media or credentials.

**日本語：** 実装・配布・合成fixtureの検証と、人の試聴・実写長尺・Claude実行・FCP GUI・投稿先確認を分けています。認証や画面操作の制約で未実施の確認を合格扱いにはしません。公開前に残る受け入れ確認は上記のとおりです。
