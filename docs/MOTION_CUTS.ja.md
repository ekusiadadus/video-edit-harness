# 動きの方向に合わせてカット位置を提案する

alpha.7以後の開発版の `session motion-cuts` は、隣接する2ショットの観察済み候補フレームを比較します。画像の動く方向と速さが近い候補を、レビューが必要な編集計画として保存します。構成・動作の意味やカメラ移動の補正は判断できません。このコマンドはトランジションを描画しません。別の `session transitions` コマンドで、指定したディゾルブ／プッシュを比較候補にできます。[開発状況](TRANSITIONS.ja.md)を参照してください。

1. 現在の計画を選択し、renderを作ります。元素材で、前のショットの終点と次のショットの始点の候補、観察する領域を確認します。
2. request JSONを作り、変更してよい非発話区間を素材ごとのフレーム番号で宣言します。音量だけで非発話と判断しません。
3. `motion-cuts` を実行し、各候補の `measured`／`uncertain` と比較結果を確認します。対応する候補があれば計画は `proposed`、セッションは `needs_selection` になります。採用や人の承認を自動記録しません。
4. source区間・内容・音声を確認して選択し、再描画します。構成比較モードで元のrenderと比較し、新しいrenderのSHAに対して視聴・試聴レビューを記録します。

```sh
uv run --no-sync video-harness session motion-cuts SESSION RENDER_ID --request-file motion.json --actor codex --note '観察した動作の方向がつながるカット候補を比較する'
```

次は形式の例です。ID・フレーム・領域・理由は実素材の観察値に置き換えてください。sourceのフレーム番号は0始まり、終点は含みません。ROIは画像左上を原点とする正規化された `[左,上,右,下]` です。

```json
{
  "version": 1,
  "left_segment_id": "observed-left-shot",
  "window_frames": 6,
  "left_box": [0.3, 0.2, 0.7, 0.8],
  "right_box": [0.3, 0.2, 0.7, 0.8],
  "choices": [
    {"left_end_frame": 48, "right_start_frame": 72, "reason": "観察した動作の区切り"},
    {"left_end_frame": 50, "right_start_frame": 74, "reason": "次の動作へつながる別候補"}
  ],
  "nonspoken_intervals": [
    {"asset_id": "your-registered-video", "first_frame": 40, "end_frame_exclusive": 80, "reason": "実聴で発話がないと確認した区間"}
  ]
}
```

`window_frames` は3〜12、候補は1〜12個です。候補終点直前と始点直後を解析し、source SHA・実フレーム番号・FPS・ROI・OpenCV版・計測値・不確かさ・actor・理由を保存します。非発話区間の宣言はASRや人の試聴を実行した証明にはなりません。実際に確認したactorと理由を記録してください。

特徴点の往復追跡誤差、残存数、方向の一致、複数フレームでの安定性を検査します。静止・模様の少ない領域・相反する動き・映像の断絶は不確かとして扱います。45度以内の方向差と2.5倍以内の速度比は候補選別のヒューリスティックで、良い編集の保証ではありません。細かい操作や読む時間を削らないよう内容を別途確認します。

visual計画に対応し、retime・J/Lカットとの併用は未対応です。フレームを変更した場合、古いcue・effects・composition guidesを無効化して一覧を返します。元のartifactとrenderは保持します。明示した効果・音ハメ・字幕領域は新しい時間対応で作り直してください。不確かな比較、互換候補なし、元と同じ終始点の場合は計画を変更しません。
