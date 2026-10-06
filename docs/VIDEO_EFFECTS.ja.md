# 映像効果の指定と確認

この文書は作業ツリーで追加中の `video_effects` 契約を記述する。公開済み alpha.5 の機能として扱わず、利用前に現在のCLI help、実装、テストと実レンダーを確認する。映像の魅力は効果の数で測らない。話の要点、動作、感情の変化、最後の答えを先に定め、効果はその一点を読み取りやすくするために使う。

## 設定

追加中のパラメーター付き効果は `smooth_zoom` と `saturation_pulse`。`uv run video-harness effects-catalog` で対応パラメーターを確認できる。旧4種類は描画互換を保持する。旧 `split_screen` は同じフレームを反転したミラーであり、2素材比較ではない。

`comparison_wipe` は独立した登録映像を使用する。`parameters` に `asset_id`、`source_start`（その素材のフレーム境界）、`divider`（0.05〜0.95）、`layout` を指定する。`wipe` は同じ画角のBefore／After向けに右側を差し替え、`side_by_side` は両素材全体をそれぞれのパネルへ縮小して収める。余白を許容して主役の切れを避ける。音声は元の編集だけを保持し、比較素材の音声は使用しない。素材SHA、尺、CFR、利用ポリシーを検査し、`visual_assets: own_only` をライセンス素材で黙って回避しない。

`keyword_title` は明示した重要語をフェード／短い上昇で見せる。`parameters` は `text`（最大120文字・3行）、`x`／`y`、`font_size_fraction`（0.02〜0.12）、`foreground`／`background`（`#RRGGBB`）、`motion`（`fade`／`rise`）、任意の `font_path`。文字カードの実測矩形とフォント／PNGのSHAを記録する。文字と背景の指定色は4.5:1以上を要求するが、アニメーション中の透過・完成画面・読む時間の確認を代替しない。顔・手・字幕・投稿UIを自動検出して避ける機能ではない。配置を調整して全編確認する。

`smooth_zoom` の `parameters` は `anchor_x`／`anchor_y`（0〜1の画面座標）、`max_scale`（1〜1.5）、`easing`（`smoothstep`／`cosine`）。これは手動アンカーで、被写体追跡や顔・足先を守る自動検査は未実装。`saturation_pulse` は `minimum_saturation`（0〜1）と同じイージングを持つ。新効果は入口・出口で変化をゼロに戻し、3フレーム以上を必要とする。`strength` はズーム量・彩度低下量へ反映する。

## 局所修正を候補として作る

現在のレンダーに対する追加・変更・削除をJSON配列にして指定する。時間は実レンダーの出力時間・フレーム境界から決める。以下は構造例であり、時刻を実素材から確認する。

```json
[
  {"action":"add","event":{"id":"focus","type":"smooth_zoom","output_start":2,"output_end":3,"strength":0.5,"reason":"実演対象へ視線を向ける","parameters":{"anchor_x":0.35,"anchor_y":0.5,"max_scale":1.12}}}
]
```

```sh
uv run video-harness session effects SESSION RENDER_ID --operations-file operations.json --actor codex --note '実演対象を控えめに強調'
```

返されたcandidate IDで `session render --candidate-id ID` を実行する。元の採用版は変えず、レンダー候補の色・音設定を引き継ぐ。`update` は `id` と `changes`（強さ・パラメーター・時間・理由）、`remove` は `id` を指定する。効果を戻す場合は元候補を再利用する。候補の採用と全編レビューは別操作。

`session compare-candidates` のページは同期再生・再生位置移動・案ごとの音声切替・選択メモ保存に対応する。保存JSONは修正提案であり、自動採用や人の承認には使わない。ブラウザーがローカル動画を読める環境で開く。

控えめな自動案は、作品の `project.json` にプリセットを指定する。

```json
{"video_effects":{"preset":"subtle","intensity":"low"}}
```

`pop_dance` はズームと短い分割画面を提案する。カラー枠は自動追加せず、明示イベントを指定した場合に限る。強度は `low`、`medium`、`high`。プリセットは**実際の編集カット境界**を基準に提案する。曲を指定しただけで拍位置を推定したことにはならない。どのカットへ何を適用するか、提案とレンダー証拠を確認する。演出の密度が高くても、見せたい動作や説明を隠すなら採用しない。

時間を明示する場合は、現在の `frame-mapping.json` の内容から計算したSHA-256に結び付ける。次は**構造例**で、ID・秒・SHAは実素材の値ではない。ゼロのSHAをそのまま入力しない。

