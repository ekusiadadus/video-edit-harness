# Final Cut Pro 2026 制作設定・品質管理 調査

調査日: 2026-10-06 / 作成者: codex / 状態: 調査・更新提案（未実装）

対象リポジトリ: `video-edit-harness`、調査基準コミット `4e229200a64d880414aef2d1596480b68ca07642`。
対象は Mac 版 Final Cut Pro。Apple の公式ガイド・リリースノート、配信先の公式仕様、規格発行元を優先した。外部製品の能力はメーカーの説明であり、この環境での動作・品質試験とは区別する。

## 1. 結論と前回の訂正

「最高の動画」に万能な設定セットはない。目的、素材、納品先、表示環境を決め、編集判断・色・音・字幕・書き出しを一貫して検証することが重要である。高ビットレート、HDR、RAW、強いノイズ除去、大量のプラグインは、それ自体では作品品質を保証しない。

前回の調整は主として読み込み処理の軽量化であり、作品品質全体を最適化したとは言えない。次の表は前回のローカル実操作記録を再評価したもの。調査時点では追加のアプリ設定変更は行っていない。後続の適用結果は[設定適用記録](FCP_SETTINGS_APPLIED_2026.ja.md)を参照。

| 項目 | 前回の状態 | 再評価・今回の推奨 | 根拠 |
|---|---|---|---|
| バックグラウンドレンダリング | 既にオフ、維持 | 妥当な開始点。重いエフェクトや上映確認では選択範囲をレンダリングする。常時オフが全案件で最速とは未測定 | [S01][S02] |
| ビジュアル検索 | オン→オフ、保存確認済み | **条件付き**。大量のBロールやアーカイブでは検索の便益がある。短い既知素材では必要時解析を提案。画質改善策ではない | [S03][S04] |
| 英語文字起こし | オン→オフ、保存確認済み | 日本語中心なら妥当な候補。英語取材では検索性を失う。検索用解析と字幕生成、ハーネスの単語時刻付き文字起こしは別機能 | [S04][S05] |
| 参照波形 | オフ→オン、保存確認済み | 低音量部分の形状を見やすくする補助。音を改善したり、実音量を示したりする設定ではない | [S06] |
| 自動最適化・プロキシ生成 | 既にオフ、維持 | 読み込み時の一括生成を避ける開始点。再生が重い素材、長編、マルチカムには必要分を生成する | [S07] |
| パフォーマンス優先 | 選択操作のみ、保存未確認 | オフライン編集向け。色・フォーカス・細部の最終判定では品質優先へ切り替える | [S08] |
| 最適化/オリジナル | 選択操作のみ、保存未確認 | 最終書き出し前に必ず再確認するチェック項目 | [S09] |
| ライブラリにコピー | オンを維持 | 素材管理を簡単にする選択。整理済みの外部メディア運用ならリンク方式も正当。どちらも媒体の独立バックアップが必要 | [S03][S10] |
| Final Cut Backups | 両ライブラリに保存先表示 | **バックアップ完了の証拠ではない**。設定のみ確認済み。実ファイル・復元試験・素材のバックアップは未確認 | [S10][S11] |

Apple の米国版リリースノートは調査時点で **12.4（2026-09-29）**。12.3にはバックグラウンドレンダリングの既定値オフ、HEVCプロキシ、Auto Mask、改良されたMatch Color、字幕生成等が記載される。12.0ではFCPXML 1.14を導入。地域別ページや検索キャッシュには旧情報が残るため、ページの更新日と対象バージョンを照合する。[S01]

このMacのインストール済みFCPバージョンは今回確認できていない。前回UIではApple M3を確認済み。今回、一般的な `/Applications/Final Cut Pro.app` のInfo.plistが見つからず、シェル起動も断続的なFD上限エラーになった。アプリ未インストールとは判断しない。最新版の機能をこの環境で使用可能と断定しない。

## 2. 設定を決める前の制作仕様

