# 相対深度による画像レイヤー合成（開発版）

遠い画面領域に登録済みの画像を重ね、近い内容を残すローカル合成です。深度は距離のメートル値でも人物マスクでもありません。髪、手、衣装、他の出演者との重なりを含め、完成映像の確認が必要です。alpha.7には含まれません。

手動の深度フィールド、またはローカルのDepth Anything V2 Smallによる推定を使います。時間方向の安定化とセッション内の採用操作との統合は未実装です。各フィールドは映像と同じ高さ・幅の `float32` NPYで、有限値0～1、近い内容ほど大きい値を指定します。対象フレーム全体で意味が共通する尺度を使ってください。フレームごとの最大・最小で自動正規化する処理はありません。

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


## ローカル推定

任意の映像を外部サービスへ送らず、公式SmallのローカルsnapshotからCPUで推定します。Smallの[公式モデルカード](https://huggingface.co/depth-anything/Depth-Anything-V2-Small-hf)はApache-2.0です。大型モデルを同じライセンスと扱わず、Smallのみ指定します。

```sh
uv sync --locked --extra depth
uv run video-harness depth fetch-model --output /absolute/path/to/small-model
uv run video-harness depth inspect-model /absolute/path/to/small-model
uv run video-harness depth infer source.mp4 --model /absolute/path/to/small-model \
  --first-frame 12 --end-frame-exclusive 24 --output output/inferred-depth \
  --actor codex --note '実フレームの相対深度を自然版と比較する'
uv run video-harness depth validate output/inferred-depth/depth/fields/depth.json
```

ほかのoptional機能を使う環境では、それらのextraもsync時に一緒に指定します。モデルフォルダーは `config.json`、`preprocessor_config.json`、`model.safetensors`、`provenance.json`を保持します。任意で公式README.mdとLICENSEも保持でき、SHAを記録します。実行可能コード・pickle・symlink・未知の追加ファイルは読み込みません。推論コマンドは自動ダウンロードしません。必要なら `depth fetch-model` で対応する公式版を明示的に取得します。

provenance.jsonには次の形式で、取得元の版と各ファイルの実SHAを指定します。版は40桁のGit revision、SHAは64桁の小文字です。対応する版とSHAはハーネス内の既知の公式値にも照合します。provenance.jsonを書き換えて任意の重みを公式Smallとして読み込むことはできません。追加の版は公式値を検証して対応表へ追加するまで拒否します。

```json
{
  "model_id":"depth-anything/Depth-Anything-V2-Small-hf",
  "revision":"5426e4f0f36572d16453bbda7a8389317b1bef99",
  "license":"Apache-2.0",
  "files":{
    "config.json":"c56698d3643dde1f83ea2212759e6b31a22b8f827246a36dd007ee8a22b3ff75",
    "preprocessor_config.json":"d41175c0d889477ca8fc67191e540faef14baf6275157b3fdecf78469e6bbf84",
    "model.safetensors":"3152477ce0d8d6978d76b995120de97cb5b928701fd0f817769f59e249a16b70"
  }
}
```

この版は2026-10-07に公式repositoryから取得・ローカル読み込みを確認したものです。モデルファイルそのものは配布パッケージに含めません。

推定は生の相対深度をフレームごとに保持し、指定区間全体のminimum/maximumで共通の0～1へ変換します。フレームごとの最大・最小には揃えません。生データから正規化値を再計算して完全一致を検査し、constantな推定、欠落、改変を拒否します。モデル・processor・runtime・補間条件をversion 2 manifestと独立したexecution.jsonへ保存し、SHAと内容を照合します。CLIのrun resultはこれらのartifact全体のSHAを保持します。この記録は改変検知のためのもので、署名された第三者の実行証明ではありません。近いほど大きいという向きは適用する仮定として記録し、メートルや人物マスクとは扱いません。

区間共通の正規化は、推定モデル自体の時間方向の揺れを解消しません。元映像を変えず、推定artifactを残し、必要なら手動版の別artifactを作って修正してください。改訂したdepth.jsonを同じ登録画像・音声条件でrenderし、輪郭と近遠を確認します。実写3フレームの推定成功は記録済みですが、完成動画・追従品質の承認ではありません。
