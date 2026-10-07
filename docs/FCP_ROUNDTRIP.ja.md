# FCPの読み込みと素材コピーを含む往復検査

開発版。公開alpha.7とは別です。XMLのDTD検査、実GUI読み込み、返却XMLの照合、完成動画の映像／音声一致、人の試聴は別々に確認します。

## モノラル素材とプロジェクト出力

2026-10-07、Final Cut Pro Creator Studio 12.4（454072）で、モノラル音声付きの2秒の合成素材を単一asset-clipとして読み込みました。元のproject sequenceの`audioLayout="mono"`には「予期しない値」の警告が出て、FCPから返した1.14 XMLのsequenceは`stereo`でした。元assetの音声チャンネルは1のままでした。

ハーネスの新しい書き出しでは、モノラル／ステレオ素材のプロジェクト出力を`stereo`とし、元assetのチャンネル数を保持します。修正版の最小XMLは同じ検証用ライブラリへ警告なしで読み込めました。素材をステレオ音源へ書き換える操作ではありません。

[AppleのTimeline Attributes](https://developer.apple.com/documentation/professional_video_applications/fcpxml_reference/story_elements/timeline_attributes)にはmonoを含むレイアウトが記載されています。本修正は、今回実測したトップレベルproject sequenceの挙動に基づきます。すべてのXML要素でmonoが不正という意味ではありません。

## FCPがライブラリ内へコピーした素材を比較する

通常の`check-fcp`は参照パスを比較します。FCPが素材をライブラリ内のOriginal Mediaへコピーするとパスが変わるため、厳密なパス比較は失敗します。明示的に`--allow-media-relocation`を付けると、元と返却先の実ファイルを読み、SHA-256とバイト数が一致することを要求します。

```sh
uv run --no-sync video-harness check-fcp reference.fcpxml \
  returned.fcpxmld/Info.fcpxml --allow-media-relocation \
  --output output/fcp-roundtrip
```

このモードは比較した全clipの素材を実際に検査し、パスとSHAを`media_evidence`へ保存します。素材の不足、差し替え、検査中の変更は失敗します。clipの数・開始・配置・長さ・sequenceの長さも引き続き比較します。ファイル名やFCPのuidだけで同一素材とは判定しません。指定しなければ従来のパス比較を維持します。

最初の最小XMLをFCPから書き戻し、同じ素材・時間範囲を持つ修正版XMLと比較しました。修正版そのものの再書き出しは未実施です。実測では元素材とFCPがコピーした素材は26,605 bytes、SHA `a1c8e2a7ab01beabaad84f173782f1d0fac5bb9fdfe149819242b2f6a1b2afca`で一致し、平坦な時間対応の照合に成功しました。これは**実FCPから取得した返却XMLと実ファイル**による確認です。再生や画素・音声ミックス一致の証明ではありません。

## 今回確認できていない範囲

音量キーフレーム・接続画像・タイトルを含む複合XMLもステレオ出力へ再生成しましたが、読み込みを実行した直後にウィンドウが取得できず、FCPの停止を確認しました。新しい障害レポートは見つかっていません。以前の07:06のSIGABRTレポートは、この試行の原因を示しません。

複合XMLの読み込み・再生・書き出し一致は未受入です。最小XMLの成功を複合機能の成功へ広げません。往復検査のscopeは平坦な素材と有理数時間で、未知のeffectは未検証として報告します。元の完成MP4と編集素材を保持し、焼き込み納品と編集可能な納品を区別してください。

証跡は`output/implementation-maya/fcp-minimal-import-20261007/`の`observations.json`、2本の最小XML、`minimal-returned.fcpxmld/Info.fcpxml`、`roundtrip-relocated/roundtrip.json`、GUI画像、複合XMLと生ログです。個人のライブラリは編集せず、Harness Pattern QA 20261006だけを使用しました。