以下は本調査の運用提案。Appleの固定値推奨を意味しない。

| ID | 決める項目 | 記録する内容 | 完了条件 |
|---|---|---|---|
| Q01 | 視聴者と目的 | 誰が何を理解・感じ・実行する動画か | 一文の目的、残す情報、避ける表現が明確 |
| Q02 | 納品先 | YouTube、縦SNS、Web、クライアント、放送等 | 解像度、縦横比、fps、色空間、音声、字幕の仕様 |
| Q03 | 原素材 | カメラ、コーデック、ビット深度、色メタデータ、音声ch、VFR有無 | `ffprobe`等による実測、未知値を推測で埋めない |
| Q04 | 画の基準 | 承認済みの参考フレーム、肌、白、黒、シーンの雰囲気 | 同じ区間・同じ表示条件で候補を比較 |
| Q05 | 音の基準 | 会話・音楽・環境音の役割、音量差、納品ラウドネス | 同音量比較と実視聴、測定値を併記 |
| Q06 | 編集構成 | 導入、展開、結論、Bロール、必要な間 | 時短量だけでなく意味・感情の連続性を確認 |
| Q07 | 権利と素材管理 | 楽曲、フォント、テンプレート、LUT、人物許諾 | 出典、利用条件、取得日、対象案件を記録 |
| Q08 | レビュー | レビュー担当、対象版、修正履歴 | 書き出しSHA-256とレビューを結び付ける |

## 3. 基本設定：素材管理・編集・再生

各行の「提案」はこの環境への推奨開始点であり、測定済み最適値ではない。

| ID | 場所/対象 | 推奨開始点と切替条件 | 確認方法・理由 |
|---|---|---|---|
| B01 | FCP/macOS/拡張の版 | 制作中に無条件で更新しない。複製ライブラリと代表素材で互換性確認後に更新 | FCP本体・ライブラリを事前保存。[S01][S12] |
| B02 | 外部編集ストレージ | Mac専用の編集ボリュームはAPFS。既存ディスクの再フォーマットは調査段階で実行しない | AppleはExFAT/FAT32で期待通り動作しない場合を説明。Time Machine用デバイスに作業ライブラリを置かない。[S13] |
| B03 | 保存場所 | originals / projects / cache / exports / backups を役割で管理する。高速SSDに作業データ、独立した保存先にバックアップを提案 | フォルダ名だけでなく、実参照先と復元可能性を確認。コピーとリンクの違いを理解。[S03][S10] |
| B04 | ライブラリ単位 | 案件・納品色管理の境界を明確にする。大量案件を一つに無制限集約しない | 色処理設定の影響範囲を限定。[S14] |
| B05 | 読み込み | カード構造と原本を保全。コピー/リンクを案件ごとに選ぶ | カードを抜いた後も再生できるか、欠落リンクがないか。統合はバックアップの代替ではない。[S03][S10] |
| B06 | キーワード/ロール | カメラ、シーン、テイク、人物、音声役割で検索可能にする | Dialogue/Music/Effectsと必要なサブロールを早期に整理。[S15] |
| B07 | 自動解析 | Visual Searchは素材探索の便益で決める。英語解析は対応言語と素材に合わせる | 解析時間と後の検索時間を別々に記録。[S04][S05] |
| B08 | 自動色・音補正 | 一括適用を作品の完成扱いにしない。問題箇所に適用し前後を確認 | ノイズ除去で声の質感、バランスカラーで照明意図を損なわないか。[S16] |
| B09 | 最適化メディア | オリジナルが快適なら必須ではない。デコード負荷や複雑な編集で必要分のみ作成 | ProResへの変換は圧縮原本の失われた情報を復元しない。[S07] |
| B10 | プロキシ | M3で重い4K/多カメラはProRes Proxy 50%を試行候補。容量優先なら対応版のHEVCと比較 | 代表30～60秒の同一区間でコマ落ち、準備時間、容量を比較。25%等は必要時。数値は運用提案。[S01][S07] |
| B11 | ビューア品質 | 編集時はパフォーマンス優先を選択肢にし、精細確認時は品質優先 | 表示解像度と納品解像度を混同しない。[S08] |
| B12 | メディア再生 | 編集はプロキシ優先も可。オンライン確認と書き出し前に最適化/オリジナルへ | プロキシしかない状態で完成マスターを作らない。[S09] |
| B13 | レンダリング | 通常は既定のオフから開始。再生できない箇所を明示レンダリング | バックグラウンドON/OFFを画質ランキングにしない。[S01][S02] |
| B14 | コマ落ち警告 | 編集では停止しない運用、技術試写では検出を優先する運用を提案 | 再生負荷によるコマ落ちと書き出しファイルの破損を区別。[S02] |
| B15 | 波形・メーター | 参照波形を表示し、音量判断はメーターと聴感で行う | 波形の大きさから無音削除・ラウドネス合格を判断しない。[S06] |
| B16 | フェード/トランジション | 0.5秒等の既定値を全カットに強制しない | 発話末尾、息、環境音、音楽フレーズを聞いて調整。本調査の編集提案 |
| B17 | タイムライン仕様 | 主な素材と納品先を基準にfps/解像度を編集前に確定 | 23.976/24、29.97/30を区別。fps変更は編集点に影響する。[S17] |
| B18 | 改訂保存 | 主要レビュー点でSnapshot Projectを作る | compound/multicamの親クリップ変更が旧版に波及することを防ぐ。[S18] |

