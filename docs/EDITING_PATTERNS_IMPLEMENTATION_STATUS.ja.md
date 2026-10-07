# 編集パターン実装の進捗と検証台帳

各項目は記録時点の状態です。直近の開発機能を先頭に掲載し、過去の未完了記録も検証履歴として残しています。公開alpha.7と開発版を区別してください。

## 2026-10-07 開発版: 全体回帰と作業ツリー外からの実素材レンダー

コード基準3b2cbba。`uv run --no-sync python -m unittest discover -s tests -v`が704件・596.188秒で成功。wheel／sdist／3スキル／Claudeプラグインの計6配布物を検証用フォルダーに生成し、アーカイブ内容・定義・checksum・設定済み秘密値の検査が成功した。公開alpha.7の配布物やtagは変更していない。検証用ファイル名は現行pyprojectの版を使うが、既存公開releaseそのものではない。

新しいPython 3.12.12環境へbase wheelをインストールし、VIDEO_EDIT_HARNESS_ROOTとPYTHONPATHを外して作業ツリー外から7項目（CLI help、doctor、効果、レシピ、プリセット、Session help、既存Session詳細検査）を確認。3スキルのZIPを別環境へ展開しdoctorで配置を確認した。独立エージェントによる3スキルの制作実行や、tracking／depth／retime等のoptional extraの新規インストールを確認したという意味ではない。

保持済みの開発Sessionをインストール済みCLIでresume。変化はgeneration／history／updated_atのみで、他の保存フィールドは不変。既存projectとplanを使い、site-packagesのwheelから実ダンス素材を全編レンダーした。1920×1080、245フレーム／24fps、10.208333秒、48kHzステレオ、全AVデコード成功。動画SHAは1144f77f09c96d3ebed0df60247e06202e5ac8e60f722a482d40687264afe5cf。これは既存の基本構成の制作経路の検証であり、新たな演出案や人の視聴承認ではない。

生ログ・配布物・復帰前後のstate・実MP4・証跡SHAは`output/implementation-maya/integration-validation-20261007/summary.json`と同フォルダーに保存。M0〜M5全体の受入、複合FCP GUI往復、Business/Symphony API実編集、人の全編視聴・試聴、投稿先再生は未完了。

当初のFCP切り分けでは音声のみ／音量自動化／画像のみ／文字のみの4XMLを準備し、DTDは成功。画面取得のタイムアウトと前面アプリ変更で、この時点では個別XMLのGUI読み込みは実行していなかった。その後、固定音量と修正した音量自動化のGUI取り込み・131キーの保持を確認し、exporterを修正した。下記追加記録とFCP_ROUNDTRIPを参照。後から取得した10:38のSIGABRT報告は接続asset-clipのXMLインポート処理を示すが、原因レイヤーは未特定。証跡は`output/implementation-maya/fcp-layer-isolation-20261007/`。準備を読み込み成功と扱わない。

## 2026-10-07 開発版: FCPのモノラル警告と管理素材コピーの往復

FCP 12.4（454072）で単一asset-clipの最小XMLをQAライブラリへ実読み込み。元sequenceのaudioLayout=monoに警告が出て、FCPから返した1.14 XMLはstereo、元assetは1音声チャンネルのままだった。新しい書き出しではmono／stereo素材をstereoプロジェクトへ出し、assetの元チャンネル数は保持。修正版の最小XMLを実GUIで警告なしに読み込み、タイムラインのsourceクリップ2秒とモノラルsource音声構成を確認した。XMLのmonoが全要素で不正という一般論にはしない。[実測と操作](FCP_ROUNDTRIP.ja.md)。

FCPが元素材をQAライブラリのOriginal Mediaへコピーしたため、最初の返却XMLはパス一致で失敗。check-fcpへ明示的なallow-media-relocationを追加し、全clipのローカル素材の実SHA／バイト数を検査し、時間対応の条件は保持。最初の実返却XMLと同じ素材・尺を持つ修正後の最小XMLの照合が成功した。修正版そのもののFCP再書き出しは未実施。両素材26605bytes、SHA a1c8e2a7ab01beabaad84f173782f1d0fac5bb9fdfe149819242b2f6a1b2afca。unknown adjust-colorConformは未検証で保持し、媒体・時間の一致を色／音／画素の一致へ広げない。

同じ修正で音量キーフレーム・画像・タイトルの複合XMLを再生成したが、読み込み直後にnoWindowsAvailable、FCP停止を確認。読み込み・再生・出力一致は未受入。現時点のDiagnosticReportsは古い07:06の報告のみで、この試行の原因を示さない。複合XMLのSHAは20d571cd6cafcd0d5916a12e4ba2509e4add0658e38ccfa3ff9b4438cde4826d。個人ライブラリへ変更なし、素材と以前の失敗を保持、再試行を繰り返さない。

関連39テストが12.187秒で成功。元monoチャンネル保持／stereo出力、同一bytesの移動／コピー、異なるbytes・素材不足・clip開始の変更拒否と従来の厳密パス比較、編集可能な音声／FCP取込の回帰を確認。共通スキル構造検査、git diff --check成功。証跡はoutput/implementation-maya/fcp-minimal-import-20261007/のobservations.json、実返却XML、roundtrip-relocated、画像、AXログとテスト／失敗ログ。API設定はこの試行でも未構成・未接続。人の試聴・複合FCP較正・全計画受入・alpha.7更新・投稿は未実施。

## 2026-10-07 開発版: 秒数で音ハメの見せ場を指定

`session beat-effects`へ`--beat-map-file`／`--cue-id`／`--at`を追加。エフェクトrequest JSONなしで、完成動画の指定秒に近い、実曲の拍の頂点フレームを選べる。既定150msの許容差を明示し、距離不足・同距離の曖昧さ・重複・保護区間・端を拒否。安全そうな別の拍へ黙示移動しない。version 2は指定時刻／選択頂点／差を封印し、version 1の描画・入力契約を維持する。`--reduced-motion`と観察済み保護区間にも対応。CLIは発話・サビ・強拍・振付の頂点を自動認識しない。[操作](BEAT_EFFECTS.ja.md)。

既存のNeon Steps＋実ダンスへ4.35秒を指定し、元音源の測定拍4.3626667秒に対応する頂点frame105／4.375秒を選択。指定と頂点の差25ms、曲の拍と頂点の量子化差12.333ms。frame100..111のズーム／彩度候補を全編描画。新動画SHAはf2f3233939878e7f0ccc7301cb544b1d36d1268d56c5bb298dc797d15e35badb。前後の完成PCM490000ステレオsampleframesとmappingが完全一致。音付き前後比較はoutput/implementation-maya/beat-time-controls-20261007/delivery/beat-time-before-after.mp4、SHA84c89a13e03a6b5312afecc9800c9b89db7001d15cc58fae2f023f8488362e00、20.4167秒／490フレーム／24fps、全AVデコード成功。前版もカットと速度編集を保持し、完全な自然版ではない。静止画で拡大の差を確認したが、人の全編視聴／試聴承認ではない。

関連29テストが25.619秒で成功。実符号化Sessionでversion2候補の描画、音声／mapping不変、証跡改変・実曲差し替え拒否、version1、距離／曖昧さ／不正値／保護／CLI混在拒否を検証。初回の拡大テストは既存test_workflowのtop-level importが失敗し、ログを保持、PYTHONPATH=testsで正しく実行して成功。共通スキル構造検査とgit diff --check成功。README・共通スキル更新。API実行・FCP GUI受入・人の全編評価・計画全体の完了・公開alpha.7更新とは分ける。投稿なし。

## 2026-10-07 開発版: 新曲に結び付いた音ハメ演出と実MP4

`session beat-effects`を追加。完成renderの登録曲SHA／実バイト、音楽cueのtrim・loop、解析結果、出力FPSへ結び付いた選択拍を使う。奇数フレーム区間の中央へズーム／彩度演出の頂点を合わせる。全区間・全拍へ自動適用せず、保護区間全体の重なり、欠ける区間、重複区間、保存済み音楽phase/audio_retime、古い曲を拒否。追加ズームを省く選択肢と、実操作・拍誤差の封印済みmotion_template証跡を保持する。[使い方](BEAT_EFFECTS.ja.md)。

