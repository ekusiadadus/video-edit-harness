# Final Cut Pro 外部拡張・周辺ソフト調査（2026-10-06）

調査のみ。基準コミット `4e229200a64d880414aef2d1596480b68ca07642` を確認。購入、インストール、素材アップロード、FCP GUI 検証は行っていない。以下の互換性は公式公開仕様の読取りであり、この Mac／FCP 12.4 での動作実測ではない。価格は地域・プラン・時点で変わるため採用根拠にしない。

## 採用順の目安

|優先度|候補と用途|公式資料で確認できた範囲|導入前に確認する点|
|---|---|---|---|
|高・必要時|[Apple Motion](https://support.apple.com/en-gb/guide/motion/motn141bc4d2/mac)：独自タイトル、トランジション、エフェクト、ジェネレータを作り、FCP Inspector に調整項目を公開|Apple のテンプレート工程。既存テンプレートも変更可能。|FCPとのバージョン整合、実際のフォント／素材ライセンス。強い演出が必要な場合だけ。|
|高・納品形式次第|[Apple Compressor](https://support.apple.com/en-asia/guide/compressor/cpsr1e359452/mac)：FCP/Motionから送って追加形式にトランスコード|同じMacに配置し互換版を使う。Apple Creator Studio版と買切版の混在に制約あり。|納品形式、色・音・字幕メタデータ、実ファイル再生を検査。通常形式ならFCP書出し／既存FFmpegで十分な可能性。|
|中・問題素材のみ|[Neat Video v6](https://www.neatvideo.com/features/compatibility/nv6fc)：ノイズ低減|FCP 10.5.2以降／11／12、Apple Silicon、macOS 11以降を明記。4Kでは統合メモリ16GB最低、32GB推奨。|強度、ディテール損失、レンダリング時間を同一区間で比較。良好な素材には不要。|
|中・複数カメラLog/RAW時|[CineMatch](https://www.filmconvert.com/plugin/cinematch)：カメラ間色合わせ、色空間変換|[製品仕様](https://www.filmconvert.com/purchase?product=cinematch)はmacOS 15以降、FCP 10.8以降。[対応カメラ](https://www.filmconvert.com/supported-cameras?Product=cinematch)はLog/RAWプロファイルのみ。|個別カメラ/プロファイル対応、FCP 12.4対応、Camera LUTと変換の二重適用、自然な白と肌。|
|中・ルック探索時|[FilmConvert Nitrate](https://www.filmconvert.com/purchase)：フィルム調色・粒子|FCP版はmacOS 11.5.1以降、FCP 10.8以降、Apple Silicon対応を記載。|FCP 12.4での実証、素材別プロファイル、粒子/ハレーションのライセンス範囲。既存の自然なグレードと同一区間比較。|
|中・高度なグレーディング時|[Color Finale 2](https://colorfinale.com/color-finale-2)：FCP内のカラーツール|公開FAQはFxPlug4、Intel/Apple Silicon、macOS 13–15、FCP 10.7以降／11。オンライン認証を要求。|公開表はFCP 12・macOS 26を明示せず。ベンダー確認と体験版で実機検証が必要。|
|中・特定演出時|[MotionVFX mTracker 3D](https://www.motionvfx.com/store%2Cmtracker-3d%2Cp4822.html)：カメラ動作推定と3D要素合成|製品ページはApple Silicon、macOS 13.6.9以降、FCP 10.6.5以降。一般[互換性記事](https://support.motionvfx.com/en/articles/5496234-are-your-plugins-compatible-with-apple-silicon-m1-m2-m3-m4-m5-computers)は現行ストア品のApple Silicon対応を説明。|製品単位でFCP 12.4を確認。トラッキング精度、画面デザイン、追加パック依存。|
|中・個別問題時|[CoreMelt](https://coremelt.com/pages/system-requirements)：安定化、マスク、追跡、修復|現行製品の一部はApple Siliconネイティブ。[Native Plugin Bundle](https://coremelt.com/products/native-plugin-bundle-paintx-modelx-stylex-lock-load)はPaintX/ModelX/StyleX/Lock & Load/SliceX/TrackXをネイティブと明記。一方、システム要件ページではSliceX/TrackX等をRosetta必要と記載し、ページ間に齟齬。|必ず製品・版を指定して最新対応をベンダーに確認。FCP 12.4は未確認。|
|低・プラグイン探索|[FxFactory](https://fxfactory.com/help/finalcutpro/)：多数のタイトル・エフェクト・音声プラグインの管理|[ダウンロード要件](https://fxfactory.com/download/)はFCP 10.6以降を表示。Appleの[互換性案内](https://support.apple.com/ja-jp/101831)はApple Silicon向けFxPlug4更新を促す。|FxFactory本体の対応≠各収録プラグインの対応。個々のFCP 12.4、macOS、Apple Silicon、ライセンスを確認。|
|高・音声に欠陥がある時|FCPの[Audio Units](https://support.apple.com/en-qa/guide/final-cut-pro/verb71ca88f/mac)／[iZotope RX](https://support.izotope.com/hc/en-us/articles/6658045386769-How-to-use-RX-as-an-audio-editor-with-Final-Cut-Pro-X)：ノイズ・クリック等の修復|Appleは64-bit AU効果をFCPで使用可能と説明。Apple Silicon上でも[多くのAUv2/v3に対応](https://support.apple.com/en-gb/102082)。RX Audio Editorで動画由来音声を扱う場合、編集音声を書き出しFCPへ再取込み。|個別AU版・FCP 12.4対応と同期確認。先にラウドネス／真のピークを測り、過処理や欠落を聴取。|

## 素材の権利と harness 連携

- 音楽・SFX・テンプレートは制作物ごとに権利を確認。[Artlistの公式ライセンス](https://artlist.io/help-center/privacy-terms/artlist-license/)は有効な有料契約中に新規プロジェクトへ組込み・公開する条件を示す。公開済み作品の継続利用と新規制作は別。顧客案件・媒体・広告・放送・クレジット/clearlist条件を契約プランで確認する。素材ファイルの再配布不可。
- フォントは[Adobe Fonts FAQ](https://helpx.adobe.com/fonts/web/font-licensing/font-licensing.html)が映像・商用/放送利用を許容。ただしサービス経由のフォントとローカルに別途インストールしたフォントは契約が別で、フォントファイルの受渡しは許可されない。FCP/Motionの表示・日本語字形は実機で確認。
- [Apple FCPXML仕様](https://developer.apple.com/documentation/professional-video-applications/fcpxml-reference)は素材、編集判断、メタデータの交換用で、ネイティブライブラリ全内容の代替ではない。DTDに合っても[インポートエラーはあり得る](https://developer.apple.com/documentation/professional-video-applications/document-type-definition?changes=_2_2)。harnessの平坦・単一ソースXMLに効果／音声／字幕が完全に載ると扱わず、FCP実機で再適用・確認する。
- [OpenTimelineIOのアダプタ一覧](https://github.com/AcademySoftwareFoundation/OpenTimelineIO/blob/main/docs/tutorials/adapters.md)では同梱プラグインの`fcp_xml`はFCP 7 XML、`fcpx_xml`は別の追加アダプタ。[後者の機能表](https://github.com/OpenTimelineIO/otio-fcpx-xml-adapter)は複数トラック、音声、マーカーを扱う一方、トランジション、音声/映像効果、速度変更、CDLを非対応と明示。現行FCPXMLの完全往復経路として採用しない。
- [FFmpegのloudnorm](https://ffmpeg.org/ffmpeg-filters.html)はEBU R128ベースでIL/LRA/True Peakを目標にした単回・二回処理を提供。既存harnessの測定・映像/音声全編デコード・フレーム対応検証は継続し、外部プラグインの見た目や書出しを合格扱いにしない。

結論：最初にMotion、Compressor、音声修復、権利処理済み素材を具体的な不足に合わせて検討する。ノイズ、追跡、色合わせ等は実素材で必要性が出た時だけ追加評価する。FCP 12.4と現行macOSの個別互換は多くのベンダーが公開表で明示していない。
