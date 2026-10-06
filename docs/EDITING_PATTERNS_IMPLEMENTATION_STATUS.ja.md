# 編集パターン実装の進捗と検証台帳

## 2026-10-06: 追跡マスクによる背景抑制（alpha.6後の開発版）

- `session track-effect --effect tracked_background` が保持pre-effects映像の追跡からOpenCV GrabCutの実前景マスクを生成し、未採用候補の背景減光・低彩度化へ接続する。連番の全サイズ二値PNG、素材・追跡・手動補正のSHA、エンジン版、actor／理由を保持。矩形塗りの代用はしない。
- 手動PNGの差し替え、画素の完全一致検査、古い素材／PNG／追跡、追跡喪失・空の前景の拒否を実装。候補再描画の同一内容SHAを別フォルダーでも受け入れる。枠外は背景なのでpose胴体枠には全フレームの手動マスクを要求する。重なる画角変更・残像・別マスクは拒否。
- RGB合成の指定開始／終了とsubsetをフレーム単位で検査。音声コピー・同じフレーム数／対応表を維持し、生成タイトルは後段。レビューに正確なrender SHAの`subject_masks`視覚確認を追加。[操作・制限](TRACKING.ja.md)。深度や髪の半透明マッティングは未実装。
- 合成の動く前景から実GrabCut・実FFmpeg・全デコードで前景保持／背景抑制、開始末尾／subset、音声PCM一致、マスク改変・重なるズームの拒否を検査。セッション候補から最終描画・未採用維持・輪郭レビュー必須も確認。全411試験138.931秒成功: `output/implementation-maya/subject-background-full-suite.log`。配布物6件監査・クリーンwheel・3スキル形式検査も成功。
- 前回残像CI37463969532は成功。今回の実ダンス輪郭品質・人の全編視聴／試聴・FCP GUI・投稿用MP4・元計画全体の完了は未証明。公開済みalpha.6には今回機能を含まない。

## 2026-10-06: 指定区間の限定残像（alpha.6後の開発版）

- 版付き`motion_trail`をcatalog、明示効果候補、実描画へ接続。指定ショット内の現在を含む2〜4フレームを減衰重みで混ぜ、最初に履歴をリセットする。カット横断、残像区間の重複、履歴より短い指定を拒否。音声はコピーし、映像の対応表・尺を維持する。自然版やプリセットへ自動追加しない。
- 画面全体の時間混合で、被写体マスクやAI補間ではない。後段の生成タイトルは混合しないが、素材や前段に焼き込まれた文字は影響する。低fps、顔・手・輪郭、文字の読み取りを実素材で確認する。[指定方法](VIDEO_EFFECTS.ja.md)。
- 30fpsと30000/1001の実描画をデコードし、古い実フレームの残像、未来の不使用、先頭リセット、区間外の終了、12フレームと音声PCM一致を検査。セッションの候補から最終MP4までの到達と未採用の維持も検査。全402試験156.165秒成功。その後の2フレーム条件・セッション試験を含む関連11試験4.042秒成功。ログ`output/implementation-maya/motion-trail-full-suite.log`／`motion-trail-focused.log`。
- 6配布物監査、クリーンwheel、3スキル形式検査成功。前回J/LのCI37462804628はmacOS/Ubuntu3環境成功。公開alpha.6には今回機能を含まない。実素材の人による品質受入、被写体マスク、動作方向トランジション、FCP GUI、投稿用MP4等を含む全計画の実装・受入を継続する。

## 2026-10-06: 実素材ハンドルを使うJ/Lカット（alpha.6後の開発版）

- `session audio-cuts` は既存renderの素材・計画・対応表に結び付いた未採用候補を作る。次クリップの実原音を先行するJ、前クリップの実原音を延長するLをPCMサンプル単位で置き換え、映像・尺は維持する。元PCMを保持する。
- 発話v3は実単語IDと時刻で完全なハンドル語を検査し、字幕と音声検査の対応を更新する。既知発話・明示保護の除去、単語の分断、範囲外／重複の置換、古い素材／対応表を拒否。整数IDにも対応する。visualは非発話の明示のみで、声の有無の自動証明ではない。
- listeningを要する`audio_cuts`レビュー項目を追加。繰り返しIDの明示は承認ではない。原カットXMLは置換前の参考、焼き込み済みmix/video_onlyのみ対応。retime併用とeditable FCPは未対応。[操作](AUDIO_CUTS.ja.md)。
- 合成chirpと実PCMデコードを用いて、置換範囲外の完全一致、原音ハンドルとの一致、映像対応表の維持、追加語の字幕・inspection対応、FCP mixのサンプル数を検査。全395試験127.428秒成功。レビュー後に対応表配列の長さ不一致の拒否を追加し、関連8試験11.513秒成功。ログ: `output/implementation-maya/jlcut-final-focused.log` / `jlcut-full-suite.log`。6配布物監査・クリーンwheel・スキル形式検査も成功。実発話・人の試聴品質、FCP GUI、最終YouTube MP4、計画全体の完成を証明しない。

## 2026-10-06: 時間変更版の比較と音声末尾の修正（alpha.6後の開発版）

