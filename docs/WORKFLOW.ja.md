# 日本語で使う

Video Edit Harnessは、Codex／Claude Codeで発話を読んで編集し、色・音声・字幕・FCPXMLを検証しながら仕上げるアルファ版です。元動画、文字起こし、判断、修正版を保持します。ローカルWhisperは実行しません。

Python 3.11以上、uv、FFmpeg／ffprobeを用意し、[README](../README.md)のタグ付きcloneと`uv sync --locked`で導入してください。リポジトリ内のSkillは`.agents/skills/video-editing`、Claude Code側は同じSkillへの相対symlinkです。単体Skill ZIPもGitHub Releaseにあります。別の場所から使う場合は`VIDEO_EDIT_HARNESS_ROOT`にハーネスの場所を指定します。

1. `projects/talk.template.json`を自分用にコピーし、素材の絶対パス・入力色・プレビュー範囲を設定する。
2. `session start PROJECT SESSION --brief-file BRIEF`で視聴者・目標尺・残す目的を保存する。
3. その素材のクラウド送信が依頼範囲に含まれる場合、`uv run --extra transcription-cloud video-harness session transcribe SESSION`。OpenAI→Azureの順。APIキーは環境変数へ設定し、JSONに書かない。
4. `session context SESSION --words`で実際の単語IDを読み、章・発話範囲・保持／省略理由を計画する。`examples/workflow*.json`は書式例であり、このまま実素材へ適用しない。
5. `session plan`→`session approve --actor codex --note REASON`→`session render`でプレビューを作る。人間が行った選択だけ`--actor human`にする。
6. 動画、音声のみ、字幕を確認。`session inspect SESSION RENDER_ID --start 432 --duration 8`で必要区間の接触シート・波形・試聴音声を出す。`session review-page`の指摘ファイルを`session feedback`へ戻す。
7. 指摘を`session revise`や色／音声／字幕の変更に反映し、新版のレビューで解消を確認する。文字起こし修正は`session correct-transcript`で単語IDと時刻を保持する。
8. 全解像度の`session render --full`を確認し、`session package --target fcp`で受け渡す。FCPでLUT、SRT、マスク、音声を適用・確認。実際の確認を`session delivery-check`へ記録し、`session finish`する。

中断・交代では`session status`、`session handoff`、`session resume --actor claude_code`を使います。全構文は`uv run video-harness session --help`にあります。API課金、試聴、FCP GUIの実際の結果を、合成テストや自動検証と分けて扱います。Windows、複雑なFCPタイムライン、複数素材／B-roll、被写体追跡は今回の対応範囲外です。