## 4. 色管理・応用設定

### 4.1 三つの制作経路

| 経路 | ライブラリ/プロジェクトの提案 | 入力処理 | 納品 |
|---|---|---|---|
| 通常SDR | SDR素材だけならStandardも可。プロジェクトはRec.709 | 正しい素材メタデータを確認 | Rec.709を正しくタグ付けしたSDR |
| Log/RAWからSDR | 広い階調を保って調整するならWide Gamut HDRライブラリ＋Rec.709プロジェクトを候補にする | カメラ形式に一致する変換を一度だけ適用 | SDRスコープとSDR表示で最終確認 |
| HDR納品 | Wide Gamut HDRライブラリ＋納品仕様のRec.2020 HLG/PQ | 入力のLog/HLG/PQを区別し変換経路を記録 | 対応表示、10-bit以上、HDRメタデータ、SDR派生も確認 |

Wide Gamut HDRライブラリはHDR納品の指定そのものではない。カメラLUTによるLog処理とプロジェクト色空間への適合は別段階である。[S19][S20]

### 4.2 実施項目

| ID | 項目 | 推奨と検証 |
|---|---|---|
| C01 | 入力判定 | Apple LogとApple Log 2、HLG、PQ、Rec.709を別形式として扱う。撮影機種名だけで判定しない。メタデータ不明なら手動確認を必須にする。[S01][S19] |
| C02 | 変換の所有者 | FCP Camera LUT、Custom LUT、ハーネスの焼き込み済み変換のどれが何を行ったかを台帳化。二重Log→709変換を防ぐ。[S20] |
| C03 | Camera LUTの影響 | メディアレベルの変更は同一ライブラリ内の使用箇所へ影響する。作品別の見た目を無計画にCamera LUTへ置かない。[S20] |
| C04 | Color Conform | 通常はAutoを開始点にする。変換済み素材や管理済みチェーンではManual/Noneを明示。HDR ToolsとColor Conformの重複変換を避ける。[S21] |
| C05 | 色メタデータ | 誤ったタグの修正と実画素の色変換を別操作として扱う。タグだけ書き換えてHDR化しない。[S14][S27] |
| C06 | 表示環境 | 対応ディスプレイでは納品に合うreference mode。安定した周囲光で判定。色判定中のTrue Tone/Night Shift等の自動的見え方変更を避ける運用を提案。[S22] |
| C07 | スコープ | Waveformで輝度、RGB Paradeでチャンネル差を確認。選択した素材/プロジェクトの色空間で表示尺度が変わることに注意。[S23] |
| C08 | ベース補正 | 露出・白バランス・黒・ハイライトを整え、ショットを合わせてからlookを作る。どの肌も同じIREや色相に押し込まない。本調査の品質提案 |
| C09 | 比較条件 | 同一区間、同一音声、同一ビューア設定で自然/暖色/映画調などを比較。代表フレームだけでなく動き・照明変化も見る。本プロジェクト規則 |
| C10 | Match Color | 照明やカメラ差を合わせる出発点として評価。自動結果を承認扱いにしない。[S01] |
| C11 | マスク | Magnetic/Auto Maskやtrackerは動き・遮蔽・カット際を全区間確認。固定領域マスクを顔追跡と呼ばない。[S28] |
| C12 | ノイズ/シャープネス | ノイズ除去は必要なショットで試し、肌・髪・細線・動体の残像を100%表示で確認。シャープネスを最後に控えめに比較。本調査の品質提案 |
| C13 | SDRレベル | Rec.709の黒・白・彩度をスコープで管理。機械的なclipでハイライトを切り捨てず、納品範囲へ意図的に収める。特定の肌IREを必須化しない |
| C14 | HDR試写 | SDR画面のトーンマップ表示だけでHDRマスターを承認しない。HDR表示とSDR変換の両方をレビュー。[S14][S27] |

