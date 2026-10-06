# Final Cut Pro 2026 ハーネス更新候補

調査日: 2026-10-06 / actor: codex / 基準HEAD: `4e229200a64d880414aef2d1596480b68ca07642`

これは調査から導いた実装候補であり、実装済み一覧ではない。関連文書: [制作設定・品質管理](FCP_BEST_PRACTICES_2026.ja.md)、[外部拡張候補](FCP_EXTENSIONS_2026.ja.md)。コード監査の根拠は下表の基準コミット・ファイル・行番号に示す。詳細な作業ログはローカルに保管し、配布しない。

## 1. 現在できることと未保証のこと

| 領域 | 現在の実装根拠（基準HEAD） | 境界 |
|---|---|---|
| 編集計画/レビュー | `session.py:658`以降、`.agents/skills/video-editing/SKILL.md:19` | 6項目・render SHA・聴取/視覚の根拠申告を扱う。申告だけで実際の人間の視聴を証明しない |
| 色 | `color.py:43`、`media.py:63` | 65³ LUT、Apple Log選択時の変換、BT.709出力。グローバルlookと固定領域補正。顔追跡ではない。HLG/Apple Log 2は現行対象外 |
| 音 | `media.py:5`、`editing.py:179` | 測定→2-pass loudnorm、区間fade、結合後のnormalizeと出力測定。FCPXMLは元音声なので仕上げ一致は別問題 |
| FCPXML | `fcp.py:99`、`:122`、`:154`、`:185` | 1.10、単一sourceのflat timeline、分数フレーム、VFR/非ゼロstart制約。色・字幕・マスク・mixの完全再現はしない |
| 納品 | `delivery.py:8`、`session.py:910` | hash付き成果物と手動仕上げ案内。FCPでの再現や配信先の再生をファイルhashから推定しない |
| 出力/検査 | `media.py:29`、`:70`、`editing.py:125` | H.264 yuv420p/AAC、タグ・全decode・尺・音声測定。高ビット深度master/HDRパイプラインとは別 |

上記のファイル名はすべて `video_harness/` 配下。行番号は今後の変更で動くため、基準コミットとともに読む。リリース上の未検証事項は `docs/RELEASE_VALIDATION.md:24` 以降にも記載されている。

## 2. 優先順位

- **P0**: 誤った色/音/タイミング、失われる仕上げ、過大な完成主張を防ぐ。
- **P1**: 高品質master、編集可能性、再現性、素材管理を改善する。
- **P2**: 高度な表現・外部拡張・複数素材workflowを広げる。

「難しそうだから後回し」ではなく、P0を先に満たさないと後の機能追加を正しく評価できない順番である。以下の規模S/M/Lは相対的な見積もりで、日数の約束ではない。