- `session compare-candidates --mode timing` は同じ選択済み計画・元カット対応・色・基本音声設定・プレビュー条件を要求し、時間変更を再計算して出力対応表と照合する。尺・操作・省略／反復フレーム・追加演出を記録する。各案の全尺を個別に再生する。既定のeffects比較の厳密な同一対応表条件は維持する。別計画・並べ替え比較は未対応。
- ブラウザー上の合成1.2秒／3.2秒比較で長い案の末尾到達を確認。修正メモのダウンロードは待機APIがタイムアウトしたが、実ファイルと画面を読み戻し、対象SHA・3.2秒・未採用／未承認を確認。`output/implementation-maya/timing-comparison-browser-evidence.json`／`timing-comparison-browser-selection.json`／`timing-comparison-browser.png`。人の試聴評価ではない。
- 前回のCI37455001989はUbuntu3.13のretime音声尺検査で失敗し、他2環境はキャンセル。MP4のmovie timescale=1000で56/30秒のAAC末尾が32サンプル短くなるケースを再現。retimeと発話retime最終muxへ48000を明示し、89600サンプルの末尾検査を追加した。派生する効果・overlay・FCP再muxの同条件検証は今後も必要。
- 必要extraを入れた環境で全371試験成功（112.248秒）、発話・visualの比較統合を含む22試験成功。生ログ: `output/implementation-maya/timing-comparison-full-suite.log`／`timing-comparison-integration.log`。実素材の見やすさ・FCP GUI・最終YouTube用MP4・計画全体の完了を証明するものではない。


## 2026-10-06: 発話保護を候補・最終描画へ接続（alpha.6後の開発版）

- 発話 `session retime` は選択済み計画の必須単語保護と、観察した `nonspoken_intervals` を持つ未採用候補を作る。操作区間の全フレームに観察を要求し、単語に重なる観察や保護の改変を拒否する。単語がないことから非発話を推定しない。
- フル解像度の連結映像をプレビューでも保持。候補描画で素材・計画・対応表・単語保護を再検証。出力フレームから連結段階・元フレームへ追跡し、字幕・検査時刻を移行する。旧cue・効果・保護領域を失効させ、新しい尺で再生成する。
- 時間変更したPCMを直接最終ミックスへ渡し、途中AACの再デコードを避ける。元カットXML・対応表を保持。FCP mixには変速済み映像と最終音声を渡す。編集可能なFCP時間変更は未対応。
- 合成の時刻注釈を用いた静止保持（60→66フレーム）・2倍速（60→56フレーム）、保護PCM一致、字幕同期、プレビュー／本番の連結素材SHA一致、FCP mix出力を検査。全363試験成功（91.030秒）: `output/implementation-maya/speech-retime-full-suite.log`。配布物6件の監査・クリーンwheel・スキル検査も成功。実ASR／実発話品質の証明ではない。
- 以下の準備段階・alpha.6の記録はその時点の履歴。現在の機能は公開済みalpha.6には未収録。実人間の発話自然さ、全編の人の視聴／試聴、FCP GUI受け渡し、最終YouTube用MP4は未完了。


## 2026-10-06: 発話の連結段階と単語保護の準備（alpha.6後の開発版）

- 発話renderで `speech-base.mov`／`speech-base.wav`／`speech-assembly.json` を保持。カット・色・既存の音声フェードを含み、追加BGM・視覚効果・音量正規化の前の段階。映像はコピー連結で追加再圧縮をしない。保存容量の見積りを増やした。自然版と従来経路のデコード画素・PCM一致試験は維持する。
- `session retime-source` は新しい発話renderから素材と `word_protection` を返す。選択済み計画・書き起こし・対応表・元素材のSHA、元word IDと出現番号、保護フレームを記録。元の未丸め単語時刻、整数フレームの連結位置、部分的に残った単語を扱う。字幕の丸めによる保護漏れと、1/3秒境界の浮動小数誤差を回帰検査した。
- 合成の音声・時刻注釈を使ったセッションの描画／inspection、60フレーム、48kHz PCM一致、素材改変の拒否を検査。実人間の発話／ASR精度の証明ではない。関連17試験成功（11.865秒）、全355試験成功（88.258秒）: `output/implementation-maya/speech-protection-final-focused.log`／`speech-protection-full-suite.log`。
- 発話 `session retime` の候補と最終描画は引き続き拒否する。次は、観察した非発話区間の指定、必須の単語保護を伴う候補、対応表／字幕の移行、音声・効果の再生成へ接続する。単語のない区間を無音と推測しない。公開済みalpha.6には未収録。ユーザーがYouTubeへアップロードする指定を計画文書にも反映。

## 2026-10-06: 同時に見える文字同士の重なり（alpha.6後の開発版）

