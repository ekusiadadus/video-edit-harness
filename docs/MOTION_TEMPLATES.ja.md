# 複合モーションテンプレート（開発版）

個別のエフェクトを毎回組み立てず、目的に応じた組み合わせを既存renderの正確な出力区間へ指定します。ローカルで描画する版付きレシピで、Final Cut ProのMotionテンプレートやTikTokネイティブエフェクトを取得する機能ではありません。alpha.7には含まれません。

| テンプレート | 通常 | `reduced_motion: true` |
|---|---|---|
| `beat_focus` | 同じ区間の滑らかなズーム＋彩度の変化 | ズームを外し、彩度の変化を小さく制限 |
| `reveal_callout` | 前半のズームから後半の要点ラベルへ | 全区間にフェードの要点ラベルのみ |

`beat_focus`の名前は拍の自動検出や音ハメの保証を意味しません。実際の音楽と動作を観察して区間を指定してください。動きを抑える版も彩度変化やフェードがあるため、完全に静止した表示を望む場合は自然版を使ってください。文字の読む時間、顔や手、投稿UIとの重なりを確認してください。3フレーム等の下限は技術的な条件で、読みやすさを保証しません。

```sh
uv run --no-sync video-harness motion-templates
uv run --no-sync video-harness session motion-template SESSION RENDER_ID \
  --request-file template.json --actor codex --note '観察した見せ場の比較案'
uv run --no-sync video-harness session render SESSION --full --candidate-id CANDIDATE_ID
```

`template.json`の例です。秒数は実renderのfpsでフレーム境界に合わせてください。この例の区間を素材の見せ場とみなしてはいけません。

```json
{
  "version": 1,
  "id": "focus-01",
  "template": "beat_focus",
  "output_start": "2",
  "output_end": "3",
  "strength": 0.5,
  "reason": "観察した動作と音楽のアクセントを強調する比較案",
  "reduced_motion": false,
  "parameters": {
    "anchor_x": 0.5,
    "anchor_y": 0.5,
    "max_scale": 1.1,
    "minimum_saturation": 0.8
  }
}
```

`reveal_callout`では`parameters.text`に実際の要点を指定します。`x`、`y`、`font_size_fraction`、`font_path`でラベルを調整できます。ラベルは単行のversion 1です。必要なら個別のversion 2文字効果で改行を指定してください。既存の構図ガイド・文字衝突チェックを省略しません。

指定は既存効果への追加となり、同じidから作られる効果が既にあれば拒否します。再指定では古い効果を`session effects`で明示的に削除してから、新しい候補を作成してください。未知のパラメーター、範囲外やフレーム境界に合わない区間は拒否します。自然／offのパターンには追加できません。

候補は自動採用されません。リクエスト、展開された各効果、元renderとmappingのSHA、actorと理由を保持します。同じ音声・mappingの自然版と`session compare-candidates`で比較し、全編と局所を確認してから採用してください。時間長は変えず、環境音声を元の時間軸に保持します。焼き込みMP4／FCPのmix・video_onlyが対象で、編集可能なFCPレイヤー、深度合成、被写体追跡をこのレシピだけで実現するものではありません。