### 4.3 編集・モーション・音声・字幕

| ID | 領域 | 実施内容/受入条件 |
|---|---|---|
| A01 | 構成 | 冒頭で視聴目的を伝え、必要な前提・因果関係を保つ。短さだけを最適化しない。レビューで意味の欠落を確認 |
| A02 | 会話編集 | J/Lカット、Bロール、room toneは文意と聞きやすさのために使う。語尾、呼吸、話者交代を全接合点で聴く |
| A03 | 音声整理 | マイク別・話者別のサブロールとDialogue/Music/Effectsを整え、必要ならstemを書き出す。[S15] |
| A04 | ノイズ/Voice Isolation | 必要最小限を同音量A/Bで判断。複数コンポーネントへの同時適用による不自然な音も確認。[S16] |
| A05 | ミックス | 会話の明瞭度を優先し、音楽はキーフレーム等で調整。EQ、コンプレッサー、de-esser、limiterは問題に対応して使う |
| A06 | 測定 | Integrated/Short-term loudness、LRA、true peakを最終エンコード後に確認。BS.1770は測定方法であり、全配信先共通の目標LUFSではない。[S24] |
| A07 | 音量目標 | ハーネスの-16 LUFS/-1.5 dBTPは開始値。YouTube公式の必須値とは表現しない。放送案件は仕様書優先（EBU R128の番組基準は-23 LUFS）。[S25] |
| A08 | 聴取 | ヘッドホン、スピーカー、モノラル、小型端末で会話・ノイズ・位相・低音の過不足を確認。測定合格と聴感承認は別 |
| A09 | 同期 | 長尺で冒頭/中盤/末尾の口形と音を確認。VFR、外部録音クロック、速度変更をリスク要因として記録 |
| A10 | スロー | 高fps実撮影のAutomatic Speedを優先候補にし、不足フレームの補間は別扱い。Optical Flow/MLは手指・交差・文字・遮蔽の破綻を検査。[S29] |
| A11 | 手ぶれ補正 | crop量と輪郭の変形、パンの意図を比較。すべてのショットで最大強度にしない |
| A12 | 縦版 | 横版から単純中央cropで完成扱いにしない。話者、実演対象、文字、UI被りを各ショットで調整。Smart Conformも再確認。[S18] |
| A13 | 字幕の意味 | 人名・数字・専門用語・句読点・話者・タイミングを原音で校正。自動字幕とソース時刻の正確性を分けて評価 |
| A14 | 字幕の可読性 | 画面サイズごとに改行、表示時間、コントラスト、背景、フォント欠けを実機確認。固定の文字数だけで合格にしない |
| A15 | 字幕の形式 | 焼き込み、切替字幕、編集可能なFCPタイトルを納品要件で区別。英語対応機能を日本語対応と推測しない。[S01][S05] |
| A16 | タイトル/動き | 少数の一貫したタイポグラフィ、色、余白、動きにまとめる。テンプレート数を品質の代理指標にしない |