- `composition_guides` の有無にかかわらず、実測した文字カード同士を共有出力フレームで検査する。固定／追従、riseの移動、終了を含まない時間範囲、完全に透明な最初のフレームを扱う。重なりは両イベントID・フレーム・有理数時刻で拒否し、自動移動しない。古い描画の画素を変えず、重なっていた旧設定の再描画は修正が必要になる場合がある。
- `title_collision_checks` に組・時刻・検査数を保持。追従／riseの位置不足や重複、非有限矩形を拒否する。riseの報告位置を60fpsのデコード実画素に照合した。保護領域なしの2文字描画で衝突拒否、非衝突版の12フレームとPCM保持を確認。全345試験成功（86.780秒）: `output/implementation-maya/title-pair-full-suite.log`。
- 実素材の `dance-two-labels.mp4` は固定文字と追従文字を83共有フレームで検査し、245フレーム・完全デコード・PCM一致を確認。抽出4場面を確認したが、人の全編視聴・試聴の承認ではない。未宣言の他人物・既存の画面内文字・UI・読み時間は自動保護しない。完成公開用MP4ではなく技術試作。
- 前段の追跡前検査commit `b41b2d3` はCI `37450668729` 全3ジョブ成功。新しい機能の配布物・CIは別の検証単位とし、公開済みalpha.6の資産は変更しない。全計画の実装・受入は継続する。

## 2026-10-06: 追従ラベルの折り返し指定と追跡前検査（alpha.6後の開発版）

- `session track-effect --effect tracked_title --title-version 2` を追加。省略時は方式1を保持。タイトルJSONのスタイル・行幅・行数・配置をエフェクト前映像の寸法で検査し、長すぎる語・不正な動き・配置は `track_video` の呼び出し前に拒否する。
- 事前検査のフォント・モデルを候補イベントへ束縛し、`title_preflight` で行・矩形・PNG SHAを返す。生成素材の候補を実描画し、事前検査と同じPNG、8フレームの追従と保護領域検査、未採用状態保持を確認。被写体との重なり・画面外は追跡後の検査で、人の読みやすさ承認は別。
- 前段の文字組みcommit `073f027` はCI `37450032878` の全3ジョブで329試験・ビルド・配布検査成功。今回の4セッション試験成功（13.494秒）、全330試験成功（80.678秒）は `output/implementation-maya/title-preflight-session-tests.log`／`title-preflight-full-suite.log` に保持。READMEの設定リンク、追跡ガイド、共通スキルの指定手順を接続。公開済みalpha.6の配布物は変更しない。

## 2026-10-06: 実測幅による日本語・英語タイトルの折り返し（alpha.6後の開発版）

- `keyword_title`／`tracked_title` の方式2を明示すると、実フォント幅・最大カード幅・最大3行で折り返す。ローカルBudouXの句境界、regexの文字のまとまり、選択した禁則と数値／単位・保護語句を使用。収まる合法な区切りがある場合は句優先で誤って行数超過にしない。省略・自動縮小はしない。方式1のPNGは保持する。
- 元の文・描画行・実測矩形、フォント／PNG、依存バージョンとモデルSHAを記録。実測した折り返し矩形を既存の配置・追従検査に接続し、変わったモデルの既存イベントを拒否する。構文・行幅は読み時間や理解を保証しない。
- 全体328試験成功（75.616秒）後に改行探索を修正し、対象の文字・動画・追従31試験成功（4.766秒）。ログ: `output/implementation-maya/text-layout-final-full-suite.log`、`text-layout-final-focused.log`。実動画で複数行の実画素・12フレーム保持・PCM一致を検査。日本語／英語PNGを生成し日本語表示を確認した。配布物6件の検査、クリーンwheelの起動、スキル構造検査も成功。最新commitのCIは別途記録する。
- READMEと共通スキルに操作・保護語句・制限を追加。公開済みalpha.6には未収録。YouTubeのMP4は用途確認待ちで、投稿はユーザーが行う。全実装計画の完了ではない。

## 2026-10-06: 原映像と情報レイヤーの色調整を分離（alpha.6後の開発版）

- 方式2はカット／リタイムした原映像へLUTと固定領域補正を適用して `visual-graded.mp4` を保持し、その後に画像・文字・エフェクトを合成する。最終段階では再度LUTを適用しない。新しいvisualセッションは方式2、既存の未指定設定は方式1を維持する。
- `visual-pipeline.json` に方式・入力SHA・LUT SHA・処理対象を保存。方式変更は未採用候補で行い、同じ色条件を要求するエフェクト比較に異なる方式を混ぜない。色・方式変更後はエフェクト前映像を再解析し、古い追跡を流用しない。
- 生成素材をモノクロ化して、後段の緑の文字と赤い画像の色が残ることを実画素で確認。従来方式では同じ情報レイヤーもモノクロ化されることを対照確認。音声PCM一致、フレーム数とCFR、追跡・変速候補の関連試験も成功。全315試験成功（74.194秒）: `output/implementation-maya/visual-grade-order-full-suite.log`。
- 未公開パッケージの6配布物検査、クリーンwheelスモーク、スキル構造検査が成功。公開済みalpha.6の配布物には未収録。意図的な画面エフェクトは従来通り前段の合成画像にも作用し、補助・比較素材に共通LUTを自動適用しない。レイヤーごとの高度な効果範囲制御、実写全編の視聴・試聴、GUI往復等は別の未完了項目。

## 2026-10-06: 追従ラベル（alpha.6後の開発版）

