# Video Edit Harness

[English](README.md) | 日本語

**Codex・Claude Codeでローカルの話す動画を編集するハーネスとスキルです。** 不要な間の短縮、場面に合う色、聞きやすい音声、字幕、Final Cut Proへの受け渡しを扱います。内容と仕上がりを確認しながら、素材のハッシュ、修正履歴、納品時の証拠を一緒に管理できます。

[![日本語の編集前後デモ](docs/demo/ja/youtube-preview.gif)](https://github.com/ekusiadadus/video-edit-harness/releases/download/v0.1.0-alpha.4/youtube-demo-ja.mp4)

**[日本語音声付きで見る：編集前 → 編集後 → TikTok](https://github.com/ekusiadadus/video-edit-harness/releases/download/v0.1.0-alpha.4/youtube-demo-ja.mp4)** · [日本語YouTube版の全編](https://github.com/ekusiadadus/video-edit-harness/releases/download/v0.1.0-alpha.4/youtube-result-ja.mp4) · [日本語TikTok版の縦動画](https://github.com/ekusiadadus/video-edit-harness/releases/download/v0.1.0-alpha.4/tiktok-demo-ja.mp4) · [English demo](README.md)

この日本語デモにはオリジナルのイラスト、合成した日本語音声、日本語の字幕とラベルを使用しています。[英語デモ](README.md)には別の英語音声・字幕・ラベルを使用しています。どちらも合成素材の例で、YouTube版は二つの助言を残し、TikTok版は一つを最後まで伝えます。実際のローカル編集結果を使った比較であり、画面収録ではありません。自動検証やデモだけでは、人による試聴の承認、FCP GUIでの読み込み、実写素材の品質は証明されません。[素材の出典とオフライン再現手順](docs/demo/README.md)。

## 編集を依頼する

| 利用方法 | 通常のYouTube動画 | TikTok・Reels・Shorts |
|---|---|---|
| Codexスキル | `$youtube /path/to/talk.mov` | `$tiktok /path/to/video.mov` |
| Claude単体スキル | `/youtube /path/to/talk.mov` | `/tiktok /path/to/video.mov` |
| Claudeプラグイン | `/video-editing:youtube /path/to/talk.mov` | `/video-editing:tiktok /path/to/video.mov` |

例えば「説明のつながりと語尾を残し、不要な間を短く。アップロード禁止」と添えます。一般的な編集や色の比較には `video-editing` を使います。上記はエージェントへの依頼で、シェルコマンドではありません。

## 最初の準備

Python 3.11以上、[uv](https://docs.astral.sh/uv/)、FFmpeg、ffprobeが必要です。macOS・Linuxに対応し、Final Cut Proでの仕上げにはmacOSが必要です。Linuxで日本語字幕を焼き込む場合は日本語/CJKフォントを用意してください。

```sh
git clone --branch v0.1.0-alpha.4 https://github.com/ekusiadadus/video-edit-harness.git
cd video-edit-harness
uv sync --locked
export VIDEO_EDIT_HARNESS_ROOT="$PWD"
uv run video-harness doctor
```

**Codex：** このディレクトリで新しいセッションを開始します。3スキルは `.agents/skills/` にあります。別のプロジェクトから使う場合は必要なフォルダを `~/.agents/skills/` にコピーし、上記のハーネスパスを引き継ぎます。

**Claude Code：** コミュニティプラグインを導入して新しいセッションを開始します。

```sh
claude plugin marketplace add ekusiadadus/video-edit-harness
claude plugin install video-editing@video-edit-harness
```

正確に `/youtube`・`/tiktok` と入力したい場合は単体スキルを使います。[導入方法・ZIPの検証・バージョン診断](docs/SKILL_INSTALL.ja.md)。公開予定のGitHubリリースはコミュニティ配布版で、公式キュレーションへの掲載ではありません。

## APIキーなしで試す

v0.1.0-alpha.4の公開後に[日本語の合成サンプル](https://github.com/ekusiadadus/video-edit-harness/releases/download/v0.1.0-alpha.4/demo-fixture-ja-v0.1.0-alpha.4.zip)を取得し、`DEMO-SHA256SUMS` で確認します。実測の単語時刻とライセンスを含みます。

```sh
uv run python scripts/prepare_demo.py --fixture /path/to/demo-fixture-ja-v0.1.0-alpha.4.zip \
  --output output/my-sample
```

エージェントへの依頼例：

```text
$youtube output/my-sample/sample.mp4
机の片付け方の二つの助言を残し、長い間だけを短くしてください。
output/my-sample/project.json と既存の
output/my-sample/transcript/transcript.json を使ってください。
アップロード禁止。まずプレビューを作成してください。
```

Claude単体では `$youtube` を `/youtube`、プラグインでは `/video-editing:youtube` に替えます。準備スクリプトは素材のハッシュを確認し、実測時刻を手元のパスに結び直し、クラウド送信を禁止に設定します。音声認識は実行しません。[CLIでの編集・デモ再生成](docs/demo/README.md)。

## 管理する流れ

**原素材 → 単語時刻付き文字起こし → 編集計画 → プレビュー → フィードバックと修正 → 全編レンダー → 確認済みの納品**をセッションとして保存します。再開・引き継ぎでも関連を保持します。長尺の編集点試聴では残りIDを表示し、合格記録には全編試聴か、確認したIDと確認省略の理由を残します。縦動画は素材・レンダー・字幕・フォントと独立したレビューを持ち、選んだ版を納品に含めます。完了証拠は納品フォルダの `completion.json` に入ります。

7用途と6スタイルを組み合わせます。室内トークは `indoor_talk` + `natural` を出発点とし、屋外の日中・夜・逆光には別の初期設定を使います。明度、コントラスト、中間調、彩度、ハイライト、固定領域の補正も調整できます。用途はプラットフォーム名ではなく、実際の場面で選びます。[プリセット一覧](docs/PRESET_CATALOG.md)。

文字起こしは **OpenAI → Azure OpenAI** の順です。素材と送信先への許可を記録し、不明・禁止なら再開後も送信を止めます。ローカルWhisper/ASRは使いません。APIキーだけでは送信許可にならず、API利用には料金が発生する場合があります。既存の封印済み文字起こしがあればオフラインで内容編集できます。なければローカルの色・音声・画角プレビューを進めます。送信禁止の子供の映像などは外部に送信しません。

[セッション操作とレビュー](docs/WORKFLOW.ja.md) · [縦動画の編集](docs/TIKTOK.ja.md) · [文字起こし](docs/TRANSCRIPTION.md) · [設計判断](docs/DECISIONS.md)

## 対応範囲と検証

**アルファ版：** 単一素材の平坦なタイムラインが対象です。通常の動画は原素材の縦横比を保持し、9:16版は余白付きfitを標準とします。center cropは確認して明示指定します。自動顔追跡、Bロール構成、プラットフォームへの投稿はありません。Apple Log LUTはRec.709変換を含むため、FCPのCamera LUTとの二重変換を避けます。HDR/HLG・Apple Log 2には別の対応変換が必要です。

FCPXMLはカット時刻と素材リンクを渡します。LUT・字幕・空間マスク・FCP最終音声ミックスは別途適用と確認が必要です。XML/DTD、ハッシュ、全編デコード、フレーム対応の検証と、人の試聴・映像確認、実際のFCP取り込み、投稿先での再生を区別します。合成デモや自動チェックは実写の品質を保証しません。[リリース検証と未確認事項](docs/RELEASE_VALIDATION.md)。

```sh
make test
uv run video-harness verify /path/to/final.mp4 --output output/final-check
```

[リリースとチェックサム](https://github.com/ekusiadadus/video-edit-harness/releases/tag/v0.1.0-alpha.4) · [貢献方法](CONTRIBUTING.md) · [MITライセンス](LICENSE)。ソース、wheel、3つの単体スキルZIP、ClaudeプラグインZIPを配布します。PyPIへの公開は行っていません。
