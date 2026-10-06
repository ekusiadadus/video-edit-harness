# 音声の J カット／L カット（alpha.6 後の開発版）

この機能は、選択済みカットの前後に元素材の音声ハンドルを使う候補を作ります。J カットは次のクリップの先頭より前の原音を、画が切り替わる前へ先行させます。L カットは前のクリップの末尾より後の原音を、画が切り替わった後へ延ばします。どちらも指定フレーム分の既存音声を置き換え、映像のカット、画の対応表、全体の尺は変えません。元の音声・映像と編集履歴は保持します。公開済み v0.1.0-alpha.6 には含まれません。

対象は、変速していない順序付きv3計画の発話セッションまたは visual セッションの、隙間のない等速のカットです。ハンドルを取る原音に音声トラックが必要です。J カットでは次のクリップの先頭より前に原音と置換先の余裕が、L カットでは前のクリップの末尾より後に原音と置換先の余裕が必要です。指定した音声置換範囲の重なり、既知の可聴単語や明示的な保護範囲の除去、ハンドル端での既知の単語の分断は拒否します。書き起こしに現れない声まで自動検出して守る機能ではありません。元映像と置換先の音を聞いて判断してください。

まず `doctor` を実行し、対象セッションの計画・元 render・音声を確認します。`session audio-cuts` に渡す JSON は、非空の `events` 配列だけを持ちます。各イベントは下記の全項目が必須で、余分な項目は受け付けません。

| 項目 | 内容 |
| --- | --- |
| `id` | 候補内で重複しないイベント ID。 |
| `kind` | `j_cut` または `l_cut`。 |
| `before_sequence_id` | 音声を先行・延長させるカットの後にあるシーケンス ID。最初のシーケンスは指定できません。 |
| `duration_frames` | 出力 fps で数えた 1 以上の整数フレーム。 |
| `reason` | 編集判断の理由。 |
| `handle_observation` | 元の音声ハンドルを試聴した観察内容。 |
| `replacement_observation` | 置き換わる区間を試聴した観察内容。 |
| `handle_audio_kind` | `nonspoken` または `speech`。 |
| `handle_word_ids` | ハンドルに完全に含まれる実際の書き起こし単語 ID を時刻順に列挙。非発話なら `[]`。 |
| `repeat_word_ids` | 元の選択済み音声または先行イベントですでに聞こえる単語を、このハンドルで再び聞かせる場合の ID。該当しなければ `[]`。 |

単語 ID は文字列または整数で、真偽値は不可です。配列内の重複も不可です。発話セッションでは `handle_audio_kind` と `handle_word_ids` を実際の書き起こし単語・時刻に照合し、繰り返す単語の ID が `repeat_word_ids` と正確に一致することを要求します。これは繰り返しを**明示して認識した**記録であり、聞きやすさの承認ではありません。字幕は原計画とハンドル内の実単語から更新します。例示用 ID を実素材の単語として使わず、元の transcript と `session context` で確かめてください。

visual セッションには単語アライメントがないため、`handle_audio_kind` は `nonspoken`、両単語 ID 配列は `[]` に限ります。この宣言は観察者の入力として記録されるだけで、声がないことを解析で検証した証拠ではありません。声がある visual 素材を発話ハンドルとして扱う経路はありません。

以下は**架空の構造例**です。`second`、2 フレーム、観察文はいずれも実素材についての観察記録ではありません。実際のシーケンス ID と、両区間を試聴して得た内容に置き換えます。

```json
{
  "events": [
    {
      "id": "lead-environment",
      "kind": "j_cut",
      "before_sequence_id": "second",
      "duration_frames": 2,
      "reason": "次の場面の環境音を画の切り替え前に先行させる",
      "handle_observation": "例示用。実素材の次クリップ直前の原音を試聴した結果を書く",
      "replacement_observation": "例示用。置換される前クリップ末尾を試聴した結果を書く",
      "handle_audio_kind": "nonspoken",
      "handle_word_ids": [],
      "repeat_word_ids": []
    }
  ]
}
```

```sh
uv run video-harness doctor
uv run video-harness session audio-cuts SESSION BASE_RENDER_ID --request-file audio-cuts-request.json --actor codex --note '観察した音声接続の候補'
uv run video-harness session render SESSION --candidate-id CANDIDATE_ID --full
```

`audio-cuts` は元 render の素材・計画・対応表に結び付いた**未採用候補**を返します。候補 render の `audio-cuts.json` に置換サンプルと原音への対応が残ります。追加音・音量正規化より前の PCM を作り、発話では実単語の出現位置と `.srt` も更新します。元の画のカットを示す `timeline.fcpxml` は J/L 音声置換前の参考資料です。FCP への J/L 音声の編集可能な表現は未対応で、受け渡しは焼き込み済みの `mix`／`video_only` のみです。`editable` は拒否します。J/L 音声置換と変速の併用も、共通の音声・単語対応がないため未対応です。

候補の両側、全文脈、全編の音を聞き、単語の頭・末尾、息継ぎ、意味、環境音のつながり、繰り返しの自然さを確認します。`session inspect` や音声・字幕の出力は確認に使えますが、生成や技術検査は試聴を証明しません。候補を明示的に採用した後も、納品する**正確な最終 render の SHA-256**に結び付いた人の視聴・試聴レビューが必要です。`audio_cuts` の review check は `listening` に基づいて記録します。FCP GUI の読み込み・再生・書き出し、配信先での再生は、それぞれ実施した範囲だけを報告してください。