- `tracked_title` をcatalog・実描画・局所修正・production依存検査へ接続。`session track-effect --effect tracked_title --title-parameters-file` が観察枠を追跡して、subject guide付きの未採用候補を作る。採用中のprojectは変わらない。
- 上／下／左／右、間隔、画面座標の微調整を明示。実測した文字カードを整数ピクセルで移動し、全フレームの位置・矩形・PNG／フォント／追跡SHAを記録する。追跡喪失・古い依存・画面外・宣言した保護領域との重なりを拒否。重なるズーム・split/comparisonは未対応の座標変換なので拒否する。
- 生成素材のデコード実画素で文字カードの位置をフレームごとに照合し、音声PCM保持を確認。候補のセッション描画、自然/offとvisual_assets off、source mismatch、stale track、lost、UI干渉を検証。全312試験成功（70.830秒）: `output/implementation-maya/tracked-title-full-suite.log`。
- 実ダンスの `dance-tracked-label.mp4` は0.5〜4秒の84フレームに左配置ラベルを適用。245フレーム、完全AVデコード、音声PCM一致、胴体の追跡領域との干渉なしを確認。抽出4場面を確認したが、人の全編視聴・試聴の承認ではない。他人物・頭や足・未宣言UIは自動保護しない。
- 自動再配置・美的な追跡平滑化・編集可能なFCP追従文字は未実装。公開済みalpha.6配布物にはこの追加を含まない。YouTube公開用動画は未完成・未投稿。全計画の実装と受入を継続する。

## 2026-10-06: visualセッション統合とalpha.6

- `session retime-source`／`session retime` が連結した元段階を確認し、未採用の候補を作る。古い明示cue・効果・保護領域は候補内で失効し、採用中のprojectを変更しない。変速後の尺で追加BGMを配置し、追跡入力は変速済みの段階を返す。
- 元のカットXMLを別に残し、FCP mix/video_onlyには変速済み映像を渡す。編集可能なFCP時間変更・発話セッションの単語保護は未対応として拒否する。自然な案へ戻すと変速も解除する。
- 原素材までのフレーム参照を保存。fpsだけの推定ではMKVの時間基準によりずれることが分かったため、原フレームでtrimし、検査したCFR素材の時間基準を正確な分数へ正規化してからfps変換する。MP4/MKV、24→30・30→24・15→10・60→30を実画素と照合した。異fpsの古いmappingにsource frame mapがない場合は再レンダーが必要。
- ローカル全体304試験成功（64.069秒）: `alpha6-full-suite.log`。Python3.11の別環境へwheelを入れ、checkout外で自然パターン・効果catalog・フレーム対応を確認した。wheel/sdist/3スキル/pluginの6配布物とプライバシー・チェックサム検査を実施。
- README・3スキル・インストールガイドをalpha.6へ更新。リリースは元のMAYA計画全体の完了を意味しない。GUI往復、全編の人の視聴・試聴、外部OAuthの実接続、人物追従する文字や発話変速等を継続する。alpha.6はコミット `8757bc43e63227621dbc19fef4feb83b93bb3d2c` で公開し、GitHub CIの3環境成功、公開8配布物のSHA一致、タグの参照先と日本語READMEの読み戻しを確認した。

## 2026-10-06: 変速・静止保持の実描画

- `retime prepare`／`retime render` を追加。入力SHA・CFR・観察した操作を束縛し、既存成果物を上書きしない。厳密なframe mapを通じて実フレームを間引き・複製し、静止保持を挿入する。補間フレームは生成しない。
- 音声は標準Rubber Band R3のサンプル時間対応で伸縮し、明示した代替phase vocoderも選べる。指定バックエンドの欠落は拒否。未変更PCMのコピー、静止区間の無音挿入と原音再開、出力サンプル数、合成toneでのピッチ保持を検証した。Rubber Band版・時間対応SHA・生ログを保存。
- 観察した字幕の原フレーム区間を出力時刻へ移しSRTを保存。飛ばされた字幕は省略として記録する。保護区間にかかる変速・保持、改変した対応表、変更された入力を拒否する。
- 実ダンス `output/implementation-maya/retime-dance.mp4` は232フレーム／24fps、464000 PCMサンプル、完全AVデコード。保持区間内部のデコード音声は無音。原frame144と出力frame127の静止画を確認した。これは既に曲を含む入力の検証で、曲も伸縮される。楽句や音ハメの自然さ・全編の試聴は未確認。
- 全体297試験成功（52.550秒）: `retime-full-suite.log`。最終の字幕順序・ログ保全変更後は関連19試験成功（2.491秒）: `retime-final-focused.log`。スキル構造検査成功。操作説明: [RETIME.ja.md](RETIME.ja.md)。
- session候補、原素材までの多段対応、FCP時間変更、既存cue／追跡／字幕の自動移行は未接続。速度変更後の映像へ旧追跡を流用しない。追加BGMは新しい出力タイムラインへ配置する。元の実装計画全体は未完了で継続する。

## 2026-10-06: 追跡した保護領域の配置検査