実曲「Neon Steps」をlibrosaで解析（137.1951 BPM、作曲指定138 BPM）。音ハメカット32／73／126／167／209、速度変化2区間、ズーム頂点52／136／199、残像2区間、文字2区間で再編集。頂点の拍量子化誤差は最大20ms。5か所のcontact sheetでは残像と文字を観察。強拍・サビ・動作の頂点の自動認識、人の全編視聴・試聴は証明していない。

時系列版と編集後の音声付き比較MP4は`output/implementation-maya/new-song-beat-effects-20261007/delivery/04-beat-sync-neon-before-after.mp4`、SHA `db956080fce791a0827015385d6853083a677c2c1349140f1a4adb246ffab1fd`。単独版245fr／24fps、比較490fr、1920×1080。時系列・演出・追加演出を抑えた版の完成PCM490000sampleframesが一致。全4ファイルのAVデコード成功。比較音量-16.01 LUFS／-1.94 dBTP。抑えた版も同じカットと速度編集を保持しており、完全な自然版とは呼ばない。

実素材で既存カット提案のfloat→string変換が245/24秒の読み取りを壊す不具合を発見・修正し、61/24秒の回帰試験を追加。関連17試験成功（22.352秒）、doctor／CLI6試験成功（0.340秒）。初回の単体fixture不足と実素材の停止を保持。文字がズーム変換後の主役領域へ重なったため、保護を弱めずズーム終了後へ移した。カット提案後に観察済み末尾source209..245を明示選択して245出力frへ揃えた変更は、カット提案のin-point不変条件と分けて記録。元動画と既存sessionの採用中projectは保持し、新しい独立sessionへ作成した。

実ログ・修正・素材・解析・proof・比較は`output/implementation-maya/new-song-beat-effects-20261007/`。24fpsの速度編集は重複／省略フレームを含み、optical flowではない。Content ID、全編の人の受入、スマホ、FCP GUI、TikTokネイティブ音楽／編集APIは未確認。投稿・upload・alpha.7更新は行っておらず、計画全体は継続。

## 2026-10-07 開発版: 曲差し替えとシンセ曲の試聴版

比較ページに登録曲・開始秒の選択を追加。version 5は利用条件と実SHAを再検証し、元のcue尺・fade・loop・duck・SFX・映像タイミングを保持する。素材不足を自動延長せず、保存されたphase/content時計とbeat anchorは拒否する。version 4のゲイン／オフを維持。新曲の音ハメが未検証であることを候補、全編render、次の候補、配布へ保持し、`beat_sync`をoffへ更新する。新曲の拍に合わせた自動再編集やTikTokネイティブ処理ではない。

ローカルのサンプルなし手続き的作曲で138 BPMの「Neon Steps」を生成し、実ダンスの複合演出版へ適用。新render `80eea7940590`、動画SHA `b23494faf6cbdf5217f5ad147e84b0183a77e7794b5e4390964b969ca1bb275e`。245フレーム／24fps、1920×1080、音声あり、全編AVデコード成功、旧曲版と全映像画素・mapping一致。新曲への拍合わせ、人の全編試聴、スマホ再生、Content IDは未確認。生成方法と許諾は[GENERATED_DEMO_MUSIC.md](GENERATED_DEMO_MUSIC.md)。

関連20試験成功（40.315秒）：曲SHA・開始位置・素材不足・旧version拒否、UIのversion 5／取り消し、1320Hz新音源の実ミックス、映像一致、証跡改変拒否と次候補への保持、従来の比較・配布。初回の引継ぎ処理の試験失敗を保存して修正。実素材の初回は通貨不一致で拒否、再試行は証跡ファイル既存で停止、保存先整理後に成功。利用条件検証は弱めていない。生ログと素材は`output/implementation-maya/music-replacement-20261007/`。

API statusの実測はkey/secret/redirect/認可すべて未構成。ローカル曲の追加をTikTok音楽API成功と扱わない。既存のネイティブエフェクト書き出しでは音楽が入っていなかった境界も維持する。投稿・upload・人の承認・alpha.7更新は行っておらず、計画全体は継続。

## FCPの編集可能な配置・音量の実機検証準備（2026-10-07）

GUIが再取得できたため、1920×1080／30fpsの独立した2秒の合成fixtureを保存。別dialogue PCM、880Hz BGM、測定duck／fadeのキーフレーム、半透明画像とタイトルの編集可能XML、期待するMP4／WAVを保持した。最初は音声専用ミキサーへ画像cueも渡して失敗し、失敗runを保存して音声cueだけに限定したv2で準備成功。

検証用Harness Pattern QAライブラリを選び、実FCPのXML読み込み画面で対象を選択し「読み込む」が有効になった状態を確認。実行後にGUI提供側がウィンドウを取得できず、読み込み済みproject・再生・FCP書き出しの一致は確認できなかった。未受入の状態を維持し、起動やダイアログ到達をimport完了と数えない。証跡は`output/implementation-maya/fcp-live-calibration-20261007/{gui-observations.json,prepared-v2/fcp-evidence.json}`。FCP較正は計画全体に残る。

## 実ダンス素材の自然・控えめ・大胆比較（2026-10-07）

同じKarma音楽、同じ245フレームを使い、自然版、彩度／フェード文字の控えめ版、2回のズーム／短い残像／上昇文字の大胆版を作成。自然→各演出版の2本のMP4も追加。全5ファイルの完全AVデコード、24fpsの245／490フレーム、48kHzステレオを確認。単独3案のPCMは一致、比較2本とも-16.28 LUFS／-5.24 dBTP。元全画面の保護矩形で追加のズーム切り欠きを拒否し、文字は余白へ配置。残像の顔への軟化は実静止画で確認したが、人の全編視聴・試聴、スマホ、FCP GUI、Content ID、公開後再生は未確認。4種類の既存デモも保持。

証跡: `output/implementation-maya/advanced-effects-real-20261007/render-v1/{review-manifest,result,accent-evidence,bold-evidence}.json`と各raw log。自然／控えめ／大胆の同期比較ページ、局所のエージェント静止画確認を別に保存。操作と条件は[COMPARISON_DEMOS.ja.md](COMPARISON_DEMOS.ja.md)。M1の実素材評価候補であり、計画全体の受入完了ではない。

## 画像・静的タイトルの元フェードを変速へ保持（開発版）

初回変速の画像・静的title cueも元の実RGBAフレームを選択する。保持中に透明度だけ進めず、間引きでアニメーションを再開始しない。元の画像／生成タイトル画像SHA・文字・配置・透明度・フェードの変更、保存層改変、キャンバス不一致、実変速マップと異なるフレーム選択を拒否。保存なしの旧レンダーは完全な一対一の平行移動のみ。追加BGMの通常再生、未採用候補、レビュー要求を維持。編集可能FCPはphaseを省略せず拒否し、mix/video_onlyへ渡す。

関連26試験成功（34.035秒）、最終全667試験成功（406.662秒）、3スキル構造検証成功。30fps／30000/1001fpsの画像・titleで保持／間引き／1フレーム区間の保存RGBA選択が完全一致、元音声PCM一致、区間外MP4画素誤差は平均4未満。別担当の読み取りレビューで具体的不具合なし。画像の全セッション経路、重なったcue、異なるOS間のフォント再生成は追加の確認対象。生ログ`output/implementation-maya/static-fade-*.log`。人の全編視聴・試聴、FCP GUI、新公開リリースの完了を意味しない。元計画全体は継続する。

## 2026-10-07 開発版: 残像・比較の初回変速への再適用

保存した元の各描画段階を`content_map`で選び、初回session retimeの同じ段階へ接続。残像の履歴と比較動画の再生位置を新しい時計で作り直さず、保持・間引き・1フレームへの圧縮でも元の実画素を維持する。全画面置換も扱い、開始位置が同じになった複数ワイプは元の段階順を使う。