## 5. 書き出し・配信・保存

### 5.1 用途別の出力候補

以下のMaster設定は本調査の制作提案。納品者の仕様があればそちらを優先する。

| 用途 | 候補 | 注意/検証 |
|---|---|---|
| SDR編集マスター | 元の納品fps/解像度、Rec.709、ProRes 422または422 HQ、PCM 48kHz | 容量と後工程で選択。8-bit原本をHQへ変換しても失われた情報は戻らない。[S26] |
| alpha合成素材 | 対応するProRes 4444等 | alphaの必要性、premultiply、合成先での縁を確認。全動画を4444 XQにする必要はない。[S26] |
| YouTube SDR 1080p | MP4/H.264、48kHz、BT.709 | 公式参考値は24/25/30fpsで8Mbps、48/50/60fpsで12Mbps。[S30] |
| YouTube SDR 4K | MP4/H.264、48kHz、BT.709 | 公式参考値は24/25/30fpsで35–45Mbps、48/50/60fpsで53–68Mbps。上限や画質保証ではない。[S30] |
| YouTube HDR | 10/12-bit、Rec.2020、PQ/HLG、対応コーデック | HEVC等を候補に、メタデータと実配信のHDR表示・SDR変換を確認。[S27] |
| 縦SNS | 9:16版を独立レビュー。1080×1920等は候補 | TikTok/Reels等はアカウント・投稿経路の最新仕様を実装時に再確認。今回は固定fps/bitrateを公式必須値として採用しない |
| 他社ポスト工程 | master＋音声stem＋字幕＋FCPXML＋依存素材台帳 | XMLに含まれないプラグインや効果を確認し、必要箇所を中間素材として渡す。[S09][S10][S31] |

### 5.2 納品ゲート

- [ ] D01: 最適化/オリジナル再生、元素材のオンライン状態、書き出し範囲を確認。[S09]
- [ ] D02: codec/profile/pix_fmt、fpsの分数、解像度/SAR、色primaries/transfer/matrix/rangeを実ファイルで確認。
- [ ] D03: 音声sample rate/channels、最終LUFS/true peak、字幕の有無・文字化けを確認。
- [ ] D04: 全フレーム・全音声をデコード。冒頭/末尾、黒フレーム、欠落、同期を確認。
- [ ] D05: 意図したノイズ・暗転・静止画まで自動検出エラー扱いしない。検出結果に文脈を付ける。
- [ ] D06: 色、フォーカス、マスク、リタイム、字幕、音を人が視聴して承認。承認者とSHA-256を記録。
- [ ] D07: 投稿が認可された場合だけ配信先へアップロード。処理完了後に画質・HDR/SDR・字幕・音声を実端末で確認。
- [ ] D08: 原素材・FCPライブラリ・XML・master・配信版・LUT・フォント/楽曲等の権利情報・版を保存。
- [ ] D09: 別場所で復元試験。FCP自動バックアップはライブラリDBのみで原素材を含まない。[S11]

## 6. 外部ライブラリ・拡張の採用方針

「ライブラリ」はFCPの `.fcpbundle`、Motionテンプレート、LUT/フォント/楽曲素材、FxPlug/Audio Units、ハーネスのソフトウェア依存関係を区別する。用途別候補とメーカー一次資料は別紙 [外部拡張候補](FCP_EXTENSIONS_2026.ja.md) にまとめる。

導入順の提案は、標準機能の不足確認 → 小さな代表素材でtrial → 互換性/ライセンス/移管検証 → 採用。標準の色補正・マスク・音声補正で足りる案件に同機能の製品を一括追加しない。