- `composition_guides` に固定 `rect` と排他的な `track_path` を追加。解決時にSHAを保存し、描画・production検証で再検査する。CFR、全フレームの有効な枠、同じエフェクト前入力が必須。追跡UIは拒否し、投稿UIには固定領域を使う。
- 追跡枠を描画順・各フレームのズーム量・アンカーで変換し、測定した文字カードとの重なりとsubjectの切れを検査。split/comparisonの座標対応は未実装なので拒否する。sessionの追従ズーム提案にはtracked subject guideも付ける。
- 実素材 `output/implementation-maya/pose-protected-title.mp4` は108フレームの文字／ズーム配置検査、全245フレームの完全デコード、音声PCM一致を確認。文字を胴体へ移した案はframe 12の干渉で拒否し動画を作らない。証拠: `tracked-composition-real-evidence.json`、`tracked-composition-real-rejection.json`、`tracked-composition-real-audio-check.json`。最大ズーム付近の静止画は確認したが人の全編レビューではない。
- 統合全体283試験成功（49.941秒）: `tracked-composition-full-suite.log`。最終の未検査表示変更後は関連23試験と追跡配置10試験が成功（`tracked-composition-final-focused.log`、`tracked-composition-worker-tests.log`）。video-editingスキルの構造検査も成功。
- 保護するのは観察した枠のみ。未検出の頭・足・別人物、文字の人物追従描画や自動再配置は未実装。可変速描画と同期、実機／外部連携、リリースを含む元計画全体を継続する。

## 2026-10-06: 姿勢検出と追従ズームの接続

- Python CVの選択肢としてOpenCV CSRTにMediaPipe Pose Landmarkerを追加。モデルは明示したローカルファイルを使い、入力・モデルSHA、ライブラリ版、選択者と理由を記録する。`tracking` extraを `opencv-contrib-python` に統一してcv2の競合を解消した。
- 同一素材・同一の手前の人物の初期枠でCSRTは74/245、姿勢方式の修正版は121/245フレームまで有効。その後は喪失を維持する。79から37フレームへ悪化した中間変更を棄却し、回転時の寸法判定のみを修正した。証拠: `output/implementation-maya/pose-backend-comparison.json`、`dance-front-pose-v3.json`。全編の本人確認ではない。
- `tracked_zoom` を実描画へ接続。追跡データ・実際のエフェクト入力のSHAとフレーム区間を検査し、喪失区間や重なる別のズームを拒否する。実素材の `pose-zoom.mp4` は245フレームで、音声PCM保持と完全デコードを確認した。このデモは旧79フレーム版の有効区間を使用する。修正版の `pose-zoom-v3.mp4` は0.5〜5秒に適用し、245フレームと音声PCM一致を再検証した。抽出6フレームの枠とズーム最大付近の静止画を確認したが、人の全編視聴・試聴ではない。
- `session tracking-source` が実際のエフェクト前入力を示し、`session track-effect` が未採用候補を作る。候補レンダーまでの接続を試験し、natural/offでは追跡を開始しない。エージェントの作成を人の承認として扱わない。
- 統合後の全体274試験成功（51.792秒）: `output/implementation-maya/pose-adopted-full-suite.log`。スキル構造検査も成功。
- 動く人物を使った文字の追従・配置保護、可変速描画と音声／字幕同期、全編の視聴・試聴、FCP実機往復、外部連携とリリースは継続作業。現在の追跡を全編自動適用の品質とは扱わない。

## 2026-10-06: 配置検査・Python CV追跡・時間対応表

- `composition_guides` をproject/candidate、production、発話／visualレンダーへ接続。測定した文字カードの干渉と手動アンカーズームによる宣言人物領域の切れを拒否する。固定した宣言領域のみで、対応外の効果は未検査として記録する。
- `tracking track`／`tracking validate` を追加。ローカルのOpenCV LKとCSRTを選べる。CFR・入力SHA・連続フレーム・喪失後の手動修正を検査し、原本や既存成果物を上書きしない。依存は `opencv-contrib-python-headless` に統一し、doctorが利用可否と版を報告する。
- 同じダンス映像・同じ衣装の枠で、LKは13/72フレーム、CSRTは22/72フレームの後に喪失。CSRTの抽出6フレームは枠を目視確認したが、全編の同一人物追跡や人のレビューの証明ではない。自動追従演出に十分な品質とは扱わない。
- `compile_retime` は厳密な出力→原動画対応、ランプ／静止保持、保護区間、間引き／重複を扱う内部コンパイラー。可変速描画・音声／字幕同期・session接続は未完了。
- 全体261試験成功（57.902秒）: `output/implementation-maya/cv-full-suite.log`。実動画の追跡と喪失検証: `cv-torso-comparison.json`、`dance-torso-csrt-v2.json`。旧productionにcompositionがない場合の納品互換性を修正。
- 操作と制限は [TRACKING.ja.md](TRACKING.ja.md)、READMEとvideo-editingスキルへ反映。M0の対話／ブラウザー受入、M2のより高度な画面設計、M3の安定した追跡と描画・同期、M4の実機／外部制作連携、M5のリリースを継続する。

以下は過去の段階ごとの記録であり、当時の未完了記述を現状の完了判定へ流用しない。