元のイベント・計画・素材・段階順、元サンプルのSHA、変速後の計画とpicture設定へ束縛。セッションは元／再配置した両層を登録する。変更したgrade、元サンプル、パラメーター、対応表、画面サイズを拒否する。旧サンプルなしの完全1対1移動は従来経路を維持する。追跡／depth／speech設定移行・多段変速合成・人の全編レビュー・FCP GUI・外部接続・次の公開版は別途残る。

関連23試験成功（36.288秒）、実画素とセッションの最終6試験成功（38.987秒）、最終の段階順2試験成功（18.857秒）。保持／間引き／圧縮を30fpsと30000/1001fpsで確認し、選択後のFFV1画素は元層の選択フレームと完全一致、通常MP4の半開区間外の画素誤差は平均4未満、元PCMは一致。最終全664試験成功（332.747秒）、3スキルの構造検証成功。生ログ`output/implementation-maya/temporal-replay-*.log`。詳しくは[RETIME.ja.md](RETIME.ja.md)。元計画全体は継続する。

## 2026-10-07 開発版: 残像・比較の元描画サンプル

残像と比較ワイプの各描画段階直後に、元の区間の実画素を同じFFmpegコマンドでFFV1/BGRAへ保存する。元入力・個別／全エフェクト計画・マッピング・比較素材、実際の順序、層のSHA／geometry／FPSへ束縛する。セッションは別ファイルとして登録し、改変を拒否する。4096フレーム超は未保存の理由を明記し、通常描画を保存済みと混同しない。

保存の有無で通常MP4の全画素・PCM一致、半開区間、重なる残像→比較の段階別画素一致、セッションの改変拒否を確認。関連12試験成功（16.963秒）、最終段階別3試験成功（2.587秒）。全体660試験成功（293.555秒）。証拠は`output/implementation-maya/temporal-sample-focused.log`、`temporal-sample-stage-order.log`、`temporal-sample-full-suite.log`。変速後の再適用とmigrationは未接続で、既存の1対1移動制約を保持する。詳しくは[RETIME.ja.md](RETIME.ja.md)。計画全体は継続する。

## 2026-10-07 開発版: 接続と実行能力の診断

TikTokの`status`／`doctor`は、認可情報の保存、有効期限、取得先ごとのscopeを分けて診断する。期限切れ時はrefresh／再認可を案内し、破損した保存情報を秘密値なしの固定エラーで拒否する。`connected`は互換の保存済みフラグで、`readiness`と`remote_verification`を実接続の証拠と混同しない。診断だけではネットワークへ接続しない。

現環境の実測ではAPI設定とKeychain認可は未登録。以前のブラウザーログインをAPI接続完了とは扱わない。FCPは起動を確認したが、GUI操作ツールがウィンドウを取得できず、実機のimport／再生較正は未確認。これらは計画全体に残る作業。

`doctor`の古いvisual_only表示を、実装済みのvisual／speech両セッションの音声・映像retimeへ訂正。編集可能FCP retimeは未対応のまま表示する。3スキルの旧「動画loop／SFX変速は未対応」という記述も現実装と整合させた。関連10試験成功（0.548秒）、全体657試験成功（290.410秒）、3スキルの構造検証成功。生ログは`output/implementation-maya/api-doctor-focused.log`、`api-doctor-full-suite.log`、`api-skill-validation-uv.log`。初回のシステムPythonによるスキル検証はPyYAML欠落で失敗し、既存uv環境で再検証した。これらは実API接続・人の視聴・FCP GUI較正・新リリースの証拠ではない。

## 2026-10-07 開発版: 動画ループと視覚cue fade

指定trimの実フレームを一度だけ出力FPSへ揃え、FFV1/BGRAの周期をstream_loopで繰り返す描画を接続。出力フレーム番号で時計を設定し、半開区間・端数FPS・透過を保持。周期の実フレーム数とSHAを記録。保存したversion2 RGBA層へloop設定と非ゼロfadeを束縛し、変速時はその実画素を選択する。旧timestamp-only loopは拒否する。

通常の動画・画像・title cueのfadeが未適用だった箇所もalpha描画へ接続。video phaseは既に焼き込まれたfadeを二重適用せず、元cue時間でfadeを検証する。画像・title fadeは新しい出力時計で適用。編集可能FCPXMLは未表現の視覚fadeを省略せず拒否し、mix/video_onlyへ渡す。

専用8件がFFmpeg9で4.371秒、FFmpeg6.1.2で1.091秒で成功。選択trimの全色順序、周期継ぎ目、端数・混在FPS、alpha、元fadeを含む短縮phase、画像・title、変化する背景のフレーム、入力/outputの全decoded PCM一致、改変の拒否を検証。FFmpeg6は既存の最小比較用buildへfade・image2・PNG/zlibを追加して検証した。全体654件が290.763秒で成功（`output/implementation-maya/video-loop-full-suite.log`）。3スキルの形式検証も成功。人の視聴・試聴、FCP実機、API連携、新リリースは未完了。

## 2026-10-07 開発版: ループ効果音の変速

ループSFXも元のcue時計で繰り返し、周期と継ぎ目のtaperを保持してから変速する。`audio_retime` version2で周期・taperサンプル数とloop内容digestを封印。version1非ループは互換読み込み。短い周期、最後の途中で切れる継ぎ目、フリーズ後の再開、元のフェード、左右の音程、音量証跡を検証。通常ミキサーのループ処理を共通化し、旧PCMとgain曲線の一致を確認。ループは新しい時計で先頭から繰り返し直さない。継ぎ目の記録は固定10msから実サンプル数へ改め、変速前／後の時計を明示する。全体646件が296.713秒で成功。その後の継ぎ目記録修正は専用15件を再検証。音声関連74件も46.918秒で成功（`output/implementation-maya/loop-sfx-audio-regression.log`）。人の試聴、編集可能FCP、再変速、公開リリースは未完了。

## 2026-10-07 開発版: 効果音の内容を変速へ追従

非ループSFXの`audio_retime`を候補移行とPCMミキサーへ接続。元のフェードを含む音を連続ランプで音程保持して変速し、フリーズ中は無音・解除後は元PCM再開。BGMは通常速度、duckは新しい声の時計。音源SHA・trim・fade・元cue区間・連続マップへ束縛し、映像の変速マップと異なる設定を拒否する。音量証跡にも設定SHAを保持。編集可能FCPへの通常速度原音代用は拒否、完成mix/video_onlyを使用。ループ・再変速・編集可能derivative stem・人の全編試聴は未完了。公開alpha.7後の開発機能であり、リリース済みを意味しない。

専用11件（Rubber Bandの左右440/660Hz速度ランプ検証を含む）、音声関連74件、設定移行13件が成功。全体641件が291.299秒で成功（`output/implementation-maya/sfx-full-suite.log`）。その後のFCPプロジェクトFPS照合追加は受け渡し6件を再検証して成功。技術検証と人の知覚評価を区別する。

## 2026-10-07: 保存済みレイヤーを変速候補へ接続（開発版）

- 動画cueのversion-2 phase mapで元の保存層を参照し、実RGBAサンプルを保持／間引きする。素材SHA・trim・配置・透明度も束縛し、保存済み画素と異なる設定を黙って使わない。層の改変は元renderと候補renderのどちらでも拒否する。旧timestamp形式は読み戻せるが、再描画には新しい元の保存層が必要。
- FFmpeg6のgeneric timeline条件が素材側のフレーム消費でも再評価される経路をソースと実showinfoで確認。変速層の表示はその開始時刻・実フレーム数・EOFで制御し、主映像を出力CFR時計にそろえる。元の通常描画は保持する。静止背景だけでなく、色の変わる背景で表示領域と未被覆領域の両方を検査する。
- 現行FFmpegの関連37試験成功（24.086秒、`sealed-overlay-native-content-seal.log`）。FFmpeg6.1.2の関連29試験成功（2.801秒、`sealed-overlay-ffmpeg6-content-seal.log`）。旧形式の読み戻しとmap合成の追加後、契約16試験成功（0.069秒、`sealed-overlay-legacy-contract.log`）。フレーム比較の許容値は緩めていない。
- 接続後の全629試験成功（336.207秒、`sealed-overlay-final-full-suite.log`）。直前の保存機能だけの状態でも全624試験成功（296.086秒、`overlay-capture-full-suite.log`）。4種類のローカル比較MP4を別々に生成し、全AVデコード・fps・実フレーム数・48kHzステレオ・音量／ピークを検査。通常YouTubeの重複見出しはv2で修正し、旧版も保存した。最新証跡は`output/demos/youtube-four-comparisons-20261007/review-manifest-v2.json`。GitHub CI・配布物・人の全編視聴／試聴・Content IDは別途検証が必要。投稿は行っていない。公開alpha.7には未収録。