| ID / 優先 / 規模 | 更新候補・仮説 | 主な対象候補 | 受入条件 |
|---|---|---|---|
| H01 / P0 / M | **環境と能力の台帳**。FCP/macOS/FFmpeg版、CPU/GPU、RAM、空き容量、LUT/拡張を記録すれば条件違いを説明できる | `doctor.py`, `runs.py` | Mac以外ではFCP unavailableを正常表現。version不明を成功にしない。秘密情報をログに出さない |
| H02 / P0 / M | **入力メディア契約**。bit depth/pix_fmt、primaries/transfer/matrix/range、fps分数、VFR、start、rotation、SAR、audio chをprobeから保存 | `media.py`, `assessment.py`, `fcp.py` | 不明/矛盾した色情報は要確認。Apple Log/Log 2/HLG/PQ/709 fixtureを誤分類しない。ユーザー上書きには理由とactor |
| H03 / P0 / M | **色変換履歴**。入力→working→outputとLUTの役割を分離し、二重変換を検出 | `color.py`, `profiles.py`, `delivery.py` | LUT SHA、input/output、technical/look区別、baked/nativeを記録。変換済み709にLog conversionを再適用するケースを拒否または明示停止 |
| H04 / P0 / M | **非対応色形式の明示ゲート**。未対応HDR/Log 2に既存Apple Logや709処理を流用しない | `profiles.py`, `color.py`, CLI | 対応/非対応/不明を別状態にする。変換を実装するまではサポート済みを名乗らない。既存sourceを上書きしない |
| H05 / P0 / L | **FCP handoff fidelityモード**。既存の手動仕上げ案内を機能別の機械可読manifestへ拡張する | `fcp.py`, `editing.py`, `delivery.py`, `fcp_check.py` | 保持/焼込み/手動/非対応の機能表とFCP再export比較を追加。現行も差を案内しているが、LUT、字幕、mask、audioの再現状態を機能単位で検証できるようにする |
| H06 / P0 / L | **最終音声の受渡し**。FCPで使えるPCM mixと編集可能な元音声を明確に扱う | `editing.py`, `fcp.py`, `delivery.py` | sample精度の尺/offset、元音声との二重再生防止。FCP再書出しで同期とLUFS/true peakを確認。fadeや接合を試聴 |
| H07 / P0 / M | **FCP roundtrip証跡**。XML import→手動仕上げ→exportでreferenceとの違いを計測 | `fcp_check.py`, `delivery.py`, tests/fixtures | 23.976/29.97等の境界、縦video、音声、色タグ、字幕を実GUIで確認。DTD合格とGUI合格を別記録。再export SHAを保存 |
| H08 / P0 / M | **納品仕様profile**。platform名だけでなくcodec/色/fps/音/字幕の契約を保存 | `profiles.py`, `media.py`, `vertical.py` | preview/master/deliveryの目的が別。SDR/HDRをタグだけで切替できない。基準source URLと確認日、値の上書き理由 |
| H09 / P0 / M | **最終encode後QCの拡張**。既存の最終MP4に対する全decode/色tag/尺/音声coverage/LUFS/true peak検査を維持し、仕様比較を拡充 | `media.py`, `evaluate.py`, `assessment.py` | 新規分はbit depth・frame count・納品派生版ごとの契約照合・文脈付き黒/無音warning。既存検査を未実装として作り直さない。検出による自動削除はしない |
| H10 / P0 / S | **レビュー証拠の構造化**。既存のactor・exact render SHA・6チェック・basis・synthetic区別を維持し、GUI/配信観測を具体化 | `session.py`, `delivery.py`, skills | 新規分は観測者の役割、観測日時、GUI・配信証拠への参照の構造化。declared/observedを区別し、syntheticを実写の品質承認へ昇格させない |
| H11 / P1 / L | **高bit-depth master経路**。H.264配信版と別にProRes等の高品質中間を提供 | `media.py`, `editing.py`, profiles | 入口からfilter途中まで精度維持を検証。最終段で10-bit化しただけを高精度処理と呼ばない。banding/gradient、色tag、full decode、容量を比較 |
| H12 / P1 / M | **FCPXML版とbundle対応**。versionを単に1.14へ書き換えず能力で選ぶ | `fcp.py`, `fcp_import.py`, `fcp_check.py` | 旧版compatibilityを保持。`.fcpxml`と`.fcpxmld/Info.fcpxml`を識別。versionに合うDTD/実GUI試験。未知effectを保持できなければ明示 |
| H13 / P1 / M | **字幕受渡しの契約**。SRT/burn-in/native editableの目的を分ける | `editing.py`, `delivery.py`, `fcp.py` | 日本語、人名、絵文字、CJKフォント、改行、rational fps、句末を確認。native化しても単語時刻を発明しない |
| H14 / P1 / M | **権利・外部依存manifest**。LUT/音楽/font/template/pluginの再現条件を保全 | `delivery.py`, new manifest schema | 出典・版・hash・利用範囲・認証要否・代替策。フォントや音源を再配布許可なしにbundleへ同梱しない |
| H15 / P1 / M | **復元可能な保存**。DB backupとmedia backupを別チェックにする | `delivery.py`, doctor, docs | 原本/ライブラリ/metadata/masterの各所在とhash。別場所でのrelink/import成功を記録。キャッシュ再生成可否も区別 |
| H16 / P1 / M | **用途別settings提案**。軽量編集、色仕上げ、HDR確認、英語取材で異なる設定を提示 | doctor/report/skills | 現状→提案→理由→確認状態のdiff。UIを読めないときはunknown。設定推奨だけで画質向上を主張しない |
| H17 / P1 / M | **比較・測定fixture**。実写とsyntheticを併用し安定比較を作る | tests, scripts, output ledger | 同一source SHA/範囲/audio/条件。白、肌、夜、逆光、動き、長尺音声を含む。主観評価と技術数値を併記 |
| H18 / P2 / L | **マルチソース/ロール/複雑編集**。Bロールや外部音声を扱う編集モデル | `edl.py`, `editorial.py`, `fcp.py` | 時間軸/接続/roleを定義してから実装。既存flat modeを壊さず、多カメラ同期・入れ子・未知effectをfixture化 |
| H19 / P2 / L | **HDR/Apple Log 2正式対応**。根拠ある入力変換と高精度出力経路を追加 | `color.py`, `media.py`, profiles | 公式変換資料/実素材に基づく。HLG/PQを区別。HDR対応displayとSDR downconversionをレビュー。H02–04/H08/H11が前提 |
| H20 / P2 / L | **動的mask/追跡/縦reframe**。固定領域からの機能拡張は独立評価 | `regions.py`, `vertical.py`, inspection | 遮蔽、画面外、速い動き、cutごとのresetを検証。追跡信頼度低下で人のreviewへ。黙って中央cropへ切替えない |
| H21 / P2 / M | **拡張adapters**。OTIOや外部audio等を限定用途で接続 | optional dependencies/adapters | plugin/adapterごとの対応表。FCP7 XMLとFCPXMLを混同しない。非対応transition/effect/retimeの脱落をテスト |

