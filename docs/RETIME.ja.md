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

visualセッションでは `session retime-source SESSION RENDER_ID` で連結した元段階を確認し、`session retime SESSION RENDER_ID --request-file request.json --actor codex --note REASON` で未採用候補を作れます。原素材までのフレーム対応を保存し、変速後にBGM・効果音を配置します。古い明示cue／エフェクト／保護領域は候補内で失効し、採用中の状態は変更しません。追跡は変速済みの実入力へ再解析します。FCPのmix/video_onlyは焼き込んだ変速を保持し、元カット参考XMLは変速前として別に残します。FCPで編集できる時間変更、既存の追跡・cueファイルの自動移行は未接続です。発話セッションは下記の開発版経路を使用します。古い対応表や追跡データを新しい動画へ流用せず、再解析・再配置します。技術検査は人の見た目・試聴レビューや投稿先再生の代わりになりません。

## 発話を保護する時間変更（alpha.6後の開発版）

新しく描画した発話セッションでも `session retime-source SESSION RENDER_ID` で、追加BGM・効果・音量正規化の前の `speech-base.mov` を確認できます。選択済みのカット・色調整・音声フェードは反映済みです。元の素材と字幕・計画は保持し、映像は再圧縮せず連結した段階を別途保存します。追加の保存容量が必要です。以前のrenderにこの段階がない場合は、選択済み計画を新しく描画してください。

返り値の `word_protection` は、実際の選択済み書き起こしとフレーム対応に結び付きます。`protected_intervals` は発話に触れるフレームの `[開始,終了)`、`word_occurrences` は元のword ID、出現番号、時刻、フレームを保持します。字幕表示用の丸めた時刻ではなく元の単語時刻を使い、切り出し・並べ替え・繰り返しも扱います。元の素材・計画・書き起こし・対応表のSHAを確認できます。

`session retime` は、必須の単語保護と観察済みの非発話区間に結び付けた未採用候補を作成します。単語のない区間が無音／非発話であるとは推測しません。書き起こしの漏れや元の時刻精度、自然な聞こえ方は別途確認が必要です。ローカルASRや追加のクラウド送信は行いません。公開済みalpha.6には未収録です。


発話requestには `nonspoken_intervals` を指定します。下記は構造例であり、番号は実際の `speech-base.mov` の観察結果に置き換えてください。操作対象のすべてのフレームが観察区間に含まれ、必須の単語保護に触れない必要があります。任意の `protected_intervals` は保護を追加します。字幕は計画の実単語から生成するため、requestで `captions` は指定しません。

```json
{
  "operations":[{"id":"pause-hold","kind":"freeze","source_frame":20,"output_frames":6,"reason":"観察した非発話の結果を読み取る時間"}],
  "nonspoken_intervals":[{"first_frame":20,"end_frame_exclusive":21,"reason":"該当区間を試聴して非発話と確認"}]
}
```

```sh
uv run --no-sync video-harness session retime-source SESSION RENDER_ID
uv run --no-sync video-harness session retime SESSION RENDER_ID --request-file speech-request.json --actor codex --note '観察した非発話区間の時間変更候補'
uv run --no-sync video-harness session render SESSION --candidate-id CANDIDATE_ID --full
```

発話の連結段階はプレビューでもフル解像度で保持します。新しい候補の描画時に素材・計画・単語保護・対応表を再検証し、変更されていれば拒否します。旧renderの低解像度の連結段階は再描画が必要です。変速後の `speech-retimed.wav` をPCMのまま追加音・正規化へ渡し、最終MP4ではAACへ符号化します。未変更の保護発話は、この正規化・追加音・最終符号化前のPCMで保持します。freezeには無音が挿入されます。

開発版のvisualセッションも `visual-retimed.wav` を保持し、そのPCMから環境音のミックスを作ります。途中の色調整・重ね合わせ・エフェクト動画のAACを再デコードして音源にする経路を避けます。変速後のMP4は各描画段階で48 kHzのmovie timescaleを指定し、例えば56フレーム／30fpsの末尾がミリ秒単位への丸めで短くならないようにします。重ね合わせとエフェクトは音声をコピーし、入力で宣言されたRec.709の色タグも保持します。最終AACの圧縮やデコーダーの末尾パディングは、PCMの保持とは別です。FCP mix用の `final-mix.wav` とXMLを使い、実際のFCPで再生・試聴を確認してください。

`pre-retime-mapping.json` と `original-cut-reference.fcpxml` に元の対応とカットを残します。新しい対応表は出力フレーム→連結段階→元素材の関係を持ち、字幕と検査時刻を移行します。追加音・効果は新しい尺で生成します。FCPのmix受け渡しは完成映像と最終音声を渡し、編集可能な速度変更は生成しません。候補作成・描画・技術検査は採用や人の全編視聴／試聴を意味しません。


時間変更版は `session compare-candidates SESSION NATURAL_RENDER RETIMED_RENDER --mode timing` で同じ選択済み計画の自然版と比較します。尺が異なるため、各案の再生・シークは独立し、短い案の終了で長い案を止めません。元の選択範囲、色、基本音声設定、プレビュー条件は揃え、尺と変更操作を証拠へ記録します。既定の `effects` 比較は従来どおり同じ対応表を要求します。この `timing` モードでは別計画・並べ替えを比較できません。下記の明示的な `structure` モードを使います。

## 構成を変えた案の比較（alpha.6後の開発版）

結果先出し版と時系列版など、別の計画を比べる場合は `session compare-candidates SESSION FIRST_RENDER SECOND_RENDER --mode structure` を使います。同じbrief・登録済みの素材群・色・基本音声設定・出力fps・プレビュー条件が必要です。各案の元の素材範囲と順序、計画に記録した理由、長さ、実際に加えた音・効果を表示します。自然版に対する範囲の追加／除去は同じ範囲の反復も数え、単なる並べ替えと素材の省略を区別します。範囲の変更は自動で良い編集と評価しません。

各動画を個別に全編再生します。同じ出力時刻が同じ内容を指すとは扱いません。速度変更がある案は変速前の範囲と速度変更／停止を別に記録します。変速していない自然版を含めてください。選択メモは動画SHAとその案の再生時刻に結び付いた提案であり、計画の採用・人の承認・投稿を行いません。従来の `effects`／`timing` モードで別計画を比較する制約は変わりません。

保存した `comparison-selection.json` は、次のコマンドで未採用候補へ戻せます。現在の計画に古い色や効果だけを適用せず、選んだrenderの計画と設定を一緒に保持します。動画SHA・brief・素材・選択時刻が一致しない場合は拒否します。

```sh
uv run --no-sync video-harness session select-comparison SESSION --data-file comparison-selection.json --actor codex --note '比較した構成を再確認する候補'
uv run --no-sync video-harness session render SESSION --candidate-id CANDIDATE_ID --full
uv run --no-sync video-harness session adopt-candidate SESSION CANDIDATE_ID --actor codex --note '再描画した構成を選択'
```

採用後も正確な全編出力のレビューが必要です。元の案に戻したい場合も、そのrenderの選択メモから候補を作ります。新しいrenderは書き起こしとcontextの入力参照も保存します。旧renderに入力参照がない発話編集は、保持済み計画に埋め込まれた実書き起こしから復元し、contextは実単語と同じbriefから自動で再生成します。単語時刻を作り直したり、人の承認を引き継いだりはしません。公開済みalpha.6には未収録です。