## 2026-10-07: 元の出力サンプルを透明レイヤーへ保存（開発中）

- 通常の動画overlay描画と同じFFmpegコマンドで透明FFV1層も生成し、実際の出力フレーム区間を保存する。RGBA・フレーム数・寸法・fps・SHAを検査し、セッションに保存層のfingerprintを登録する。プレビュー寸法の流用、参照改変、範囲外・逆順のフレーム指定を拒否する。
- 保存を加えたMP4と従来のgraphで描画したMP4の全デコード画素が一致すること、保存したalphaから元区間の画素を再構成できることを、分数fps・ミリ秒時計の先頭CFR複製・素材alphaで検査。FFmpeg9.0.2の関連8試験成功（2.837秒）、隔離したFFmpeg6.1.2でも8試験成功（1.884秒）。証跡: `output/implementation-maya/overlay-capture-native-success.log`／`overlay-capture-ffmpeg6-success.log`。
- これは保存／リマップ部品の検証。変速候補の移行・再描画はまだ旧時計再計算を使うため、先のLinux CI失敗の解消は未証明。新方式への接続と全体検査を続ける。直前の字幕・時計修正の状態では全616試験成功（295.333秒、`caption-groups-full-suite.log`）。公開alpha.7は変更していない。
- ユーザーはYouTube向け・ダンス・エフェクト・音ハメを、それぞれ音付きの編集前後比較MP4へ分けることを指定。投稿はユーザー本人が行う。4本の最終納品・人の試聴は未完了。

## 2026-10-07: 単語IDに結び付いた字幕の区切り（alpha.7後の開発版）

- `session caption-source`で実表示の単語ID・出現番号と時刻を取得し、`session caption-groups --spec-file`で日本語／英語の区切りを未採用候補として指定する。全単語の順序・表記・完全な被覆をhashへ結び付け、未知・重複・欠落、カットをまたぐ区切り、指定語句の分断を拒否する。自動の意味理解ではない。
- 元の実単語時刻、発話retimeの単語保護フレーム、J/Lカットの実音声サンプルから表示時刻を生成する。読み時間・句読点・字幕重なりは警告とし、時刻や発話を自動変更しない。SRTと字幕証跡のSHAをセッション・納品で照合する。通常YouTubeは別SRT、縦型の焼き込みと実機確認は別工程。[操作と制約](CAPTION_GROUPS.ja.md)。
- 関連29試験成功（16.069秒）: `output/implementation-maya/caption-groups-final-focused-success.log`。合成発話の候補・変速・未採用状態、映像SHAの不変、実SRTと証跡の改変拒否、納品コピーを検査。全体検査・人の理解／読みやすさ・実機UI・最終MP4は未証明。
- 前回動画overlayのcommit `f467d38`のCI37514812521はUbuntu3.11のフレーム比較3件で失敗。隔離したFFmpeg6.1.2で混在fpsとミリ秒時計の2件を再現。区間先頭の同期初期化と、音声負時刻による入力PTSのずれを調査し、先頭のCFR複製との対応を引き続き修正する。比較閾値は維持。公開alpha.7の資産は変更していない。全計画は継続し、YouTube投稿はユーザー本人が行う。

## 2026-10-07: 動画overlayの素材フレームを変速後へ移行（alpha.7後の開発版）

- 動画cueの`phase_map`に元区間のフレーム番号と、元の描画入力から実観測したtimebase／timestamp配列を保持する。素材を従来のtrim・配置・透明度・FFmpeg framesyncでRGBA透明層へ描画し、rawフレームを間引き／複製してlossless FFV1層を作る。最終MP4は通常のエンコードを通る。元素材の音を追加せず、元の音声をコピーする。
- 異なる素材fpsで粗い時計を使うと未来フレームが選ばれる不具合を、フレームごとに大きく色が変わる素材で再現し修正。元の実時計を保持し、元／新cue開始が違う場合、ミリ秒時計、素材alphaを検査。素材SHAをstreamingで前後検査し、コマンド／stderrをローカルログへ残す。
- visualセッションも`overlay-evidence.json`を書き、SHAを登録・再検査する。証跡のない古いrenderは元設定で再描画が必要。元／新4096フレーム上限、非ループ素材の必要尺は元区間で検査。動画ループとeditable FCP変速は明示拒否し、mix/video_onlyを使う。
- 関連35試験成功（18.873秒）: `output/implementation-maya/video-cue-phase-coarse-clock.log`。セッション候補の実描画、採用状態不変、時計証跡の改変拒否、元と同じPCM、60fps／30000/1001と24fps混在、粗い時計、alpha、保持／間引きを検査。旧形式のFPS省略を受け入れる互換性修正後、関連14試験成功（20.479秒）と全604試験成功（275.934秒）: `video-cue-phase-compatibility.log`／`video-cue-phase-full-suite-final.log`。SFX・ループ・残像・通常cue fade・追跡／発話設定の移行、実素材の受入、最終MP4等の全計画は継続。公開alpha.7には未収録。

## 2026-10-07: keywordタイトルのフェード・riseを変速へ追従（alpha.7後の開発版）

- keywordタイトルもvisual retime移行の`phase_map`へ接続。PNG入力に元の相対フレーム時刻を与えて既存FFmpeg fadeを通し、出力時計へ戻す。riseの描画位置／測定boundsも同じ元フレームから計算する。既存の非変速タイトル描画は保持する。
- 整数フレーム時計を明示し、30000/1001で小数PTSが切り捨てられる1フレームのずれを修正。元1フレームの透明タイトルを複製しても表示しない。途中から見えるタイトルの新区間先頭を衝突検査から除外せず、複製した元透明フレームは対象外にする。その他のfadeフレームは保守的に可視として扱う。
- 関連30試験成功（4.406秒）: `output/implementation-maya/retime-title-integer-clock.log`。実60fps／30000/1001、nonzero開始、保持／間引き、途中から可視、1フレーム保持で文字ROIの画素とriseの位置を検査。全594試験成功（264.232秒）: `output/implementation-maya/retime-title-full-suite.log`。最後に可視フレーム区間を全フレーム集合を作らず保持する変更後も関連30試験成功（4.550秒）: `retime-title-final-closure.log`。6配布物監査、3スキル形式、クリーンwheel smokeも成功。前回`d068d62`のCI37508827629成功を読み戻し確認。通常cueのfade・動画overlay／効果音の素材変速、追跡・発話設定移行、実素材の人の全編レビューと最終MP4は継続する。公開alpha.7には未収録。

## 2026-10-07: 変速後の既存演出とパルス位相の移行（alpha.7後の開発版）

- visual `session retime`の既定`--timeline-settings migrate`は、実renderの対応表へ束縛したcue・固定保護領域を元区間の逆フレーム対応で移行し、採用中のprojectを変更しない。候補に旧／新対応表SHA、区間、actor／理由、元render SHAを持つ改変検査済み証跡を保持する。明示`clear`は失効項目を返す。
- `zoom_pulse`／`smooth_zoom`／`saturation_pulse`は元区間の相対フレームを`phase_map`に保持し、静止保持で演出値も保持、加速で元値を省略する。元のパルスを新しい尺全体へ再配分しない。元／新区間4096フレーム、FFmpeg式65536文字まで。追跡領域の衝突検査も同じ位相を使用する。
- BGMは元素材開始から新しい出力時計で通常再生し、既存拍基準は宣言済みcue相対オフセットを保持する。曲を映像と同じ速度に伸縮する機能ではない。動画overlay／効果音／比較wipe／残像／keywordタイトルは完全な一対一平行移動のみ対応。素材内容、タイトルの動き、フェード自体の変速は引き続き実装対象。古い対応表、消失区間、曖昧な映像拍基準、追跡、深度、発話設定の移行を拒否する。
- 全586試験成功（262.611秒）: `output/implementation-maya/retime-settings-full-suite.log`。実FFmpegのズーム・彩度の旧／新フレーム比較、候補描画の実対応表SHA、採用状態不変、証跡改変拒否を検査。6配布物の監査、3スキル検査、クリーンwheel smokeも成功。人の見た目・試聴受入、FCP GUI、YouTube用途の確定、最終MP4、全計画の完成は未証明。YouTube投稿はユーザー本人が行う。公開alpha.7には未収録。[操作と制限](RETIME.ja.md)。

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


