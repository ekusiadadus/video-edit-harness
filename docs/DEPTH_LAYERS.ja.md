# 相対深度による画像レイヤー合成（開発版）

遠い画面領域に登録済みの画像を重ね、近い内容を残すローカル合成です。深度は距離のメートル値でも人物マスクでもありません。髪、手、衣装、他の出演者との重なりを含め、完成映像の確認が必要です。alpha.7には含まれません。

現在は手動で用意した深度フィールドを使います。自動推定モデル、時間方向の安定化、セッション内の採用操作との統合は未実装です。各フィールドは映像と同じ高さ・幅の `float32` NPYで、有限値0～1、近い内容ほど大きい値を指定します。対象フレーム全体で意味が共通する尺度を使ってください。フレームごとの最大・最小で自動正規化する処理はありません。

## 準備

フレーム番号は元映像の0始まりです。対象区間内の全フレームを連続して指定します。request.jsonの相対パスはrequest.jsonのあるフォルダーから解決します。

```json
{"version":1,"fields":[
  {"frame":12,"path":"depth/000012.npy"},
  {"frame":13,"path":"depth/000013.npy"}
]}
```

```sh
uv run video-harness depth prepare source.mp4 request.json \
  --output output/depth-preparation --actor codex --note '実フレームに対応する手動の相対深度'
uv run video-harness depth validate output/depth-preparation/fields/depth.json
```

元映像、入力フィールド、保持したコピーを残してください。SHA・fps・フレーム・画面サイズ・値の範囲・欠落を検査します。改訂時は別の出力フォルダーを使います。

## 合成

画像は既存のproduction素材登録フローで権利根拠を登録します。`--asset`には登録済み素材レコード、`--policy`にはasset_policyの内容を渡します。Rec.709のゼロ開始タイムスタンプを持つ映像と、映像と同じ画面サイズのRGBA画像が対象です。画像RGBもRec.709の符号化値として扱い、ICC変換は行いません。画像を勝手に拡大・切り抜きしません。回転・表示変換を持つ入力は座標の取り違えを防ぐため拒否します。必要なら向きを確定したRec.709映像を別ファイルで作り、その映像に対応するフィールドを準備してください。

```sh
uv run video-harness depth render source.mp4 output/depth-preparation/fields/depth.json \
  --asset registered-image.json --policy asset-policy.json --input-color rec709 \
  --threshold 0.5 --softness 0.1 --strength 0.5 \
  --output output/depth-candidate --actor codex --note '遠景だけに画像を重ねる比較案'
```

しきい値より近い領域は元映像を残します。境界のsoftnessは滑らかな混合幅、strengthは画像の強さです。対象区間以外は合成せず、全映像を再エンコードします。圧縮による画素差はあり得ます。音声がある場合はコピーし、デコード後のPCM一致を検査します。

出力のvideo.mp4とdepth-render.jsonは比較用の未採用候補です。全デコード、fps・フレーム数、音声一致は技術検証であり、輪郭品質や視聴者への効果を証明しません。自然版と同じ音声・区間で比較し、境界の揺れ、抜け、画像が顔や必要な情報を隠す箇所を確認してください。モデルによる自動追従、ネイティブFCPの深度エフェクト、投稿先の再生確認は含みません。ユーザーのYouTubeアップロードはユーザー自身が行います。
