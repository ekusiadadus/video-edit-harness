# 相対深度による画像レイヤー合成（開発版）

遠い画面領域に登録済みの画像を重ね、近い内容を残すローカル合成です。深度は距離のメートル値でも人物マスクでもありません。髪、手、衣装、他の出演者との重なりを含め、完成映像の確認が必要です。alpha.7には含まれません。

手動の深度フィールド、またはローカルのDepth Anything V2 Smallによる推定を使います。明示指定した場合に、動きを補償する時間方向の補正候補を作れます。セッション内の候補作成・比較・選択・採用・納品に対応します。各フィールドは映像と同じ高さ・幅の `float32` NPYで、有限値0～1、近い内容ほど大きい値を指定します。対象フレーム全体で意味が共通する尺度を使ってください。フレームごとの最大・最小で自動正規化する処理はありません。

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

## フレーム単位の手動修正

推定結果の手や衣装の境界に問題がある場合は、元のartifactを変更せず、指定フレームのfloat32 NPYだけを改訂します。値は同じ0～1・近いほど大きい尺度で指定し、フレームごとに再正規化しません。

```json
{"version":1,"fields":[{"frame":13,"path":"corrections/000013.npy"}]}
```

```sh
uv run video-harness depth correct output/inferred-depth/depth/fields/depth.json correction-request.json \
  --output output/depth-revision --actor codex --note '実フレームの手の境界を修正した候補'
uv run video-harness depth validate output/depth-revision/fields/depth.json
```

version 3 manifestは、元のmanifestのSHA、修正したフレーム、入力フィールドと保持したコピーを記録します。未指定フレームは直前の版から引き継ぎます。次の修正も別の出力フォルダーへ保存でき、以前の修正を保持します。来歴は最大32個のmanifestまで検査し、循環や改変、範囲外の指定を拒否します。元のモデル・生の推定値は親artifactを通じて検証し続けるため、親とモデルを削除しないでください。

ユーザーは自然言語で「13フレーム付近で手が背景に消えないように直して」と指定できます。スキルを使うエージェントが実フレームを確認して修正用フィールドと改訂を保存します。エージェントの修正はactor=codex等で記録し、人による承認とは扱いません。対応する映像を再レンダリングし、自然版・前の版と同じ音声で比較します。


## セッションで使う

パターンを有効にし、自然版の全解像度レンダーを先に作ります。`visual_pipeline_version: 2` の出力に保持した `visual-graded.mp4` を深度の入力にしてください。フレーム番号はこの組み立て済み映像の番号で、カメラ素材の番号とは限りません。推定・手動準備・修正は上のコマンドを使います。

productionへ同じ画面サイズのRGBA画像と権利根拠を登録し、素材IDで指定します。`visual_assets: licensed` または所有素材だけの `own_only` が必要です。`off`、自然パターン、演出強度off、プレビュー解像度、editable FCPは対象外です。FCPはbakedのmix/video_onlyを使います。

```sh
uv run video-harness session depth-layer SESSION BASE_RENDER_ID \
  --manifest output/inferred-depth/depth/fields/depth.json --asset-id IMAGE_ASSET_ID \
  --threshold 0.5 --softness 0.1 --strength 0.5 \
  --actor codex --note '観察した遠景へ画像を重ね、自然版と比較する'
```

返されたcandidateは未採用です。自然版と同じ構成・音声で候補を全解像度レンダーし、比較してから採用します。NATURAL_RENDER_IDには同じmappingの自然版を指定してください。

```sh
uv run video-harness session render SESSION --full --candidate-id CANDIDATE_ID --actor codex
uv run video-harness session compare-candidates SESSION NATURAL_RENDER_ID DEPTH_RENDER_ID
uv run video-harness session adopt-candidate SESSION CANDIDATE_ID --actor codex --note '比較した結果と採用理由'
uv run video-harness session render SESSION --full --actor codex
```