基準: `ff39aa9496ed8180a8c0387f4c092643eb52f218`。目標は[計画](EDITING_PATTERNS_PLAN_2026.ja.md)の全範囲。部分提供を全体完了と扱わない。

## 2026-10-06: MAYA計画の最初の効果改善

続く実装で `comparison_wipe`（独立した登録素材、ワイプ／全画面を保つ左右比較）と `keyword_title`（実測文字カード、フェード／上昇）を追加。比較素材のSHA・尺・開始フレーム・CFR・利用ポリシー、文字色と背景のコントラスト、フォントSHA・PNG SHAを検査する。比較素材の音声は使用しない。視覚だけの比較素材を音声納品権利の対象へ誤って含めないよう修正した。

新しい実素材デモは `output/implementation-maya/m2-demo/pair-title.mp4`。245フレーム／24fps、完全デコードと音声コピーを検証。実際のポスター確認で、画角の違う素材のワイプが主役を切ることを確認し、全素材を収める左右比較を追加した。技術検査と静止画確認であり、人の全編視聴・試聴の承認ではない。

統合後の全体試験は240件成功（`output/implementation-maya/m2-full-suite.log`）。FFmpegのフィルタ能力フラグが2文字になる環境でdoctorがmix機能を誤検知する問題も修正。文字・比較の基本描画は追加したが、字幕辞書・主役／投稿UIとの自動干渉検査、追跡、リタイム、FCP実機受入、外部制作連携は引き続き未完了。

- `effects-catalog` に版付きパラメーターを追加。`smooth_zoom` は手動アンカー・拡大率・イージング、`saturation_pulse` は最低彩度・イージングを扱う。強さが実描画へ反映されることと音声保持を実レンダーで試験。
- `session effects` は登録renderを基に追加・修正・削除する未採用候補を作る。元候補の色・音を引き継ぎ、現行採用版やレビューを変更しない。
- 比較ページに同期再生・案別音声・再生位置・選択メモ保存を追加。ブラウザー実動作の受入は未確認。保存は提案であり、人の承認や自動採用ではない。
- 素材の実測durationを付けたコピーが台帳digest検査に干渉する不具合を修正。ランキングには原本台帳を渡す。
- 全体234試験成功: `output/implementation-maya/full-suite.log`。実素材384フレームの新ズーム版も完全デコード・時間・音声コピーを確認。人の視聴・試聴、FCP GUI往復は未確認。
- 追加の素材方向として、Pexelsのスタジオ・グループダンス13648584とMixkitのダンスポップ／EDM3曲を取得。原音を使わない試聴版を `output/demos/kpop-style-20261006/` に保存。曲のContent ID状態は不明であり、ローカル試聴を配布承認と扱わない。
- [MAYA計画](ADVANCED_EDITING_MAYA_PLAN_2026.ja.md)の対象領域検査、文字アニメーション、2素材比較、追跡、リタイム、外部制作連携は未完了。全体の実装目標を継続する。

## 2026-10-06: 契約とローカルミックスの統合

- 6パターンの版・定義SHA、厳密な新設定schema、明示的な好みの保存を追加。
- 素材台帳に媒体・商用・広告・帰属・Content ID・完成映像／完成音声／元素材の独立した許諾、媒体SHAと権利根拠SHAを追加。
- Pexelsの検索・取得を別許可に分けたadapter、他サービスの手動取得状態、期限付き傾向profileを追加。実サービスの検索・取得は未実行。
- `production resolve/register/validate/select/cues/trend` をCLIへ統合。
- 発話PCM結合→追加BGM／効果音→最終測定・正規化の順序を実装。音の変更をmix cacheに反映し、映像cacheは共有。
- cueを編集後frame mappingのSHAへ結び付け、尺・順序変更で古い配置を拒否。naturalは以前の追加演出を使用しない。
- MP4納品の音声単独ファイルに独立した権利ゲートを追加。production XMLの統合までFCP納品は明示的に拒否し、旧flat XMLを同じ仕上がりだと誤表示しない。

検証ログ: `output/implementation-patterns/doctor.json`、`production-render-tests.log`、`integration-tests-3.log`、`worker-assets.log`、`worker-av.log`。

生成した2秒の映像・自作toneで、未指定とnaturalのデコード映像／PCM一致、BGM追加時の映像一致・音声差、素材差し替え拒否、stale cue拒否を確認。実際の発話の聴きやすさ・自然さ・FCP GUI・配信先再生の証明ではない。

## 完了前に必須の残り

1. セッションの不変candidate保存、比較、選択者／理由付き採用、旧版復帰、レビュー依存失効。
2. beat mapのセッション登録、拍への許可範囲カット、保護発話の維持、誤差の表示。
3. visual EDLのセッションdispatchと無音声／複数素材render、元環境音の保持、適用対象別レビュー。
4. ミックスPCM差し替えXMLと編集可能な音声／映像レイヤー、roles／gain／markers、未知構造拒否、relink、GUI import／reexportの証拠。
5. portable依存manifestと許諾別handoff。映像が変わる補助素材・字幕・縦版も同じ成果物へ結び付ける。
6. doctorの追加機能診断、3スキルの共通契約、READMEの実際に動く例、wheel／sdist／skill／plugin配布確認。
7. 全要件監査、同条件比較レビュー、実素材・実試聴の未確認範囲の明示。