外部拡張台帳には `product / vendor / version / macOS / FCP / architecture / install_path / license_scope / asset_hash / project_usage / fallback / tested_at` を持たせる。未知値はunknownのまま保持し、ネット上の「Apple Silicon対応」をFCP 12.4＋実機での合格に置き換えない。価格は購入時の地域・税・サブスクリプション条件を再確認する。

## 7. ハーネス更新への接続

詳細なコード監査と更新候補は別紙 [ハーネス更新候補](FCP_HARNESS_BACKLOG_2026.ja.md)。最優先は効果の種類を増やすことより、入力色形式・変換経路・出力仕様の整合を検証し、FCPでの見た目/音とハーネスの結果の差を明示すること。

採用前の実験は、同じソースSHA、同じ区間、同じ音声、同じ機器条件で行う。技術合格、AIによる候補選択、人の視聴承認、FCP実インポート、配信先再生を別の証拠として保存する。画像統計・SSIM等は創作的なgradingの良さを自動判定する指標にはしない。

## 8. 未確認事項・実装前の確認

1. 実機のFCP版、macOS、RAM、ディスプレイとreference mode、SSD空き容量・実効速度。
2. 前回のビューア品質/メディア再生設定の保存状態。
3. 使用中2ライブラリの実バックアップ、独立原素材コピー、復元成功。
4. Apple Log/Log 2/HLG/PQ、長尺VFR、各カメラの実ソースに対する色・同期試験。
5. 外部プラグインの購入済みライセンス、インストール版、FCP 12.4での動作。
6. 主な納品先と、字幕・HDR・master・音声stemの要求。

今回の成果は調査文書。アプリの追加変更、プラグイン導入、コード実装、動画のアップロード、画質向上の実測は含まない。

## 9. 一次資料一覧

各資料の確認日: 2026-10-06。旧版を指す例示と現行仕様を区別した。URLに地域/版が含まれる場合、そのページの対象に注意。公式記載は能力と制約の根拠であり、本文の運用提案すべてをメーカーが推奨しているという意味ではない。

