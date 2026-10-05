# Cloud transcription / クラウド文字起こし

OpenAI first, Azure OpenAI second. No local Whisper/ASR is installed or started. API `whisper-1` can supply word timestamps; that is a cloud request, not a local model. The semantic transcript and timing transcript may differ: read the mismatch warnings and correct actual word spelling without inventing alignment.

Record the already established source-specific decision before calling transcription:

```sh
uv run video-harness session cloud-policy output/my-session allow \
  --providers openai azure --actor codex \
  --note 'User authorized this source for these two cloud providers'
uv run --extra transcription-cloud video-harness session transcribe output/my-session
```

Use the true actor and authorization basis; do not copy the example note as evidence. `allow` is bound to the source SHA and provider list. `deny` and `unknown` block requests before upload; resume retains the policy. To prohibit upload:

```sh
uv run video-harness session cloud-policy output/my-session deny \
  --actor codex --note 'User instructed no uploads for this source'
```

The project may also contain `cloud_permission` with `source_sha256`, `policy`, `providers` and `basis` before starting a session. Low-level transcription APIs enforce the same permission. For direct `transcribe PROJECT`, record it in that project's JSON. A new source hash requires its own permission. Keys in the environment do not authorize a request.

Set `OPENAI_API_KEY` in the agent's environment. Azure fallback requires `AZURE_OPENAI_API_KEY`, `AZURE_OPENAI_ENDPOINT`, `AZURE_OPENAI_TRANSCRIPTION_DEPLOYMENT` and `AZURE_OPENAI_TIMESTAMP_DEPLOYMENT`; `AZURE_OPENAI_API_VERSION` is optional. Do not put values in project files, prompts, logs or Git. `doctor` reports only configuration booleans. Routing skips providers that are not authorized; if Azure alone is permitted, OpenAI is not contacted. Calls may incur API charges.

An existing sealed source-bound transcript can be attached without upload:

```sh
uv run video-harness session transcript output/my-session /path/to/transcript.json
```

**日本語：** 許可は実際のユーザー指示に基づき、素材のSHAと送信先を指定して一度保存します。再開時も禁止を保持します。同じ許可済み素材を使うたびに再確認する必要はありません。例文を許可の証拠として流用しないでください。送信禁止の素材は既存の封印済み文字起こしを使い、なければ色・音声・画角のローカル処理まで進めます。単語時刻の捏造やローカルWhisper実行は行いません。