全体完了・リリース・人による承認は未実施。

## 2026-10-06: 比較候補とvisualセッションの統合

- 不変candidateを追加し、現行設定を変えずrender・比較できる。採用はproject／plan／brief／transcriptを正確なsnapshotへ切り替え、旧案を保持する。プレビュー採用を全編レビューへ昇格しない。
- パターンの解決後設定・定義SHAをproject snapshotへ凍結し、定義更新で旧案の演出が変わらない。naturalへの復帰では旧snapshotを解除する。
- `session visual-plan`、v4計画の選択・明示revision、無音声／複数素材render、visualのcontext・feedback・reviewを統合。元音声のある区間は維持し、ない区間を明示的な48kHz silenceで埋める。
- 素材別fps・寸法のformat resourcesとconform-rateを含むXMLを生成する。接続素材のoffsetとmarkerを親素材のsource-local時刻で表し、読み戻し時に出力時刻へ検算する。
- loopの周期を48kHz sample数へ固定し、拍変換と同じ周期を使う。継ぎ目と丸め誤差は別に記録。
- 追加音・映像の適用時には選曲、素材文脈、権利、拍の追加レビューを要求する。無音声visual版は架空の発話・字幕レビューを要求しない。
- finished-picture＋最終PCMのFCP準備関数を追加。完成音声の別配布が許諾されない場合は動画のみへ限定。FCP納品bundleへの統合はまだ未完了。

検証: `full-candidates-visual.log`（統合時169件成功）、`candidate-feedback-tests.log`（7件成功）、`patterns-final-focused.log`（13件成功）、`visual-session-end-to-end.log`（silent visualセッションをMP4納品・portable completion検証まで実行）、`worker-fcp.log`（実アプリ付属DTDとsource-local／mixed-FPS構造検算）。いずれも実素材の人によるレビューやFCP GUIの再生証拠へ読み替えない。

上の残り一覧の1・3は実装と生成素材の縦断試験が進んだ。FCP納品の依存コピー／relinkと往復session import、拍へのカット採用、CLI／スキル／配布、GUI・実素材レビュー、全項目監査は継続する。

追加統合: 共通の演出・権利・比較契約をvideo-editingスキルへ記載し、YouTube／TikTokから参照する。3スキルの構文検証は成功。`full-patterns-integrated.log`は172件成功。その後、visual原素材のライセンス・クレジットと環境音の別配布条件をproduction依存へ追加し、`source-rights-integration.log`で9件成功。原素材の音も、BGMと同様に完成音声の別配布ゲートを通す。

## 2026-10-06: 拍提案・返却XML・外部検索CLIの統合

- `session propose-beats`を追加。現行レンダー／音源SHA／配置から拍を再マッピングし、visual EDLは許可された無発話区間内の提案として保存する。選択を経ずにレンダーできず、変更後の出力対応とcueを再生成する。発話計画はマーク記録のみ。新提案・旧プロジェクト・証拠を保存し、旧音源／古いレンダーを拒否する。
- `session import-production-fcp`を追加。現行フルレンダーとXML・production・mappingを検証。返却XMLと判定結果を保持し、対応するeditable変更を未採用のcandidate changesファイルへ保存する。mixは比較のみ、未知変更は拒否。候補作成・再レンダー・比較・明示採用へ接続し、人の承認を捏造しない。
- FCP納品の依存コピーと相対メディア参照を統合。生成fixtureのmix bundleを移動し、元renderフォルダを削除しても依存検証が通る。未許諾の依存や改ざんを拒否。XMLのGUI再現はまだ別途未確認。
- Pexels `production search/fetch`を別ネットワークゲートでCLI化。現在の公式動画API `/v1/videos/search`に更新。上限付きHTTPS、redirect拒否、認証ヘッダーのメディアホスト送信拒否、一般的な接続エラー、未確認の権利状態を実装。鍵は環境変数のみ。実API通信は行っていない。
- doctorに音声filter、librosa可用性、追加CLIとPexels鍵の有無（値を含めない）を追加。README日英、共通スキル、[操作ガイド](EDITING_PATTERNS_USAGE.ja.md)を更新。

検証ログはすべて`output/implementation-patterns/`:

- `full-patterns-continued.log`: 全189件成功、26.027秒。
- `session-beats.log`: 2件成功。生成映像／音源の実レンダー、カット提案、選択、7フレームへの再レンダー、旧render拒否。
- `session-import.log`: 3件成功。Session境界はmock、XML構造は別のimporter試験で検証。
- `providers-cli.log`、`production-doctor.log`、`final-focused-continued.log`: 模擬通信、最新endpoint、サイズ上限、ヘッダー転送拒否、doctor、import境界。
- `portable-production.log`: 実生成renderとportable bundle、移動・原参照削除・メディア改ざん拒否。
- `help-propose-beats.txt`、`help-production-import.txt`、`help-production-search.txt`: 実CLI help。

