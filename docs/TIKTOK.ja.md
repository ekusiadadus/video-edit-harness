# TikTok・縦型ショートの編集

[English](TIKTOK.md) | 日本語

`tiktok`専用スキルで、TikTok・Reels・YouTube Shorts向けの動画をローカルで編集します。[導入ガイド](SKILL_INSTALL.ja.md)に従い、タグで固定したハーネスとスキルを用意してください。Claude Codeで正確に`/tiktok`と呼び出すには、`.agents/skills/tiktok`またはリリースZIPから展開した`tiktok/`を`~/.claude/skills/tiktok`へ配置し、新しいセッションを開始します。Codexでは`$tiktok`を指定します。マーケットプレイスのプラグイン経由では`/video-editing:tiktok`です。

```text
/tiktok /absolute/path/to/video.mov
/tiktok /absolute/path/to/talk.mp4 30秒で分かる解説に。語尾は残して、アップロードしないでください。
```

これはエージェントへのスキル呼び出しで、シェルコマンドではありません。動画のパスだけではクラウド文字起こしや投稿は許可されません。お子さんの動画など、公開禁止・送信禁止の素材はローカルに留めます。

素材を調べ、実際の場面に合わせた色とプレビューを用意します。許可された文字起こしと単語IDがあれば「冒頭で価値を伝える → 要点 → 結論」の短い構成へ編集し、留保や否定、語尾、呼吸を保持します。使える文字起こしがなければ、ローカルの色・構図・音声調整まで進め、時刻の捏造や会話の自動カットはしません。15〜60秒は編集方針の例で、プラットフォームの上限ではありません。

色調整または編集済みMP4から、縦型の納品ファイルを作ります。

```sh
uv run video-harness tiktok-export /absolute/path/to/graded-video.mp4 \
  --output output/my-tiktok --framing fit
# この編集結果に対応する、確認済みSRTがある場合は字幕を焼き込めます。
uv run video-harness tiktok-export /absolute/path/to/graded-video.mp4 \
  --output output/my-tiktok-captioned --framing fit \
  --subtitles /absolute/path/to/subtitles.srt
```

1080×1920、正方形ピクセルのH.264 MP4と音声、ハッシュ、技術検証を保存します。既定の`fit`は全画面を保持して余白を付けます。`center_crop`は明示的に選び、各場面で人物や文字が切れないか確認します。自動顔追跡はありません。入力は色調整済みSDR／Rec.709です。Apple Logの場合は先にハーネスで変換します。

[TikTokの公式インフィード広告仕様](https://ads.tiktok.com/resources/help/article/tiktok-auction-in-feed-ads?redirected=1)は9:16を推奨し、表示を妨げない範囲は寸法・キャプション・追加UIにより変わるとしています。これは広告仕様で、通常投稿の一律の仕様ではありません。1080×1920や字幕の余白はハーネスの作業上の既定値です。実機の投稿プレビューでも確認してください。

縦型MP4を作っても、元の画角で出力するFCPXMLの構図は変わりません。FCPへ引き継ぐ場合は縦型の構図を別途適用して確認します。全編デコード、寸法、長さ、音声の検証と、人による目視・試聴、字幕確認、TikTokでの再生確認は区別します。投稿やアップロードは別途明示的に依頼された場合だけ行います。

## セッションに縦版を保存する

文字起こしを使う編集では、縦エクスポートを `session register-vertical SESSION RENDER_ID RESULT_JSON` で主レンダーに関連付けます。`session review-vertical SESSION DERIVATIVE_ID --data-file REPORT_JSON` には動画SHAと、`framing`・`captions`・`audio`・`playback` の4項目を、実際のstatus・basis・noteで記録します。画角と字幕、音声、ローカル再生を確認し、投稿先での再生とは区別してください。合成fixtureの `synthetic` は人の確認ではありません。

主動画の最新全編と縦動画のレビューが通ったら `session package SESSION RENDER_ID --target mp4 --derivative-id ID` で選んだ縦版を含め、`session finish SESSION DELIVERY_ID --actor ACTOR` します。素材・主レンダー・計画・字幕・フォント・出力が変わると旧レビューを使えません。完了記録と確認証拠は納品フォルダに含まれます。`video_harness.delivery.verify_completion(folder)` はファイルハッシュと記録の整合確認で、署名付き証明やTikTok上の再生確認ではありません。