## 2026-10-07: 深度の改訂とセッション連携

開発版にフレーム単位のdepth correctと、session depth-layerによる未採用候補作成を追加。親artifactの来歴を保った反復修正、graded pictureのSHA照合、画像の権利・visual_assets制約、色補正後／字幕前の合成、比較・選択・採用、最終SHAに対するdepth_contoursレビュー、baked納品へ接続した。納品用の深度証跡はローカルパスを除き、フィールドとフレーム/SHA対応を保持する。モデルと元画像は外部参照。

関連18テストと全482テスト（199.868秒）が通過。納品完了時の深度パスを除く最終修正も、関連9テスト（18.678秒）で通過。3スキルの形式検証と静的レビューも通過。実写3フレームの静止画では奥の出演者も低い深度になり、標準しきい値で人物全員を保護できる証明は得られていない。時間方向の安定化、人による全編の視聴・試聴、完成MP4は未完了。alpha.7の公開済み機能とは区別する。ユーザーがYouTubeへアップロードするため、こちらから投稿しない。


## 2026-10-07: 深度の時間方向の補正候補

開発版にdepth stabilizeを追加。OpenCVの往復フロー・明るさ差・局所模様・画面外を検査し、有効画素だけ前フレームの深度を動きに合わせて混合する。割合が不足したフレームと明示カットでは履歴をリセット。以前のカットは反復補正・手動修正を通じて保持する。version 4は元manifest・設定・OpenCV版・各フレームの有効割合を記録し、検証時に実映像から再計算する。納品証跡にも設定・リセット理由を保持する。

関連16テスト（36.368秒）と静的レビューが通過。初回2回のテストは、リセットしたフレームを補正済みと期待した試験箇所で失敗し、実際の有効割合を調べてリセット／補正の両方を検査する形へ直した。動作のしきい値は緩めていない。全489テスト（225.715秒）が通過。その後の再計算中の元映像／フィールド変更検出も関連17テスト（38.348秒）で通過。3スキル形式検証、wheel／sdistビルド、素材・モデル混入検査、隔離環境のwheelインストールも通過。

実写24フレームは初期設定で全リセット、有効割合0.156～0.235。明示的なmin-coverage=0.15では23フレームを補正した。静止画差分の確認と再計算一致は技術証拠であり、合成輪郭の改善、人の視聴・試聴、完成MP4の承認ではない。alpha.7には含まれない。元の全体計画と最終動画は継続中。

## 2026-10-07: 指定語句を保つ縦型字幕の折り返し

開発版のtiktok-exportに任意のcaption-layout設定を追加。日本語・英語を明示し、実フォントの文字幅・縁取り・はみ出しを測って、英単語・数値と単位・指定語句・Unicode書記素を保って折り返す。日本語の基本禁則を扱う。元のSRTの内容・時刻と音声を保持し、512コードポイント／820px／3行を超える字幕は切り捨てず拒否する。設定を省略した従来描画も保持する。操作例と制約はCAPTION_LAYOUT.ja.md。

納品用portrait-caption-layout.jsonには映像・元result・字幕・フォントのSHAと実際の行を残す。未知のネストしたフィールド、ローカルパス、未使用の保護語句とその設定全体のハッシュをコピーしない。既存の納品全体を匿名化したという意味ではない。移動後の検証と証跡改変の拒否を試験した。

全498テスト（231.196秒）が通過した後、証跡の許可フィールドと長文入力制限を追加し、最終関連38テスト（3.425秒）が通過。最終ツリー全体のCIは別途確認する。3スキル形式検証、wheel／sdistビルド、素材・モデル等の禁止メンバー検査、隔離wheelインストールも通過。合成字幕の静止画で指定語句の保持を確認したが、人のレビュー、全JLREQへの適合、投稿先UIの安全領域、意味に沿った発話区切り、完成MP4の承認は未達。公開済みalpha.7には含まれない。動画の用途は回答待ち、YouTubeへのアップロードはユーザーが行う。

## 2026-10-07: 編集可能FCPの静的な配置

字幕機能のcommit16f6fe9に対するCI37497455027はLinux/Python3.11・3.13、macOS/Python3.12の3環境すべて成功した。

開発版に、プレビューとFCPXMLで共通の静的な画像・動画・タイトル配置を追加。素材の実サイズ、整数への丸め、YUV420の座標丸めを使い、大きさ・位置・透明度を接続クリップに記録する。戻りXMLは素材のSHA・サイズ・配置を照合し、未知の変形、無視される場所のノード、別spineのノードを拒否する。画面の70%×50%の既存配置を維持する。これは投稿先UIの安全領域や人物保護の保証ではない。

動画素材は表示フレームレートだけでなく全フレームの実際の時刻を検査する。4秒120フレームから1枚を落とした合成素材では平均FPS差が1%未満になり、平均値だけのガードを通ることを確認した。実フレーム時刻のガードは拒否する。非ゼロ開始、回転、非正方形ピクセル等の対応外素材も拒否する。

配置の実描画・XML改変拒否・素材の時刻の関連25テスト（4.880秒）、全512テスト（222.780秒）が通過。その後の実フレーム時刻ガードと追加試験は、最終関連31テスト（5.009秒）で通過した。最初の新規描画試験はFFmpegが受け付けないseek指定.5で失敗し、0.5へ直した。レンダラーの判定は緩めていない。3スキル形式検証、6配布物の検査、wheel隔離インストールも通過。最終ツリー全体のCIは別途確認する。

生成証跡はpending_fcp_gui_calibrationを保持する。Apple資料とDTDを参照した変形座標・倍率の実FCP表示は未校正で、GUI画面取得がcgWindowNotFoundで失敗した。XML検査や合成素材だけで表示一致を主張しない。BGMダッキング、ループ継ぎ目、ピーク抑制、最終音量補正の編集可能FCP再現は次の未完了工程。詳細はFCP_OVERLAY_PLACEMENT.ja.md。alpha.7の公開済み機能とは区別する。最終動画の用途は回答待ち、YouTubeへはユーザーがアップロードする。

## 2026-10-07: 実際の音量変化とミックス入力の保存

配置機能commit354af1dのCI37499877191はLinux/Python3.11・3.13とmacOS/Python3.12の3環境で成功。Appleのanimation資料を確認し、静的配置の位置を素材高さではなくプロジェクト高さの百分率へ修正した。実FCP表示の校正は未完了のまま保持する。

開発版の音声キュー描画は、実ミキサーの相対音量・フェード・ダッキング・ループ継ぎ目を48 kHzサンプル配列へ記録する。全体のピーク抑制は別係数として保存。入力の声／環境音、素材、ミックスWAV、時刻と設定をSHAで結び付ける。発話編集のキャッシュ利用でも必要なWAVと配列を検査して復元し、セッションのrender証跡に登録する。保存の有無で既存PCMが変わらないことを確認した。manifestはパスを含まないが、ローカルのaudio-gain-evidence.jsonはパスを含む参照情報であり、公開配布用の匿名化証跡ではない。

関連51テスト（21.020秒）、最終全536テスト（242.444秒）が通過。3スキル形式検証、wheel／sdistビルド、6配布物の混入検査、隔離wheelインストールも通過した。数値境界のレビューで有理数の半サンプル時刻が浮動小数点化によりずれる箇所を直し、ミキサーと同じ有理数丸めの試験を追加した。最終音量補正前の保存に限定し、編集可能FCPの音量キーフレーム・処理済みステム・最終補正・GUI再生一致は継続中。操作と制約はAUDIO_GAIN_EVIDENCE.ja.md。alpha.7の公開済み機能とは区別する。人の試聴・最終動画の承認は未達。動画用途を確認中で、完成MP4を渡し、アップロードはユーザーが行う。

