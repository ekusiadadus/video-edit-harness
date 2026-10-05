# Public demo / 公開デモ

[Watch the sound-enabled overview](https://github.com/ekusiadadus/video-edit-harness/releases/download/v0.1.0-alpha.4/youtube-demo.mp4) · [YouTube result](https://github.com/ekusiadadus/video-edit-harness/releases/download/v0.1.0-alpha.4/youtube-result.mp4) · [TikTok result](https://github.com/ekusiadadus/video-edit-harness/releases/download/v0.1.0-alpha.4/tiktok-demo.mp4)

The overview shows a brief promise, a matched before/after excerpt, two example requests, the actual portrait result and the output types. English labels serve both READMEs; the underlying Japanese speech says:

> 机を片付けるコツは、使うものだけを戻すことです。よく使うものを手前に置くと、次の作業を始めやすくなります。

“Put back only what you use. Keeping frequent-use items within reach makes the next task easier to start.” The input has a two-second inserted pause between the two complete sentences. YouTube retains all 41 API-timed tokens and shortens the pause; TikTok retains the complete first tip (17 tokens). Their final source ranges come from the real word timing and frame mapping. Both comparison sides use a -18 LUFS normalization target; this is a project choice. Cuts shorten the gap by approximately 1.97 seconds; the full edit also removes the unused ending tail.

## Source and evidence

- Original desk illustration drawn specifically for this fixture, no people or personal footage.
- Japanese voice generated through OpenAI `gpt-4o-mini-tts`, built-in `marin`, with smooth, calm narration instructions.
- Word timing measured through OpenAI API transcription on this explicitly authorized synthetic sample. Cloud timing may use `whisper-1`; no local ASR runs.
- Input video SHA-256: `ec53da5b25575d541396be276c6307c5c2b9ef03dc1ce1b8f880d1390ae12d6b`.
- Public ZIP contains exactly `sample.mp4`, `timing.json`, `provenance.json`, `LICENSE`. It includes no API responses with private paths or credentials.
- Fixture and public graphics are distributed under the repository's MIT license. AI voice is disclosed; no impersonated speaker or custom voice.

The overview is composed from actual input/edit files and presentation cards. Its command card is labeled as example invocations; it is **not** a Codex/Claude screen recording or FCP GUI proof. Technical checks cover full decode, audio, dimensions, 30 fps, square pixels and BT.709 tags. Human listening, aesthetic acceptance, FCP GUI and destination-platform playback remain separate checks. The fixture is a short offline onboarding example, not a 10–15-minute real-talk benchmark.

## Reproduce from a clean clone, without API keys

Prepare the pinned checkout using the [installation guide](../SKILL_INSTALL.md). Download `demo-fixture-v0.1.0-alpha.4.zip` and `DEMO-SHA256SUMS` from the release. Verify the checksum before extracting; it must match the published asset. Run from the checkout:

```sh
uv run python scripts/prepare_demo.py --fixture /path/to/demo-fixture-v0.1.0-alpha.4.zip \
  --output output/demo-sample
uv run python scripts/render_demo_sample.py --sample output/demo-sample \
  --session output/demo-youtube --mode youtube
uv run python scripts/render_demo_sample.py --sample output/demo-sample \
  --session output/demo-tiktok --mode tiktok
uv run python scripts/build_platform_demos.py --sample output/demo-sample \
  --youtube-session output/demo-youtube --tiktok-session output/demo-tiktok \
  --out output/demo-presentation --docs-output output/demo-images
```

Alternatively omit the two session arguments: the presentation builder creates both sessions itself. No ignored author-side source path is required. Existing output folders are never removed or reused. `--font /path/to/CJK-font.ttc` selects a local font; otherwise the builder detects Hiragino on macOS or Noto Sans CJK on Linux. Install a CJK font if neither exists. Encoded byte hashes depend on FFmpeg and fonts; reproduction checks source identity and behavior, not bit-identical output across machines.

The prepare step verifies a strict ZIP inventory and both provenance/timing source hashes, then reseals the measured timing for your path. Its project explicitly denies cloud upload. Rendering records `automation` selection and `not_human_reviewed`; generation never invents a passing human review. The portrait result uses the production default fit/padding: it preserves every part of the source illustration and puts captions below it. Center crop remains an explicit, separately reviewed choice.

For actual agent invocation, follow the README sample prompt instead of the deterministic renderer. Start with a preview and inspect the outputs before requesting a full render or delivery.

**日本語：** 公開サンプルと実測単語時刻だけで再現できます。APIキーは不要で、送信禁止を保存します。READMEでは小さなGIFを一つだけ表示し、音声付きMP4・YouTube全編・TikTok結果にリンクします。子供の映像やDownloadsの個人素材は含みません。人による試聴、FCP取り込み、投稿先の確認を済ませたという表示はしません。

Older alpha.2 synthetic walkthrough assets (`preview.gif`, `poster.png`) remain for historical references; they are not the current README hero.