## 3. 推奨する着手順

### 第1段階: 仕様・検査・正直な受渡し

H01–H04、H05の差分manifest、H08–H10を最初の実装単位とする。目的は「何を読み、何を変換し、何を渡したか」が機械的に追える状態を作ること。変更前の既存fixture結果をbaselineとして保存し、既存SDR処理の挙動を回帰検証する。

### 第2段階: 一つの実素材でFCPまで閉じる

H06–H07、H17を実施。権利・プライバシー上使用可能な代表素材を選び、短い映像をハーネス→FCP→最終exportまで通す。referenceと一致しない箇所は「FCP未対応」または明示した仕上げ作業として残す。成功条件はXMLの生成だけではない。

### 第3段階: masterと編集可能性

H11–H16。ProRes等の高品質master、字幕・依存素材・バックアップを整備。FCPXMLの新版対応は実際に必要な機能から追加し、互換版を残す。

### 第4段階: 高度な表現

H18–H21。複数素材、HDR/Log 2、追跡、外部アダプタをそれぞれ独立fixtureで実装する。全領域を同時に変えると色・音・タイミングの差の原因が追えなくなるため、受入条件単位でまとめる。

## 4. 提案するセッション情報（概念設計）

既存JSONへの追加を今ここで実装するものではない。実装時はschema version/migrationを設け、旧セッションの再開を検証する。

```json
{
  "environment": {"fcp_version": null, "macos_version": null, "ffmpeg_version": null},
  "media_contract": {"source_sha256": null, "input_color": "unknown", "fps_rational": null},
  "color_pipeline": {"input_transform": null, "look": null, "output_space": "bt709", "baked": false},
  "delivery_profile": {"purpose": "sdr_web", "master_codec": null, "audio_target_basis": "project_choice"},
  "handoff": {"mode": "editable_with_reference", "manual_steps": [], "unsupported_features": []},
  "dependencies": [],
  "evidence": {"technical": null, "human_review": null, "fcp_roundtrip": null, "distribution": null}
}
```

`null`は未検証を表す。値の入力・存在だけで検証済みにしない。`baked=false`は例示であり、実素材に自動適用してはいけない。

## 5. 検証計画

| 試験 | 素材/条件 | 何を証明するか | 証明しないこと |
|---|---|---|---|
| 単体/機能 | deterministicな小fixture、同一seed | schema、rational time、tag、エラー処理 | 実写の美しさ、GUI動作 |
| 映像/音声全decode | 最終納品file | デコード可能性、技術的整合 | 自然な編集・良い色・良い音 |
| 色経路試験 | gradient/chart、既知709/Log、明暗/肌 | 変換順・bit-depth劣化・二重変換 | 芸術的なlookの良さ |
| 音声試験 | speech、breath、silence、music、長尺 | 接合・同期・loudness・true peak | 人の聞きやすさの最終判断 |
| FCP実GUI | 対象FCP/macOS、複製library | import、依存解決、再exportの整合 | 他バージョンや全plugin互換 |
| 人のreview | 同一区間/同音量、最終SHA | その版の意味・色・音・字幕の承認 | 他のrenderや改訂版の承認 |
| 配信後検証 | 認可されたupload、複数端末 | transcode後の現実の視聴 | ローカルmasterだけでは代替不可 |

実装開始時のコマンドはリポジトリ指示に従い `uv sync --locked`、`uv run video-harness doctor`、該当CLIの`--help`を実行し、変更に関連するテストを実施する。今回は調査のみのため依存追加やテスト実行で未変更のコードを再検証する作業は行っていない。

## 6. 採用を急がない項目

- 最新FCPXML番号への置換だけで新機能対応を名乗ること。
- 全素材のHDR化、全出力の4444 XQ化、8-bit処理後の10-bit化による品質主張。
- 無音・暗い領域・低SSIMの自動削除や自動不合格。
- proxy作成を全クリップで強制すること、M3という機種名だけで処理時間を予測すること。
- プラグインを大量導入し、依存ライセンスや別Mac移管を後回しにすること。
- native `.fcpbundle` 内の非公開データベースを直接書き換える連携。
- 映像の単語alignmentを例示IDから生成すること、クラウドへのsource別許可を省略すること。