採用は人による最終レビューとは別です。合成は色補正の後、字幕や通常のエフェクトの前です。元のgraded picture、manifest、登録画像のSHAを照合し、色補正変更や改変で一致しなければ拒否します。音声や別エフェクトの改訂では深度設定を保持し、naturalへ戻す操作では解除します。色補正を変える場合は新しいgraded pictureでフィールドを作り直してください。

最終レンダーの正確なSHAに対する `depth_contours` 視覚レビューが必要です。髪・手・衣装・奥の出演者・遮蔽・時間方向の揺れを実動画で確認します。実写3フレームの静止画確認では、奥の出演者が標準しきい値より低い深度になりました。床も近い領域になるため、人物全員を保護するマスクとして自動適用できる品質の証明にはなりません。

納品にはフィールドと修正来歴のフレーム/SHA対応を保持します。公開用の深度証跡は元のローカルパスを除きます。モデルと元画像は外部参照で、バンドル単独の完全な再レンダリングはできません。ローカルの元artifactも保管してください。YouTube向けの完成MP4と人の視聴・試聴確認は別の納品工程です。


## 時間方向の補正を試す

推定値の揺れが見える場合は `depth stabilize` で別の候補を作ります。前フレームの深度を現在の映像の動きへ合わせ、往復のフロー一致・明るさの差・局所的な模様を検査した画素だけ混ぜます。[OpenCVのFarneback optical flow](https://docs.opencv.org/4.10.0/dc/d6b/group__video__track.html)をローカルCPUで使います。人物の識別や、揺れがなくなることの保証ではありません。

```sh
# tracking extraが必要。ほかのoptional機能もsync時に一緒に指定します。
uv run video-harness depth stabilize output/inferred-depth/depth/fields/depth.json \
  --strength 0.5 --fb-tolerance 1 --photometric-tolerance 0.08 --min-coverage 0.5 \
  --output output/stabilized-depth --actor codex --note '同じ区間の揺れと輪郭を比較する'
uv run video-harness depth validate output/stabilized-depth/fields/depth.json
```

`strength` は前フレームの混合比、`fb-tolerance` は往復フロー誤差の許容ピクセル、`photometric-tolerance` は0～1の明るさ差、`min-coverage` は混合可能な画素の最低割合です。strengthとmin-coverageは0超～1、フロー誤差は0超～8、明るさ差は0超～0.5。数値は出発点で、素材に合った品質を保証しません。オフにする場合は補正前のmanifestを使います。

カット後の最初の実フレームを `--cut-frame 120` のように指定します。複数のカットは昇順・重複なしで繰り返し指定してください。指定区間の途中だけが対象です。以前のversion 4で指定したカットは、version 3の手動修正を挟んでも後の補正へ引き継ぎます。自動ショット検出は行いません。カット境界と有効画素が少ないフレームでは履歴を混ぜず、そのフレームの推定値へ戻します。模様の少ない領域は安定化できない場合があります。

version 4のmanifestは元manifestとフィールド、OpenCV版、設定、各フレームの有効割合とリセット理由を保存します。検証は実映像からフローを再計算し、結果のフィールドと完全一致を検査します。同じOpenCV版が必要で、異なる環境で不一致なら成功として扱いません。4096フレームまで、来歴32manifestまで。補正前のartifactは保持し、必要ならversion 3の手動修正を続けられます。

セッションには補正版のmanifestを `session depth-layer` で渡します。音声・フレーム数・時間対応は変えません。完成映像で輪郭、残像、髪、手、奥の出演者、カット境界を確認し、補正前と自然版を残してください。機械による再計算一致は、時間方向の品質や人の承認の証明ではありません。


2026-10-07の実写24フレーム検査では、初期値min-coverage=0.5で全フレームがリセットされ、有効割合は約0.156～0.235でした。明示的な0.15の別候補では先頭以外の23フレームを補正しましたが、静止画差分は輪郭にも出ています。フレーム間の平均差が少し減っても、動きと推定誤差を分離した品質評価ではありません。実写の合成輪郭・全編の時間方向の品質は未承認で、自動採用しません。
