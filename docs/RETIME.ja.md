# スピードランプと静止保持

`retime prepare` は実入力のSHA・CFR・フレーム数へ操作を結び付け、未採用の提案を保存します。`retime render` は対応表どおりに原フレームを間引き・複製してMP4を作ります。補間による新しいフレームは生成しません。低fpsのスローは滑らかになるとは限りません。

```sh
uv sync --locked --extra retime-audio
uv run --extra retime-audio video-harness retime prepare INPUT.mp4 request.json --output proposal.json --actor codex --note '観察した動作の見せ場を強調する'
uv run --extra retime-audio video-harness retime render INPUT.mp4 proposal.json --output retimed.mp4
```

Rubber Bandコマンドが使えるローカル環境が必要です。インストールと版は使用環境で確認してください。既存のtrackingなどのextraも使う場合は、sync/runに併記するか同期済みの環境で `uv run --no-sync` を使います。

次は構造例です。フレーム番号・字幕・理由は実素材の観察結果へ置き換えます。終了フレームは含みません。

```json
{
  "audio_backend":"rubberband",
  "operations":[
    {"id":"movement","kind":"ramp","source_first_frame":24,"source_end_frame_exclusive":120,"speed_start":0.5,"speed_end":2,"reason":"見せたい動作から次の姿勢への変化"},
    {"id":"hold","kind":"freeze","source_frame":144,"output_frames":6,"reason":"結果を読み取る時間"}
  ],
  "protected_intervals":[[0,24]],
  "captions":[{"id":"result","text":"観察した結果","source_first_frame":144,"source_end_frame_exclusive":168}]
}
```

ランプの速度は0.25〜4倍。出力尺はフレーム単位へ丸め、実際の間引き・重複を報告します。操作は順序付きで重ならない必要があります。保護区間を変速・静止保持が横切る場合は拒否します。発話や細かい操作の保護区間を省略して、安全が自動保証されたと扱わないでください。

音声は原区間をピッチを保ちながら伸縮します。未変更区間はPCMをコピーし、静止保持では無音を挿入して原音から再開します。後から追加するBGMは、新しい出力タイムラインへ配置するのが基本です。すでにミックス済みの曲を含む入力へ適用すると、その曲も時間伸縮されます。音ハメや楽句の自然さを自動保証する処理ではありません。

標準の `rubberband` はR3エンジンとサンプル単位の時間対応を使います。[公式CLIの時間対応仕様](https://breakfastquay.com/rubberband/usage.txt)を参照してください。明示した `phase_vocoder` は代替実装ですが、[librosa公式が説明するアタックのアーティファクト](https://librosa.org/doc/0.11.0/generated/librosa.phase_vocoder.html)に注意が必要です。バックエンドが使えない場合に黙って別方式へ切り替えません。音質は全編の試聴で確認します。

字幕は入力フレームを通じて時刻を移し、飛ばされた字幕は `omitted_by_retime` として記録します。MP4へ焼き込まず `.srt` として保存します。発話の文字起こし・単語アライメント・翻訳を生成する機能ではありません。

入力は回転を焼き込んだ正方形ピクセルのRec.709映像が前提です。HDRや表示回転付き素材は拒否します。Apple Log素材は明示的にRec.709へ変換してから使います。既存の成果物は上書きしません。入力・提案の変更、VFR、範囲外参照は拒否し、全映像・音声をデコードして尺・fps・フレーム数を検査します。

visualセッションでは `session retime-source SESSION RENDER_ID` で連結した元段階を確認し、`session retime SESSION RENDER_ID --request-file request.json --actor codex --note REASON` で未採用候補を作れます。原素材までのフレーム対応を保存し、変速後にBGM・効果音を配置します。古い明示cue／エフェクト／保護領域は候補内で失効し、採用中の状態は変更しません。追跡は変速済みの実入力へ再解析します。FCPのmix/video_onlyは焼き込んだ変速を保持し、元カット参考XMLは変速前として別に残します。FCPで編集できる時間変更、発話セッションの単語保護への統合、既存の追跡・cue・字幕ファイルの自動移行は未接続です。古い対応表や追跡データを新しい動画へ流用せず、再解析・再配置します。技術検査は人の見た目・試聴レビューや投稿先再生の代わりになりません。

## 発話区間の確認（alpha.6後の開発版・描画接続は未完了）

新しく描画した発話セッションでも `session retime-source SESSION RENDER_ID` で、追加BGM・効果・音量正規化の前の `speech-base.mov` を確認できます。選択済みのカット・色調整・音声フェードは反映済みです。元の素材と字幕・計画は保持し、映像は再圧縮せず連結した段階を別途保存します。追加の保存容量が必要です。以前のrenderにこの段階がない場合は、選択済み計画を新しく描画してください。

返り値の `word_protection` は、実際の選択済み書き起こしとフレーム対応に結び付きます。`protected_intervals` は発話に触れるフレームの `[開始,終了)`、`word_occurrences` は元のword ID、出現番号、時刻、フレームを保持します。字幕表示用の丸めた時刻ではなく元の単語時刻を使い、切り出し・並べ替え・繰り返しも扱います。元の素材・計画・書き起こし・対応表のSHAを確認できます。

これは発話の候補描画に接続するための準備機能です。`session retime` による発話動画の速度変更はまだ拒否します。単語のない区間が無音／非発話であるとは推測しません。書き起こしの漏れや元の時刻精度、自然な聞こえ方は別途確認が必要です。ローカルASRや追加のクラウド送信は行いません。公開済みalpha.6には未収録です。