## 2026-10-07: 最終補正前のFCP音量キーフレーム

開発版はfcp_handoff=editableとfcp_audio_automation=measuredを明示した場合に、保持した音量配列をループごとの素材時刻へ変換する。線形dB補間で全サンプルの係数を再計算し、絶対誤差2e-5以下を検査。ゼロの-96 dB近似、+24 dB上限、1部分20,000点／全体200,000点／1,000部分上限と計算量の上限を明示し、満たせない場合は拒否する。保持した声のPCMを別トラックに接続し、共通ピーク抑制を声と各キューへ適用。元の主映像の音声はXMLで無効にする。最終ラウドネス補正は再現せず、pre_normalizationとpending_fcp_gui_calibrationを記録する。

関連37テスト（19.863秒）、全547テスト（243.382秒）が通過した後、セッション設定の許可・証跡を用いたキーフレーム削除検出・素材末尾の厳密検査・全体の出力上限を追加。重なるキューとループの証跡をXML走査順で比較してしまう問題を修正し、時刻とSHAによる照合に変更した。最終関連41テスト（10.861秒）が通過した。DTD検査、ループの素材時刻、重なるキュー、改変拒否、セッションの候補／設定変更を含む。最初の有理数時刻の試験は同値の未約分表記を期待して失敗し、試験を有理数としての比較へ直した。座標や補間の判定を緩めていない。

最終ツリー全体のCIと配布物検査は別途確認する。画面取得は今回もcgWindowNotFoundで失敗し、実FCPでの補間・音源の読み出し・元音声の無効化・音量点の再生確認は未達。この音量キーフレーム付きXMLの戻りインポートは黙って削除せず拒否する。処理済みステム、最終音量補正、実際の音声比較と試聴は継続中。alpha.7の公開済み機能ではない。完成MP4の用途は回答待ちで、投稿はユーザーが行う。

## 2026-10-07: 一定倍率の最終補正と音量点を保持した読み戻し

commit1aaeae0のCI37502587768とcommit ee2409fのCI37504081601は完了・成功を確認した。

開発版は、音声キューのある描画で補正後・AAC圧縮前の48 kHzステレオ浮動小数点WAVを保持する。キャッシュの必要ファイルとして照合・復元し、補正前後の音声を全サンプルで比較した証跡をセッションへ登録する。最小二乗で測った共通倍率が全サンプルの誤差2e-6以下に収まる場合だけ、FCPの声と各キューへその倍率を反映しscalar_normalizedを記録する。チャンネル別の変化・クリッピングなど一定倍率で説明できない場合はnon_scalarを記録し、XMLはpre_normalizationのまま。無音から音が生じた場合は倍率を捏造しない。音量目標の達成、ステム合算、最終AAC、実FCP再生との一致とは別の数値検査である。

生成した音量点、音声範囲、声のSHAと音量、主映像の音声無効化を保持したXMLの戻りインポートを追加した。既存の対応範囲で映像キューの長さ等を修正し、未採用のレビュー必要候補として扱える。音量点・音声範囲・声の差し替え・隠れたparam値の追加は拒否する。同時刻キューの比較はIDで同順位を処理し、測定時のサンプル丸めを元のキュー時刻へ書き戻さない。

最終関連47テスト（27.566秒）と最終全570テスト（252.548秒）が通過。初回は映像側の証跡を排他的writerへ二度書いた箇所と同時刻キュー順序で失敗し、単一書き込みと同順位処理へ直した。その後の試験は未補完の合成cue設定／リスト順序を期待した箇所で失敗し、通常のvalidate_cuesとID照合を使うfixtureへ直した。3スキル形式検証、wheel／sdistビルド、6配布物の混入検査、隔離wheelインストールも通過。最終CIは別途確認する。動的補正の処理済みステム、任意の音量点変更の取り込み、実FCP再生、実写動画の試聴と完成MP4は継続中。alpha.7には含まれない。用途は回答待ち、YouTubeへはユーザーがアップロードする。

## 比較ページのエフェクト調整（2026-10-07 開発版）

`effects` 比較ページに強さ・個別オフ・直前取り消し・候補単位のリセットを追加。version 2 選択 JSON を既存 `select-comparison` へ読み込むと、正確な動画 SHA と選択元の設定・計画を保持した未採用候補になる。通常レンダーと別の採用・正確な出力レビューが必要。version 1 選択は継続対応。元の候補や映像は保持する。保存済みリタイムの時計・効果全体のキャプチャに依存する候補は調整対象外。区間・位置・BGM 調整、区間だけのレンダー、端末上の人の操作レビューは未完了。[操作と制約](COMPARISON_ADJUSTMENTS.ja.md)。公開 alpha.7 には含めていない。

検証: 合成素材の修正前後で実画素差・同じデコード済み音声・同じ対応表を確認。不正な操作は候補・採用状態を変えず拒否。既存 version 1 と発話コンテキスト復元を含む全 674 テスト成功（375.145 秒）。生成された JavaScript の案別保持・強さ・オフ・取り消し・リセット・JSON 出力を Node の DOM アダプターで確認し、スライダー精度と一操作単位の取り消し修正後も再検証成功。3スキルの構造検査成功。これは実ブラウザー・スマートフォンでの人の操作受入や動画の全編目視・試聴を意味しない。

## 修正区間の音付き比較（2026-10-07 開発版）

`session preview-effects` は version 2 の比較修正候補と、調整元・修正版の全編レンダーを検証して、変更区間の前後比較 MP4 と HTML を生成する。削除した効果は元の区間を参照。選択対象・余裕フレーム・映像 SHA・対応表・元の素材範囲を保存。再生・音声切替・シークは区間内の比較であり、全編 SHA に対するフィードバック／承認とは別。30 秒超過・古い参照・異なる設定や対応表・プレビュー版のみの入力は拒否する。

完成 MP4 の出力フレームを切り出すため、効果・音楽の時計を短い区間へ再適用しない。音声は親の出力時計を 48 kHz の最近接サンプルへ対応させ、視聴用 AAC に再符号化。元の完成動画は保持する。失敗時は映像・HTML を除去し、ログと失敗結果を残す。生成済み全編を用いた確認であり、区間だけの高速再レンダーは未実装。8-bit yuv420p の完成映像が対象。スマートフォンの人の操作受入、FCP実機比較、全編の人の目視・試聴は別途必要。[操作](COMPARISON_ADJUSTMENTS.ja.md)。公開 alpha.7 には含めていない。

検証: 30000/1001 fps の連続映像から指定した区間と最終1フレームを切り出し、親のデコード済み画素との完全一致を確認。削除した効果の元区間と変更前後の同じ対応表、候補・採用状態の不変、失敗した映像／ページの除去、ログ保持、最終検査での親変更検出、既存出力の保護を検証。全 675 テスト成功（375.921 秒）、最後の失敗処理修正後の関連 9 テスト成功（16.327 秒）、共通スキル構造と CLI help 検証成功。実ブラウザー・スマートフォンでの人の操作受入や全編の試聴とは別の証拠。

## 比較ページの区間・位置指定（2026-10-07 開発版）

通常効果の出力フレーム区間と、smooth_zoom の正規化アンカーを version 3 選択 JSON で反映。version 2 は強さ・オフの従来契約を保持。未知のパラメーター・片側だけの時刻・不正なフレーム・位置を拒否し、最小長や対象範囲を既存 resolver で検査。追従の範囲変更と保存された phase/content 時計は対象外。ページは日本語の効果名、範囲・位置入力、案別保持、取り消し・リセットに対応。プレビューは元の区間と変更後の区間を両方含める。BGM、追跡対象、速度のページ調整や区間だけの高速再レンダー、実端末の人の操作受入は未完了。公開 alpha.7 には含めていない。