```json
{
  "video_effects": {
    "version": 1,
    "mapping_sha256": "0000000000000000000000000000000000000000000000000000000000000000",
    "events": [
      {"id":"example-opening","type":"zoom_pulse","output_start":1.0,"output_end":1.5,"strength":0.35,"reason":"説明の最初の実演に視線を向ける"},
      {"id":"example-compare","type":"split_screen","output_start":4.0,"output_end":5.5,"strength":0.5,"reason":"同じ動作を左右に並べて視覚的なアクセントを置く"},
      {"id":"example-turn","type":"monochrome","output_start":8.0,"output_end":9.0,"strength":0.4,"reason":"話題の転換を短く示す"},
      {"id":"example-payoff","type":"color_frame","output_start":12.0,"output_end":12.6,"strength":0.3,"reason":"答えを提示する瞬間にアクセントを置く"}
    ]
  }
}
```

明示イベントは `id`、対応する `type`、編集**後**の `output_start`／`output_end`、0〜1の `strength`、具体的な `reason` を持つ。古いmappingへの指定、範囲外・矛盾した配置、未対応の種類は失敗として表示する。`natural`／追加演出offを指定した作品へ効果を暗黙に残さず、効果との明示的な衝突は黙って無視しない。速度ランプ、glitch、FCPの第三者プラグインはこの契約にない。似た見た目へ勝手に置換しない。

## 編集と検証の手順

追跡ズーム `tracked_zoom` は、保持したエフェクト前の入力に対する検証済み追跡JSONを使用する。`session tracking-source`／`session track-effect` の手順は [TRACKING.ja.md](TRACKING.ja.md) に記載している。入力・追跡SHA、fps、選択区間を検査し、喪失や重なるズームを拒否する。身体ポーズ方式の枠は胴体であり、全身の見切れ防止や人物同定の証明ではない。追跡した保護領域との文字の重なり・ズーム見切れはフレームごとに検査する。未宣言の顔や足先は保護対象へ自動追加しない。

1. 元素材から問い・導入、情報または感情の変化、結論・見せ場を選ぶ。使うBロールは説明中の対象や動作を示すものにする。音声が許す箇所だけJ/Lカットでつなぎ、語尾・息・環境音を守る。寄りや効果音は意味のある強調へ絞り、前後に視聴者が理解できる余白を残す。
2. ユーザーが指定した効果の**種類・強さ・時間**を上記設定へ写す。拍に同期させるなら、許可済み音源の解析結果、実際のtrim／loop／cueから得た**出力側の拍時刻**を使用する。拍の位相や半拍／倍テンポが曖昧なら、その効果は提案待ちと記録する。
3. 同じ原映像範囲・発話・音量で、効果ありと静かな版を比較する。各イベントの開始・最大・終了フレームを見て、急な段差、顔・手元・字幕・UIとの重なり、色や動きの不快さを確認する。縦版は実際の9:16出力で再確認する。素材利用条件と音声cueは別々に検証する。
4. 要求したイベントと実際に適用されたイベント、却下理由、出力SHA-256、判定者、視聴・試聴の根拠を残す。技術的なdecodeやフィルタ証拠は人の評価を代替しない。変更後の全編、字幕、音声、縦版、納品レビューは新しいSHAに結び直す。

効果を含む完成MP4を渡す場合、mix／video-onlyのFCP経路はその絵を焼き込む想定。editable FCP XMLで効果の同等な編集可能レイヤーが表現できないときは、エラーとして扱い、対応済みと称しない。FCP GUIでのimport・再exportや配信先再生は別の確認である。

ローカルの32秒デモが作られていても、YouTubeへのアップロードや公開の証拠ではない。アップロードは、その素材・宛先について別途明示された指示がある場合だけ実行する。

## FCPで手作業を行う場合の一次資料（2026-10-06確認）

- [Apple: Create split edits](https://support.apple.com/guide/final-cut-pro/ver1632d82c/mac) — 音声と映像の編集点を別々に扱う手順。J/Lカットの説明は編集意図のガイドであり、本ハーネスが任意の発話を自動で分割したという主張ではない。
- [Apple: Add video effects](https://support.apple.com/guide/final-cut-pro/ver4e33bc9/mac) — FCP側での効果追加と調整。
- [Apple: Add video effect keyframes](https://support.apple.com/guide/final-cut-pro/ver8e3f20ea/mac) — FCPのパラメータアニメーション。ハーネスの焼込み効果と編集可能なFCPキーフレームは別物として検証する。

フックの配置、アクセントの密度、音楽との相性は編集上の提案であり、視聴維持率の実測結果ではない。
