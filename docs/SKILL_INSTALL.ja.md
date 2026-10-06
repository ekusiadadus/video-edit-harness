# スキルの導入

[English](SKILL_INSTALL.md) | 日本語

MITのコミュニティ版です。通常動画の `youtube`、縦動画の `tiktok`、一般編集の `video-editing` を配布します。実行には別途ハーネスが必要です。スキルの導入だけで素材の送信が許可されるわけではありません。公式キュレーションへの掲載ではありません。

## 1. ハーネスを用意する

Python 3.11以上、uv、FFmpeg、ffprobeを導入し、日本語字幕の焼き込みには日本語/CJKフォントを用意します。

```sh
git clone --branch v0.1.0-alpha.7 https://github.com/ekusiadadus/video-edit-harness.git
cd video-edit-harness
uv sync --locked
export VIDEO_EDIT_HARNESS_ROOT="$PWD"
uv run video-harness doctor
```

別プロジェクトからエージェントを起動する際もこの環境変数を渡します。doctorはパス・実行系/プラグイン/スキルのバージョン・コマンド・ツール・フォント・空き容量を表示します。認証情報は設定の有無だけを表示します。必要な指摘を解消してから編集します。バージョン差は診断情報で、異なる版ではコマンド互換を確認してください。エージェントは依存関係を自動導入しません。

## 2. 導入方法を一つ選ぶ

**Codex：** チェックアウトの `.agents/skills/` に3スキルがあります。別プロジェクトでは必要なフォルダを `~/.agents/skills/` またはプロジェクトの `.agents/skills/` にコピーします。新しいセッションで `$youtube`・`$tiktok`・`$video-editing` に素材パスと要望を添えます。

**Claude Codeプラグイン：**

```sh
claude plugin marketplace add ekusiadadus/video-edit-harness
claude plugin install video-editing@video-edit-harness
```

新しいセッションで `/video-editing:youtube`・`/video-editing:tiktok`・`/video-editing:video-editing` を使います。マーケットプレイスはmainに追従し、上記ハーネスは明示更新まで固定されます。更新後はdoctorで版を比較してください。

**Claude単体スキル：** `.agents/skills/NAME` を `~/.claude/skills/NAME` または `.claude/skills/NAME` にコピーします。新しいセッションで `/youtube /path/to/video.mov`・`/tiktok /path/to/video.mov`・`/video-editing` を使います。同じスキルの単体版とプラグインを重複導入しないでください。

## 配布ZIPと検証

[alpha.7リリース](https://github.com/ekusiadadus/video-edit-harness/releases/tag/v0.1.0-alpha.7)から取得します。`RELEASE-MANIFEST.json` は現行のwheel、ソース、3スキルZIP、プラグインZIPだけを列挙し、`SHA256SUMS` はそれらとmanifestを検証します。導入前に照合してください。

`NAME-skill-v0.1.0-alpha.7.zip` は `NAME/` にSKILL.md・agents/openai.yaml・LICENSEを展開します。使用するエージェントのスキルディレクトリにコピーします。ハーネス本体や動画は含みません。

`video-editing-claude-plugin-v0.1.0-alpha.7.zip` はmanifest・3スキル・ライセンスを含む固定版です。展開後、`claude --plugin-dir /absolute/path/to/extracted-plugin` で読み込めます。プラグイン直下のCLAUDE.mdは自動読込されず、スキルがハーネスのREADMEとAGENTS.mdを読むよう指示します。

wheelは仮想環境に `uv pip install /path/to/video_edit_harness-0.1.0a7-py3-none-any.whl` で導入でき、CLIとプリセットを含みます。スキルはチェックアウトのテンプレートと指示も利用します。PyPIには公開していません。

## 最初に試す

[公開用のオフライン合成サンプル](demo/README.md)で試せます。実測単語時刻付きで、APIキーは不要、送信禁止を保存します。実際の素材では既存の許可を引き継ぎ、素材SHAと送信先の許可をセッションに保存します。不明・禁止なら認証情報があっても文字起こし送信を止めます。ローカルWhisper/ASRは使いません。文字起こしがない場合もローカルの色・音声・画角プレビューは利用できます。

[Codex公式スキル資料](https://developers.openai.com/codex/skills/) · [Claude公式スキル資料](https://code.claude.com/docs/en/skills) · [Claudeマーケットプレイス資料](https://code.claude.com/docs/en/plugin-marketplaces)
