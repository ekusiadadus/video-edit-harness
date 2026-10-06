# 被写体の追跡と配置検査

追跡はローカル処理です。クラウド送信・人物の同定・自動採用はしません。検証した追跡位置を `tracked_zoom` のアンカーに使えます。追従文字は未実装です。

```sh
uv sync --locked --extra tracking
uv run video-harness tracking track input.mp4 --output track.json --box 0.2 0.3 0.5 0.7
uv run video-harness tracking validate track.json --source input.mp4
```

`--algorithm csrt` でOpenCVのCSRT追跡を選べます。`tracking` extraはMediaPipeと同じ `opencv-contrib-python` に統一し、headless版を併用しません。既定の `lk` は特徴点の幾何変換、CSRTは対象の外観を扱います。CSRTの成功フラグも本人を追えている証明ではないため、初期の見た目との局所的な相関・枠の範囲を検査し、人の確認を残します。モデルを自動ダウンロードする処理はありません。

`template_correlation` はCSRTが返した枠の近傍で測る初期外観との相関で、同一人物の確率ではありません。少量の位置／倍率ずれを許容しますが、失われた状態からこの比較だけで追跡を再開しません。アルゴリズムと実行時OpenCV版を成果物に保存します。実装の根拠は[OpenCVのCSRT API](https://docs.opencv.org/4.x/d2/da2/classcv_1_1TrackerCSRT.html)、依存の選び方は[公式Pythonパッケージの説明](https://pypi.org/project/opencv-contrib-python/)です。

## 身体ポーズを使う候補

`uv sync --locked --extra tracking --extra pose-tracking` を実行し、`--algorithm pose --model LOCAL_MODEL.task` で明示したローカルMediaPipe Pose Landmarkerモデルを使えます。自動取得や動画の送信はしません。モデルSHA、サイズ、MediaPipe版を記録します。[公式モデルとAPI](https://ai.google.dev/edge/mediapipe/solutions/vision/pose_landmarker/python)を確認して用意してください。

この方式の枠は肩と腰の4点から作る胴体領域です。初期の小さな衣装の枠と同じ寸法を保持するものではありません。全身・顔・手足を隠さないことは別途確認します。見え方・存在のスコア、前フレームとの幾何対応で選び、候補が曖昧な場合は停止します。検出配列の番号を人物IDとして扱いません。同じ実ダンス素材・手前の人物の初期枠ではCSRTが74フレーム、姿勢方式の修正版が121フレーム（24fpsで約5秒）の後に喪失しました。衣装の細い枠で比較した13／22フレームとは初期枠が異なります。左側の人物は初期検出されませんでした。全編の同一人物追跡や、どんなダンスにも有効という証拠ではありません。

## セッションで追従ズームを提案する

```sh
uv run video-harness session tracking-source SESSION RENDER_ID
uv run video-harness session track-effect SESSION RENDER_ID --box 0.2 0.3 0.5 0.7 --first-frame 0 --end-frame 24 --algorithm csrt --max-scale 1.12 --strength 0.65 --actor codex --note '実演の対象へ視線を向ける'
```

これは構造例です。観察した枠とフレーム範囲へ置き換えます。最初のコマンドが返す、保持された**エフェクト適用前の映像**を見て指定します。visual編集では色調整前、発話編集では色調整・ミックス後の適用段階です。追跡とズームは同じ段階の入力SHAへ結び付け、色や音・構成の変更で入力が変われば再解析します。完成MP4を追跡したデータを別段階の映像へ流用しません。

成功時に未採用のcandidateを返すので、そのIDで `session render --candidate-id` を実行し、静かな案と比較します。`natural`／追加演出offの案には提案しません。選択区間にlostがあれば失敗し、追跡ファイルを修正用に残します。`--corrections-file` に観察したフレームと枠を指定して再提案できます。追跡枠の中心に向けるズームであり、対象を画面中央へ固定するリフレームとは別です。重なる別ズームとの併用は座標が変わるため拒否します。

`session track-effect` は追跡した枠を `subject` 保護領域として候補に付けます。ズームによる枠の切れと、測定した文字カードとの重なりをフレームごとに検査します。胴体の枠から頭や足先の領域は推定しません。他の踊り手・未宣言の字幕・投稿UIとの関係は実動画で確認します。

`--box` は最初の対象フレームで観察した左・上・右・下を、画面幅／高さに対する0〜1の割合で指定します。背景を大きく含む枠や別々に動く腕・胴体を一緒にした枠は、同じ動きとして追えない場合があります。国籍や人物の同一性は推定しません。

`--start-frame` と `--end-frame` は原動画のフレーム番号で、終了は含みません。`--max-width` は処理解像度の上限で、原動画を変更しません。CFRと実際のタイムスタンプを検査し、VFRは拒否します。

追跡が失われたフレームは `state: lost`、`box: null` になります。低品質の位置を補間せず、手動修正までlostを維持します。修正ファイルは `{"48":[0.2,0.3,0.5,0.7]}` のような、実際に観察した原動画フレーム番号と枠の対応です。`--corrections-file` で新しい成果物を作ります。元の追跡ファイルは上書きしません。

```sh
uv run video-harness tracking validate track.json --source input.mp4 --first-frame 0 --end-frame 24
```

区間指定の検証は、その全フレームに有効な枠がなければ失敗します。`inlier_fraction` は幾何変換に整合した特徴点の割合で、人物同定の確率ではありません。SHA、fps、連続したフレーム列、喪失後の明示修正を検査します。検証成功でも `review_required: true` を維持し、実動画で別人物への乗り移りや枠のずれを確認する必要があります。

## 固定した保護領域

プロジェクトの `composition_guides` は、出力映像で観察した固定領域を宣言します。人物を自動検出する機能ではありません。

```json
{
  "composition_guides": [
    {"id":"visible-action","kind":"subject","rect":[0.2,0.2,0.7,0.9],"output_start":0,"output_end":2,"reason":"この区間で手元を含めて見せる"}
  ]
}
```

上は構造例です。実際の出力区間・fps・位置を観察して指定します。`subject`、`caption`、`ui` を使えます。測定した `keyword_title` の矩形が保護領域に重なる場合、または `smooth_zoom` が宣言した人物領域を切る場合、レンダーは失敗して修正を求めます。対応外の効果は `not_checked_for_this_effect` と記録し、検査済みと扱いません。動く人物、未宣言の対象、画面上の読了時間は自動検証していません。

## 動く保護領域

固定の `rect` の代わりに `track_path` を指定できます。実際のエフェクト前入力を追跡したJSONを使います。

```json
{"composition_guides":[{"id":"observed-torso","kind":"subject","track_path":"/absolute/path/track.json","output_start":"1/2","output_end":"3","reason":"この区間の観察した胴体を保護する"}]}
```

これは構造例です。実素材の有効区間へ置き換えます。解決時に追跡ファイルSHAを保存し、描画・納品時に再検査します。fps、連続した有効な枠、実入力SHAも一致が必要です。`subject` と `caption` が対象で、投稿UIは画面に固定した `rect` を使います。追跡枠はエフェクト前の座標で、ズームの描画順とイージングを使って出力位置へ変換します。測定した `keyword_title` が1フレームでも重なれば、イベント・領域・フレームを示して修正を求めます。`subject` のズーム見切れも拒否します。画面分割・別素材比較との組み合わせは座標対応が未実装のため拒否します。

検査は追跡枠だけが対象です。本人確認、全身の検出、文字を人物に追従させる描画、文字の自動再配置、読む時間の判断は行いません。セッションの提案は未採用のまま比較・レビューします。

## 時間を変える編集の実装状態

`time_mapping.compile_retime` はスピードランプと静止保持の出力→原動画フレーム対応表を生成します。発話などの保護区間に触れる変更を拒否し、間引き／重複フレームを記録します。`retime prepare`／`retime render` が対応表どおりの単独MP4、音声伸縮、観察した字幕のSRT移行を扱います。[時間変更の手順](RETIME.ja.md)を参照してください。セッション候補・FCP時間変更・既存cueや追跡の移行は未接続です。時間を変更した映像に古い追跡を流用せず、実際の入力を再追跡します。
