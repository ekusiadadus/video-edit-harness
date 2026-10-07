# 曲の拍でエフェクトの頂点を合わせる

開発版の`session beat-effects`は、配置済み音楽の実SHAと切り出しに結び付いた拍を使い、選んだ拍でズーム／彩度演出の頂点が来る候補を作ります。曲全体の毎拍へ自動で演出を載せません。投稿・TikTok内の音源追加・人の採用は行わず、公開alpha.7にも含みません。

ユーザーは「この曲の見せ場だけズーム。自然版も残して」「この拍だけ弱く」「動きを抑えて」と指示できます。エージェントが現在の完成レンダーから音楽cueと素材SHAを確認し、実音源の拍を解析して選びます。自動検出した拍は、強拍・サビ・動作の頂点を証明しません。候補を聴き比べて修正します。

```sh
uv run --no-sync video-harness production beats assets/music.wav --librosa --output music-beats.json
uv run --no-sync video-harness session beat-effects harness/session RENDER_ID \
  --request-file beat-effects-request.json --actor codex --note '選んだ見せ場の拍だけを強調'
uv run --no-sync video-harness session render harness/session --full --candidate-id CANDIDATE_ID
```

`librosa`はbeat-analysis extraの導入が必要です。既存のextraを消さないように環境を確認してください。BPM指定は均一な仮のグリッド、未指定の軽量解析はtransient hintsです。実音声を解析した結果と区別します。クラウドやASRへ送信しません。

requestは以下の項目を持つversion 1です。

| 項目 | 指定 |
|---|---|
| `version`、`id` | `1`と重複しない演出名 |
| `cue_id` | 現在のproductionにあるmusic cue ID |
| `beat_map` | その登録曲を実際に解析したJSONオブジェクト全体 |
| `beat_indices` | 選択cueへマッピングされた拍の0始まりの番号。元音源全体の番号とは異なる |
| `window_frames` | 3〜301の奇数。両端が元の強さに戻り、中央フレームが頂点になる |
| `strength`、`parameters` | 既存beat_focusテンプレートの強さ・アンカー・倍率・最低彩度 |
| `reduced_motion` | trueで追加ズームを省き、彩度変化を小さくする |
| `protected_intervals` | 演出を重ねたくない出力秒数の区間配列。発話／手順の保護は実観察から指定 |

元曲のsource_start、trim、loopを通して最寄りの出力フレームへ量子化します。`motion_template`証跡に曲SHA、元解析、選択cue、量子化誤差、ピークフレーム、実操作を保存し、全編レンダー／配布へ引き継ぎます。端で欠ける演出、保護区間との重なり、選択区間の重なり、古い音源SHA、保存された音楽phase/audio_retime時計は拒否します。JSONを手直しして古い拍を新曲の検出結果へ見せかけないでください。

カットを拍へ動かす場合は先に`session propose-beats`で実ソース範囲に結び付いた計画を作り、確認して全編レンダーします。速度変化のあとで新しい音楽配置に演出を載せます。beat-effects単体はカット・音声・速度を変えません。動きを抑える指定も、すでにある速度変化や他の演出を解除する意味ではありません。

完成MP4をスマホで全編視聴・試聴し、顔や足先、音のアクセント、字幕の衝突を確認します。技術的なピークフレームの一致と、人が感じる音ハメの良さは別です。利用条件・Content ID・投稿先の確認も残ります。