FCP GUI試験の現在地: `output/implementation-patterns/fcp-gui-fixture/`に生成fixtureの納品を保持し、UI操作で`Harness Pattern QA 20261006.fcpbundle`を別途作成。作成後の画面取得がタイムアウトし、再試行でScreenCaptureKitエラー`-3811`を返した。プロセスとライブラリの存在は確認済みだが、fixture XMLのimport・再生・再exportを確認した証拠はない。既存ユーザー作品を変更せず、アプリの再起動や検証済みへの書換えを行っていない。

残る作業: GUI経路の復旧と実FCP往復、実素材の視聴・試聴、配布パッケージの新機能・privacy監査、計画全要件の監査。全体のgoalは継続中で、リリース済みとは扱わない。

## 2026-10-06: FCP GUI再確認と実素材デモの準備

GUI取得は復旧した。専用QAライブラリへmix XMLを実際にimportし、再生操作と1.14 FCPXML再exportを確認した。ただし128×128 fixtureのsequence formatに警告があり、聴感・色・無警告importの合格は主張しない。返却は `output/implementation-patterns/fcp-gui-fixture/mix-roundtrip-1.14.fcpxmld/Info.fcpxml` に保持した。

実際のFCPはprimary clipの`srcEnable=video`を落とした。そのためmix納品用に音声トラックを持たない`finished-picture.mp4`と別のfinal PCMを生成・封印し、audio-bearing pictureを納品前に拒否する。Importerはインストール済みApple DTDに一致する1.12〜1.14、`.fcpxmld/Info.fcpxml`、無害なbookmark等と色変換なしを扱う。未知の有効effectsや危険なaudio-enable変更を黙認しない。再生成した無音pictureのGUI往復は未完了。

ポリシー指定がpattern名より優先されるcue配置を追加し、intro/outro、連続音楽、実chapter境界、選択限定、疎な効果音、タグで指定されたvisual配置を区別する。音源・意味位置が不足する場合はpending理由を返す。

配布成果物はwheel/sdist・3skill・plugin ZIPのローカル生成、隔離wheel install、manifest/SHA/禁止パス/設定済みsecret値監査まで確認した。旧alpha.5名の監査用成果物であり、新版の公開はしていない。変更後の再buildと最終監査が必要。

公開無料ダンス映像（Pexels、Sergey Makashin、5359281/5359284）とMixkitのMidnight Funkを使うローカル音ハメデモを準備中。Content ID状態は未確認のまま記録する。`asset_policy.content_id_check=pending_local_review`は明示的なローカル埋込確認だけに使い、delivery packageは拒否する。ライセンス許諾とYouTubeの実際の著作権チェックを混同しない。

ユーザー指定: 投稿先は「⛄ 絶望ドメイン ⛄」（Studioで確認したchannel ID `UC0OVt-xRkc_tco_FrGMgigQ`）。一般公開の意向はあるが、**動画の投稿直前にユーザー確認を受ける**。現在はアップロードも公開もしていない。完成動画のSHA、タイトル、説明、公開先・範囲を提示してから進める。


## 2026-10-07: 投稿担当と深度合成の開発状態

最新のユーザー指定では、動画の用途を確認してローカルMP4を渡し、YouTubeへのアップロードはユーザーが行う。以前の投稿直前確認という運用はこの指定に置き換わる。用途は回答待ちで、検証用の自然版・低動作版は最終完成版ではない。

深度の開発実装は、手動の相対深度フィールド保存・検証、登録画像を近い内容の後ろへ合成する独立候補コマンドを追加。技術検証は全467テストで通過した。回転付き入力の拒否を実ファイルで検証し、合成MP4の区間・近遠表示・音声一致を合成素材で確認した。実素材の輪郭品質と人のレビューは未確認。自動推定モデル、時間方向の安定化、セッション内の採用操作は未実装。alpha.7の配布済み機能とは区別する。詳細はDEPTH_LAYERS.ja.md。全体の計画は継続中。


## 2026-10-07: ローカル相対深度の推定

開発版のdepthコマンドにfetch-model／inspect-model／inferを追加した。公式Smallの対応revisionとconfig・processor・safetensorsをコード内の既知SHAで固定し、ローカルCPU推定のみを実行する。取得CLIで実際にダウンロード・検査し、実素材の1080pダンス3フレームで推定とversion 2 artifactの検証を確認した。モデルとメディアは配布物に含めない。

生の推定値を保存し、対象区間共通のmin/maxで正規化する。rawとnormalized値の完全一致、source/frame/model SHA、独立したexecution.jsonのruntimeとmanifestの照合を行う。単独manifestのruntime捏造、任意の重みを公式版として宣言する操作は拒否する。記録はローカルの改変検知であり、第三者の署名付き実行証明ではない。

関連19テストと3スキルの形式検証が通過。旧main8349aa9のCI37485540407は3環境すべて成功。今回の新コードは全473テストで通過（186.214秒）。時間方向の安定化、近遠仮定の実映像確認、輪郭・遮蔽の合成レビュー、セッション内の採用操作と最終動画は未完了。alpha.7にはこの推定機能は含まれない。
