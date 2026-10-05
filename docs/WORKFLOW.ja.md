# 日本語で使う

Video Edit Harnessは、Codex／Claude Codeで発話を読んで編集し、色・音声・字幕・FCPXMLを検証しながら仕上げるアルファ版です。元動画、文字起こし、判断、修正版を保持します。ローカルWhisperは実行しません。

Python 3.11以上、uv、FFmpeg／ffprobeを用意し、[README](../README.md)のタグ付きcloneと`uv sync --locked`で導入してください。リポジトリ内のSkillは`.agents/skills/video-editing`、Claude Code側は同じSkillへの相対symlinkです。単体Skill ZIPもGitHub Releaseにあります。別の場所から使う場合は`VIDEO_EDIT_HARNESS_ROOT`にハーネスの場所を指定します。

1. `projects/talk.template.json`を自分用にコピーし、素材の絶対パス・入力色・プレビュー範囲を設定する。
2. `session start PROJECT SESSION --brief-file BRIEF`で視聴者・目標尺・残す目的を保存する。
3. その素材のクラウド送信が依頼範囲に含まれる場合、下記のcloud-policyで許可を保存してから `uv run --extra transcription-cloud video-harness session transcribe SESSION`。OpenAI→Azureの順。APIキーは環境変数へ設定し、JSONに書かない。
4. `session context SESSION --words`で実際の単語IDを読み、章・発話範囲・保持／省略理由を計画する。`examples/workflow*.json`は書式例であり、このまま実素材へ適用しない。
5. `session plan`→`session approve --actor codex --note REASON`→`session render`でプレビューを作る。人間が行った選択だけ`--actor human`にする。
6. 動画、音声のみ、字幕を確認。`session inspect SESSION RENDER_ID --start 432 --duration 8`で必要区間の接触シート・波形・試聴音声を出す。`session review-page`の指摘ファイルを`session feedback`へ戻す。
7. 指摘を`session revise`や色／音声／字幕の変更に反映し、新版のレビューで解消を確認する。文字起こし修正は`session correct-transcript`で単語IDと時刻を保持する。
8. 全解像度の`session render --full`を確認し、`session package --target fcp`で受け渡す。FCPでLUT、SRT、マスク、音声を適用・確認。実際の確認を`session delivery-check`へ記録し、`session finish`する。

中断・交代では`session status`、`session handoff`、`session resume --actor claude_code`を使います。全構文は`uv run video-harness session --help`にあります。API課金、試聴、FCP GUIの実際の結果を、合成テストや自動検証と分けて扱います。Windows、複雑なFCPタイムライン、複数素材／B-roll、被写体追跡は今回の対応範囲外です。

## 許可・長尺・縦動画・完了証拠

開始前に `uv run video-harness doctor` で実行系とスキル、パス、必要なコマンドを確認します。クラウド送信について既存のユーザー指示を `session cloud-policy SESSION allow --providers openai azure --actor codex --note BASIS` または `deny` で保存してから文字起こしを呼びます。実際の許可の根拠を記載し、素材SHAや送信先が変わらない限り許可を毎回聞き直しません。不明・禁止なら送信を止め、再開でも保持します。[設定詳細](TRANSCRIPTION.md)。

編集点の試聴は `session audition-junctions SESSION RENDER_ID --offset 0 --limit 24`、次は `--offset 24` と進めます。`--ids` で指定もできます。生成音声の一覧は総数・残りIDを表示しますが、生成しただけで「試聴済み」にはしません。24件を超える編集点に合格レビューを付けるには、同じ動画SHAを持つ `junction_coverage` に全編試聴のメモ、または確認済みIDと省略理由を記録します。

```json
{
  "render_sha256": "ACTUAL_VIDEO_SHA256",
  "checks": ["six actual check objects; see examples/workflow-review.json"],
  "junction_coverage": {
    "render_sha256": "ACTUAL_VIDEO_SHA256",
    "mode": "selected",
    "reviewed_ids": ["ACTUAL_SEQUENCE_ID"],
    "waived": [{"id": "ANOTHER_SEQUENCE_ID", "reason": "Actual reason for omission"}],
    "note": "Actual listening scope"
  }
}
```

これは構造の抜粋です。checks配列は実際の6項目オブジェクトに替え、IDは計画から取得してください。全編を聞いた場合は `mode: full_listening` と実際のメモを使います。確認を全件省略したまま合格にはできません。

縦動画はエクスポート後に `session register-vertical SESSION RENDER_ID RESULT_JSON` で関連付け、`session review-vertical SESSION DERIVATIVE_ID --data-file REPORT_JSON` に画角・字幕・音声・ローカル再生の実際の結果を記録します。選択した縦版を `session package SESSION RENDER_ID --target mp4 --derivative-id ID` で含めます。主動画のレビューだけで縦動画を合格にしません。投稿先での再生確認は別です。

finish後、納品フォルダの `completion.json` と `evidence/` に確認範囲と完了結果が保存されます。元の `delivery.json` は梱包時のスナップショットのままです。別マシンへ移したフォルダは `video_harness.delivery.verify_completion(folder)` でファイルと記録の整合を確認できます。署名付き証明ではありません。合成の `synthetic_complete` は人の試聴や実際のFCP確認の代わりにはなりません。