検証: パターン映像の同じアンカーで区間だけを移動し実画素差を確認。次に同じ区間でアンカーだけを変更して実画素差を確認。デコード済み音声の一致、旧・新区間を含むプレビュー、採用・レビュー状態の不変、不正な時刻・位置・任意パラメーター拒否を確認。生成 JavaScript では 30000/1001 の正確な時刻・version 3 出力、取り消し・リセット、不正入力の保存停止を検証。最初の全体検査で旧セッションの空エフェクト比較2件を検出し、フレーム情報を不要な経路へ要求しないよう修正。修正後の関連17テストと全676テスト（386.482秒）、共通スキル構造検査が成功。実端末の人の操作・全編目視／試聴とは別。

## 2026-10-07: 効果の変更区間を先に描画する（開発版）

`session preview-changes SESSION CANDIDATE_ID` は version 2/3 の比較修正候補から、未採用の変更区間を描画する。元の全編レンダーが記録したエフェクト入力 SHA と一致する保存映像と完成音声を再利用し、効果・残像の元の時計と色調整／中間符号化の順序を保持する。変更前・変更後の両区間を含め、前後 MP4・音声切替 HTML・SHA 付き証跡を生成。区間のみは全編レンダー一覧へ登録せず、採用条件も満たさない。全編描画と正確な出力レビューは別途必要。古い参照・保存入力の喪失・効果以外の変更・30秒超過は拒否する。公開 alpha.7 には含めていない。

測定: 同じ12秒960×540/30fps合成映像と候補、変更区間90〜149フレームを直列で各3回。全編の中央値9.265633秒、最終区間確認4.682672秒、約49%短縮。元の区間末尾まで処理するため、後半や長い映像への一般的な速度保証ではない。通常CRFの符号化境界による画素差があり、対応全編画素とのPSNRは38.64dB。完成音声から同じ区間を切り出したデコードPCMは一致。可逆圧縮による効果グラフ検査では残像履歴・色変化の位相の画素一致を確認。全編の人の目視／試聴・実端末操作・FCP実機検証とは別。証跡: `output/implementation-maya/effect-window-performance/`。[操作と制約](COMPARISON_ADJUSTMENTS.ja.md)。

### ユーザー評価による優先順位の修正

2026-10-07のユーザー評価は「エフェクトとTikTok APIの活用が弱く見える」。機能数・テスト数を映像の満足度へ置き換えず、次の受入は実素材の演出差と公式機能の実行結果を優先する。現在の4本のダンス／エフェクト比較は追従ラベル・控えめズーム中心で、ダンス向け複合演出の代表受入とは扱わない。

