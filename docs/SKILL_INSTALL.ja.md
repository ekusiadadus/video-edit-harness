# video-editingスキルの導入

[English](SKILL_INSTALL.md) | 日本語

CodexとClaude Code向けにMITライセンスで公開するコミュニティ製スキルです。このGitHubリポジトリとリリースから配布します。各社の公式キュレーション一覧への掲載ではありません。実行にはVideo Edit Harness、Python 3.11以降、uv、FFmpeg、ffprobeが必要です。ローカルWhisperは導入せず、スキルの導入だけで動画のアップロードが許可されることもありません。

## ハーネスの準備

```sh
git clone --branch v0.1.0-alpha.3 https://github.com/ekusiadadus/video-edit-harness.git
cd video-edit-harness
uv sync --locked
export VIDEO_EDIT_HARNESS_ROOT="$PWD"
```

エージェントを起動する環境にも`VIDEO_EDIT_HARNESS_ROOT`を渡してください。スキルは依存ツールの導入や不足しているチェックアウトの取得を自動実行しません。ハーネスがない場合は先に上記の準備を行います。既存のスキルが同じ名前である場合は、内容を確認してから更新してください。

## Codex

このチェックアウトでは`.agents/skills/video-editing`からスキルを検出できます。他のプロジェクトでも使う場合は、このフォルダを`~/.agents/skills/video-editing`へコピーするか、リリースの`video-editing-skill-v0.1.0-alpha.3.zip`を`SHA256SUMS`で確認してから配置してください。ZIPは`video-editing/`として展開され、`SKILL.md`、`agents/openai.yaml`、MITライセンスが含まれます。ハーネスと動画素材は含まれません。

新しいCodexセッションで`$video-editing`を指定します。例：「$video-editingでローカルの室内動画を3つの色で比較してください。素材はアップロードしないでください」。仕様は[公式スキルガイド](https://developers.openai.com/codex/skills)を参照してください。

## Claude Code

リポジトリのコミュニティマーケットプレイスからプラグインを導入できます。

```sh
claude plugin marketplace add ekusiadadus/video-edit-harness
claude plugin install video-editing@video-edit-harness
```

新しいClaude Codeセッションで`/video-editing:video-editing`を指定します。マーケットプレイスの更新対象は公開リポジトリです。別途用意したハーネスのチェックアウトは、明示的に更新するまで上記タグに固定されます。ZIPの`video-editing/`を`~/.claude/skills/`へ配置して`/video-editing`で呼び出す方法もあります。重複して読み込まないよう、どちらか一方を選んでください。

リリースには`video-editing-claude-plugin-v0.1.0-alpha.3.zip`も用意します。マニフェスト、同じスキル、ライセンスを含む配布物で、ハーネスや動画素材は含みません。展開後は`claude --plugin-dir /absolute/path/to/extracted-plugin`でローカル読み込みできます。インストールされたプラグインのルートにある`CLAUDE.md`は自動読み込みされません。スキルはハーネスのREADMEとAGENTS.mdを読むよう明記しています。[公式マーケットプレイス手順](https://code.claude.com/docs/en/plugin-marketplaces)も参照してください。

## 素材の保護と確認の範囲

アップロード禁止の素材は、クラウド文字起こしにも送信しません。色調整、音声の正規化、プレビュー、技術検証はローカルで実行できます。既存の封印済み文字起こしがなければ、単語の時刻を捏造せず、文字起こしに基づく間の編集は行いません。公開デモは合成素材です。人による試聴・目視確認とFCPのGUI確認は、ソフトウェアの検証と区別します。

## /tiktokを使う

専用の`tiktok-skill-v0.1.0-alpha.3.zip`を確認して展開し、`tiktok/`を`~/.claude/skills/tiktok`へコピーします。新しいセッションで`/tiktok /path/to/video.mov`を指定できます。Codexでは同じフォルダを`~/.agents/skills/tiktok`へ配置し、`$tiktok`で呼び出します。プラグイン導入の場合は`/video-editing:tiktok`です。[TikTok編集手順](TIKTOK.ja.md)を参照してください。
