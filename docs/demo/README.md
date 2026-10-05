# Public demos / 公開デモ

The two versions use separate speech, captions, illustration text and presentation cards. English is not a relabelled Japanese recording. Each README shows only its matching preview.

| Language | Overview with sound | YouTube edit | TikTok edit |
| --- | --- | --- | --- |
| English | [Overview](https://github.com/ekusiadadus/video-edit-harness/releases/download/v0.1.0-alpha.4/youtube-demo-en.mp4) | [Landscape result](https://github.com/ekusiadadus/video-edit-harness/releases/download/v0.1.0-alpha.4/youtube-result-en.mp4) | [Portrait result](https://github.com/ekusiadadus/video-edit-harness/releases/download/v0.1.0-alpha.4/tiktok-demo-en.mp4) |
| 日本語 | [音声付き概要](https://github.com/ekusiadadus/video-edit-harness/releases/download/v0.1.0-alpha.4/youtube-demo-ja.mp4) | [横長の編集結果](https://github.com/ekusiadadus/video-edit-harness/releases/download/v0.1.0-alpha.4/youtube-result-ja.mp4) | [縦長の編集結果](https://github.com/ekusiadadus/video-edit-harness/releases/download/v0.1.0-alpha.4/tiktok-demo-ja.mp4) |

These alpha.4 assets remain a draft until the [release gates](../RELEASE_VALIDATION.md) pass. Download URLs become public when that release is published.

Both overviews show the same sequence: promise → complete before/after sentences → example commands → portrait result → output types. YouTube retains both complete tips and shortens the long pause. TikTok keeps one complete tip, with captions below the preserved landscape illustration. Before/after audio uses the same -18 LUFS normalization target. Sentence anchors and comparison ranges come from each language's own measured timing and frame mapping; token counts and durations are not copied across languages.

English script:

> The trick to a tidy desk is to put back only what you use. Keep the things you use most within reach, so the next task is easier to start.

日本語の音声：

> 机を片付けるコツは、使うものだけを戻すことです。よく使うものを手前に置くと、次の作業を始めやすくなります。

## Source and evidence

- Original desk illustrations; no people, children's videos or private Downloads footage.
- Separate English/Japanese AI speech generated with OpenAI `gpt-4o-mini-tts`, built-in `marin`, smooth conversational instructions. No real speaker recording or impersonation.
- English timing was re-measured per original sentence WAV to recover zero-duration words omitted by whole-source timing, then mapped with exact PCM concatenation offsets. These are API-measured times, not guessed alignment.
- Word timing measured through the OpenAI API on explicitly authorized generated media. Cloud `whisper-1` is permitted; no local ASR runs.
- Each `demo-fixture-{en,ja}-v0.1.0-alpha.4.zip` contains exactly `sample.mp4`, `timing.json`, `provenance.json`, `LICENSE`. Source SHA and language are verified before use.
- `DEMO-MANIFEST.json` records separate source identities, languages, retained tokens, comparison ranges, full-decode checks and final output hashes. `DEMO-SHA256SUMS` covers the exact public inventory, including separate SRT captions.
- MIT code/illustrations and disclosed synthetic AI voice. API raw responses, credentials and private paths are excluded.

The command cards are **examples**, not Codex/Claude screen recordings or FCP GUI proof. Technical checks cover full decode, audio, dimensions, 30 fps, square pixels and BT.709 tags. Human listening, aesthetic acceptance, FCP GUI and platform playback remain separate checks. These short fixtures are offline onboarding examples, not real 10–15-minute talk benchmarks.

## Reproduce without API keys

Follow the [installation guide](../SKILL_INSTALL.md), download the matching fixture and verify it against `DEMO-SHA256SUMS`. English example:

```sh
uv run python scripts/prepare_demo.py --fixture /path/to/demo-fixture-en-v0.1.0-alpha.4.zip \
  --output output/demo-sample-en
uv run python scripts/build_platform_demos.py --sample output/demo-sample-en \
  --language en --out output/demo-presentation-en --docs-output output/demo-images-en
```

日本語版は `demo-fixture-ja-v0.1.0-alpha.4.zip` と `--language ja` を使い、出力先も別の新しいフォルダにしてください。音声と実測文字起こしの言語が異なる場合は、生成を開始せずエラーになります。準備後のプロジェクトはクラウド送信を禁止し、再生成にAPIキーは不要です。

To reuse existing sessions, add `--youtube-session PATH --tiktok-session PATH` after rendering with `scripts/render_demo_sample.py`. Existing output directories are never replaced. Use `--font /path/to/font.ttc` to select a local font; Japanese needs Hiragino or Noto Sans CJK. Encoded hashes vary with FFmpeg/fonts; source identity and behavior are the portable checks. Automated fixture selection is recorded as `automation` / `not_human_reviewed`.

Older unlocalised graphics remain historical references; `en/` and `ja/` contain the current README previews.

The repaired overview uses one continuous H.264/AAC encode on an exact 30 fps / 48 kHz grid. It shows complete sentences instead of starting midway through speech. Captions identify the intentional source pause explicitly, so the static illustration is not mistaken for stalled playback. The Japanese overview is 33.8 seconds; English is 35.2 seconds.