再確認: ローカル `tiktok-api status` はクライアント／Keychain未構成・未接続。既存の開発者Sandboxは `user.info.basic` / `video.list` とテストユーザー登録まで。ブラウザーのログインをAPI接続・ネイティブ演出適用と呼ばない。[Direct Post仕様](https://developers.tiktok.com/docs/en/content-posting-api-reference-direct-post)のリクエストは投稿設定・素材転送であり、曲／エフェクト指定を含まない。[Symphonyエディター](https://ads.tiktok.com/resources/help/article/how-to-edit-videos-with-symphony-creative-studio)は音楽・区間エフェクトを備えるが、Studio画面の機能をAPIのエンドポイントとして推測実装しない。[公式Symphony API入口](https://ads.tiktok.com/creative/creativeCenter/tools/api?aioChannel=creative_center)と[公式Business API音楽合成](https://www.postman.com/tiktok/tiktok-api-for-business/request/hvcbkdi/video-soundtrack)は別経路として利用権限・仕様・用途を検証する。

当初の実ブラウザーではSymphony編集画面がBusinessログインへ戻った。TikTokログイン経路はDM管理・投稿管理・設定変更・広告作成公開と規約同意を要求したため、権限付与せずメールログインへ戻し、既存Businessアカウントのログインをユーザーへ依頼。この時点の証跡は `output/implementation-maya/effect-window-performance/tiktok-live-audit-20261007.json`。その後の実編集・書き出し確認は下記に分けて記録する。

2026-10-07の再確認でSymphonyログイン済みの制作画面へ入れた。Stockの21.9秒ダンス素材にNightclubの区間エフェクトを追加し、横方向ブラーと効果レイヤーを確認。Downloadした実MP4は1080×1920、30fps、657フレーム、全AVデコード成功、SHA-256 `73567571e63d2bba409b1bc6019859dc8e4a6b157f214960e87bb7cb6af40ad3`。K-popカタログの検索／選択はできたが音楽レイヤー追加は未確認で、完成MP4は実質無音（−91 dB）。Studio UIでの効果適用の証拠であり、編集API疎通・音ハメ完成・人の全編受入・YouTube用途の権利確認を証明しない。ローカル素材送信・配信投稿なし。証跡は `output/implementation-maya/tiktok-native-live-20261007/`。同時点のdoctorはAPI未構成・未接続。

開発版の外部仕上げ返却経路: `native-inspect`が取得MP4の全AVデコード・音声ピークを検査し、`session native-result`が既存提案と元／返却SHAの申告へ結び付けて動画・申告・検査・生ログを保持する。提案には新しいIDを付け、旧形式はartifact SHAでも指定可能。音声なし／ピーク−90 dB以下では音楽入りの要求を`requested_music_not_demonstrated`と示す。音があるだけで選択曲や効果の適用を確認済みとはしない。元の時間対応・字幕・拍・追跡・レビューを継承せず、採用中project／plan／renders／reviewsを変えない。外部処理のAPI申告も実API応答の証明ではない。改変はstatus／resumeで拒否する。

関連14テスト（1.602秒）で実MP4の音あり・無音・音声なし、CLI取り込み、旧提案、SHA不一致／未知効果／認証query拒否、検査中差し替え、保存動画改変、壊れたMP4／ネットワークプレイリスト拒否、採用状態の不変を確認。共通スキル構造検査成功。実際のSymphony取得MP4を新CLIへ通し、21.9秒・全AVデコードpass・ピーク−91 dB・`requested_music_not_demonstrated`を確認。証跡は `output/implementation-maya/native-result-import-20261007/`。このStock動画を無関係なローカルSessionの返却として登録していない。Business／Symphony API接続、人の全編視聴・試聴、権利・配信確認とM4全体の受入は引き続き未完了。公開alpha.7には含まない。

区間描画の最終検証: 全678テスト（452.220秒）、共通スキル構造検査が成功。最終コードの3回再測定は4.597557〜4.803436秒、中央値4.682672秒。元の全編基準との比は1.98倍、時間短縮49.46%。測定は上記の単一合成ケースに限定。`candidate-final.json` / `validation-final.json` と全体ログを保存。

## 実ダンスの複合演出比較（2026-10-07 開発版）

Pexelsの既存登録済みダンス素材（245フレーム、24fps）とMixkit Karmaの既存権利記録を検証し、Session経由で比較を生成。元映像全体を1920×1080の余白付き画面へ縮小し、元音声を除去、比較両側へ同じ曲の同じ区間を配置した。編集後は6ショットへの組み替えと音楽の測定拍に合わせた5か所のカット、2か所の0.5→1.5／1.5→0.5速度ランプ、2ズーム、2残像、DROP／MOVE文字。カット変更で振付の時系列は変わる。ランプは24fps素材の複製／省略で、光学フローは使用していない。動作のピークや振付との音楽的適合は人の視聴・試聴待ち。

実素材で見つかった2件を修正: 全編FCPXML生成の小数秒丸めによる末尾拒否、および速度マッピング断片をショット境界と誤認する新規残像の拒否。新しいvisual変速候補はversion 2で真のショット境界を保持し、旧version 1の再現経路は維持する。実際のカットをまたぐ残像と文字／保護領域の衝突は引き続き拒否。旧v1レンダーの比較証跡は`legacy-retime-comparison.json`へ保存。

比較納品は`output/implementation-maya/compound-dance-20261007/delivery-v2/03-effects-compound-before-after.mp4`。20.4167秒、1920×1080、490フレーム/24fps、48kHzステレオ。比較元両側の完成PCMは490000サンプルフレームずつ一致。比較MP4の全映像／音声デコード成功、測定値−16.10 LUFS／−5.60 dBTP。SHA-256は`979e2625c1c30c44f7441acc36e0f4a43e8b107e6d90e146b090eef5c59dcd5e`。生成手順・失敗ログ・候補／レンダーの証跡を同フォルダーへ保持。エージェントの静止画確認は実施したが、人の全編目視／試聴、Content ID確認、配信先再生、FCP GUI受入は未実施。候補は未採用、アップロード／公開なし。TikTokネイティブの音楽／エフェクト適用ではない。公開alpha.7には含まない。

修正後の全680テスト（412.577秒）と共通スキル構造検査が成功。独立した読み取り専用コードレビューで具体的な正当性の不具合は未検出。5カットと自動検出した拍のフレーム丸め差は最大20msで、`beat-cut-evidence.json`に保存。拍位置の一致は振付との適合や人の試聴承認を意味しない。

## 比較ページの動きの速さ（2026-10-07 開発版）

ズーム／彩度演出へ「短く・速め／元の長さ／長く・ゆっくり」の効果時間ボタンを追加。現在の区間中心を保ち、元の長さを固定基準に整数フレームへ変換するため、連続クリックで縮み続けない。強さ・アンカー・映像とBGMの速度は維持し、既存version 3の区間修正として保存。立ち上がりと戻りの独立調整ではない。手入力済みの不正範囲、範囲外・最小長未満は拒否。取り消し／リセット／オフと開始・終了欄の更新を検証。追従やphase/content時計は対象外。

実ダンスの45フレームズーム[77,122)を、同じ中心99.5の23フレーム[88,111)へ変更し、Session経由の未採用候補を全編描画。修正版映像SHAは`fce5a6f3e8d79e3a0856ae0c02030b14aff16d79e481881fec2e76ddd069591d`。対応表・デコードPCMの一致、全AVデコード、採用中project／reviewsの不変と変更区間プレビューを確認。証跡は`output/implementation-maya/effect-speed-controls-20261007/`。Nodeによる端数FPS保存・反復・undo/reset・失敗拒否と関連全9テスト（27.354秒）、スキル構造検査が成功。独立レビューで発見した不正な手入力範囲の黙示修正を直して再検証。実ブラウザー／スマートフォンでの人の操作受入・全編視聴／試聴・ネイティブTikTok適用は未実施。公開alpha.7には含まない。

## 比較ページのBGM修正（2026-10-07 開発版）

既存の音楽cueへ強さ（−60〜12 dB）／オフを指定し、取り消し・リセット・案ごとの保持を接続。BGM変更を含む選択はversion 4で、旧version 1〜3も維持する。元音声／効果音の設定、音楽の素材・切り出し・フェード・duck・配置・ループは維持。最終正規化は全ミックスの音量を変え得るため、元音声との相対強度と絶対音量を区別する。正規化なし、または正確なレンダーに封印したmix-evidence／production-mixの元音声RMSが非ゼロの場合だけゲインを提供。正規化されたBGMだけの素材や検査が不明な場合はオフのみ。RMSから発話や試聴品質を推定しない。cueのphase_map／audio_retime、効果のcontent_mapはこの操作から保護する。

関連14テスト（41.917秒）成功後、比較ページへの実データ接続を追加確認し、対象3テスト（8.645秒）が成功。合成440 Hz元音声＋880 Hz音楽の全編レンダーで−12 dB指定が周波数成分の比率を変え、全画素と対応表を維持すること、音楽オフ、未知／重複／SFX ID・不正ゲイン拒否、封印mix検査の改変拒否を確認。Nodeでversion 4の保存・オフ・undo/reset・候補切替・不正入力拒否を確認。元の完成音声を使う効果区間プレビューはBGM変更を拒否し、全編レンダーと新音声の確認を要求する。

実ダンスの複合演出版48fe6409ff07からBGMを外し、未採用レンダー2c05692bb522を作成。全画素SHAと対応表が元と一致、全AVデコード成功、音声は−91 dBの実質無音。出力SHA-256は8929e81d33f0b2bc1135735779a3d60bd0ce1abd92d34864901aa90df8231028。採用中project／reviewsは不変。証跡はoutput/implementation-maya/comparison-music-20261007/。この元映像は無音なので、ゲイン操作は表示せずオフを提供。README・共通編集スキルを更新し構造検査成功。人の全編視聴／試聴と実ブラウザー操作、曲差し替え・拍再計算・BGM区間の高速ミックス、TikTok編集API、M0〜M5全体の受入は未完了。公開alpha.7は変更しない。

## TikTok Studioの実音楽・エフェクトと返却前後診断（2026-10-07 開発版）

先の実質無音の失敗を保持し、Studio内蔵Stock素材で再検証。Audioの「Pick music for me」で実音楽レイヤーが入り、音楽のみ基準版と短いNightclub効果版を別々にダウンロードした。個人素材のアップロード・公開なし。基準版SHAはc5db2d24bd8abacc937ef7791c6c6101e425b914836de8ec92a16792af9c4f38、効果版SHAは676b75be059e27b8890c596df3365cbafc63499b95609ad0bb236e8bfe6471b4。両側21.9秒、1080×1920、657フレーム／30fps、44.1kHzステレオ、全AVデコード成功。前後フレーム時刻は一致するが音声PCMは完全一致しない。約2.7〜3.8秒で縮小映像の差を確認した。曲名のUI表示は録音同一性やYouTube転用許諾の証拠ではない。

新しいnative-compareは、外部返却MP4の全デコード、最初の音声PCMのSHA／サンプル数と、時刻一致を確認した全フレームの縮小RGB差を保存する。異なる長さ／時刻は黙示整列しない。画像比較はブロック処理し、長尺の全RGBをメモリーへ読み込まない。診断の成功で元動画関係・曲／効果の同一性・人の全編視聴／試聴・権利・API実行・採用を承認しない。音声の一致も配置の承認ではない。取得MP4と生ログ、UI証拠、音付き前後比較をoutput/implementation-maya/tiktok-native-music-20261007/へ保存。READMEと共通編集スキルを更新。

これはStudio UIの実実行であり、Business／Symphony編集APIの実実行ではない。ローカルTikTok APIは引き続き未構成・未接続。YouTube転用許諾未確認のため機能検証用として保持し、既存の絶望ドメイン向け4分類の公開用素材には混ぜない。公開alpha.7を変更しない。

新規4テストと既存返却検査8テストが成功（全12、3.497秒）。実際に符号化した映像で、画面変更＋同一PCM、音声変更＋同一縮小画面、短い尺・異なるPTSの比較拒否、音声なし、MP4を装ったネットワークプレイリスト拒否を確認。共通スキル検査・git diff --check成功。機能検証用の音付き前後MP4はdelivery/tiktok-native-music-effect-before-after.mp4、43.8秒、1314フレーム、全AVデコード成功。比較ラベルを追加し、各音声末尾を21.9秒まで無音補填して連結した。人の全編視聴／試聴承認は未実施。

2026-10-07追加: FCP固定BGMのGUI取り込み成功。測定音量は補間属性でparamを無視する警告を再現し、interpを省略するexporter修正を実装。修正候補の警告なしGUI取り込みとネイティブXML再書き出しで131キーの時刻一致を確認、往復取り込み側の対応を含む関連57テスト成功（12.828秒）。画像・タイトル・複合XML・音声再生一致は別の未受入項目。Business API開発者申請は審査待ちへ進み、アプリ説明を準備したが、アプリ作成と編集APIは未実行。詳細はFCP_ROUNDTRIPとTIKTOK_APIを参照。

2026-10-07画像の切り分け: 元の画像単独XMLの読み込み後にFCP終了を観測。FCPのネイティブ静止画／接続画像XMLを取得し、ゼロ長画像asset・未定義rate format・video接続へ合わせた検証用候補はDTD・警告なしGUI取り込みに成功。黄色画像と50%不透明度を確認した。実exporterと戻し処理への統合、タイトル・複合XML、再生一致は未完了。詳細と元／候補SHAはFCP_ROUNDTRIPとimage-only/native-image-evidence.json。