- [S01] [Apple: Final Cut Pro release notes](https://support.apple.com/en-us/102825) — 12.4/12.3/12.0と変更点。米国版を基準。
- [S02] [Apple: Playback settings](https://support.apple.com/guide/final-cut-pro/playback-settings-verb8e60ab7/12.4/mac/26.6) — 背景render・警告。
- [S03] [Apple: Import settings](https://support.apple.com/nl-nl/guide/final-cut-pro/verb8e6085b/12.3/mac/15.6) — コピー/リンク、解析。proxy codecの記載は[S01]の新版変更を優先。
- [S04] [Apple: Find clips and projects](https://support.apple.com/en-bh/guide/final-cut-pro/ver65764b45/mac) — Visual/Transcript Search。
- [S05] [Apple: Audio analysis options](https://support.apple.com/guide/final-cut-pro/audio-analysis-options-verb6acaf60/12.4/mac/26.6) — 英語解析と音声自動処理。
- [S06] [Apple: Editing settings](https://support.apple.com/guide/final-cut-pro/editing-settings-verb8e60d02/mac) — 参照波形、既定duration。
- [S07] [Apple: Create optimized and proxy files](https://support.apple.com/en-om/guide/final-cut-pro/verb8e5f6fd/mac) — メディア生成。H.264記載は旧情報、現行HEVC変更は[S01]。
- [S08] [Apple: Control playback quality](https://support.apple.com/en-za/guide/final-cut-pro/ver2fd7a8b94/mac) — 表示品質と再生メディア。
- [S09] [Apple: Export final mastering files](https://support.apple.com/en-sg/guide/final-cut-pro/ver0192a47b8/mac) — 書き出し前のoriginal切替、範囲と出力。
- [S10] [Apple: Copy a project to another Mac](https://support.apple.com/guide/final-cut-pro/copy-a-project-to-another-mac-ver2ccd060e8/12.4/mac/26.6) — メディア/依存素材の移管。
- [S11] [Apple: Restore a library](https://support.apple.com/en-ie/guide/final-cut-pro/ver85d95b8a9/mac) — DBバックアップの範囲。
- [S12] [Apple: Back up Final Cut Pro](https://support.apple.com/en-gb/119609) — アプリとライブラリの保全。
- [S13] [Apple: Format storage devices](https://support.apple.com/en-us/102116) — APFS。
- [S14] [Apple: Wide-gamut HDR tips](https://support.apple.com/guide/final-cut-pro/wide-gamut-hdr-tips-verad6f7dbbd/mac) — 表示/ライブラリ/メタデータ。
- [S15] [Apple: Intro to roles](https://support.apple.com/en-ie/guide/final-cut-pro/verb71cbcbe/mac) — ロール、subrole、stem。
- [S16] [Apple: Enhance audio](https://support.apple.com/en-eg/guide/final-cut-pro/verc1fab873/mac) — 音声補正の機能と制約。
- [S17] [Apple: Conform frame sizes and rates](https://support.apple.com/en-ae/guide/final-cut-pro/ver3363b44e/12.4/mac/26.6) — fps/サイズの整合。
- [S18] [Apple: Duplicate projects and clips](https://support.apple.com/guide/final-cut-pro/duplicate-projects-and-clips-verfd45ffa45/12.4/mac/26.6) — Snapshot、縦横派生。
- [S19] [Apple: Intro to wide color gamut and HDR](https://support.apple.com/en-au/guide/final-cut-pro/ver09be4f91f/mac) — 処理色域。
- [S20] [Apple: Apply LUTs](https://support.apple.com/en-gu/guide/final-cut-pro/ver24f966423/mac) — Camera/Custom LUTと処理順。
- [S21] [Apple: Automatic color management and Color Conform](https://support.apple.com/en-asia/guide/final-cut-pro/ver808063493/mac) — 色変換重複の注意。
- [S22] [Apple: Reference modes](https://support.apple.com/en-gb/108321) — 表示モードの用途。
- [S23] [Apple: Waveform monitor display options](https://support.apple.com/en-ie/guide/final-cut-pro/ver761c9d9d/mac) — 輝度とRGB表示。
- [S24] [ITU-R BS.1770](https://www.itu.int/rec/R-REC-BS.1770/en) — loudness/true peak測定規格。
- [S25] [EBU R128](https://tech.ebu.ch/publications/r128) — 放送向けラウドネス基準。
- [S26] [Apple: About Apple ProRes](https://support.apple.com/en-om/102207) — codecの用途。
- [S27] [YouTube: Upload HDR videos](https://support.google.com/youtube/answer/7126552?hl=en-GB) — HDR納品条件。
- [S28] [Apple: Creator Studio June 2026 update](https://www.apple.com/newsroom/2026/06/apple-creator-studio-gets-smarter-faster-and-more-connected/) — Auto Mask等の能力。宣伝上の品質表現を検証済みと扱わない。
- [S29] [Apple: Change clip speed](https://support.apple.com/en-qa/guide/final-cut-pro/ver40b00150/mac) — Automatic Speed/補間。
- [S30] [YouTube: Recommended upload encoding settings](https://support.google.com/youtube/answer/1722171?hl=en) — SDR upload参考値。
- [S31] [Apple Developer: FCPXML Reference](https://developer.apple.com/documentation/professional-video-applications/fcpxml-reference) — 交換形式の範囲。
- [S32] [Apple Developer: FCPXML Bundle Reference](https://developer.apple.com/documentation/professional-video-applications/fcpxml-bundle-reference?changes=_3) — `.fcpxmld`構造。
- [S33] [Apple Developer: Importing FCPXML Data](https://developer.apple.com/documentation/professional-video-applications/importing-fcpxml-data) — bundle/document両対応。本文のCurrent=1.10は旧例示であり最新版判定に使わない。
