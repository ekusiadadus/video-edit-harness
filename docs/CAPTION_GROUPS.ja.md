# 意味のまとまりで字幕を区切る（開発版）

「否定表現を分けない」「名前と単位を一緒に見せる」「英語を句で区切る」と指定できます。スキルは実際の発話の単語IDと出現番号から区切り案を作り、未採用候補として描画します。従来の文字数による自動分割も保持します。公開alpha.7には含まれません。

確認済みの書き起こしを使い、誤字・専門用語・否定・単位は先に`session correct-transcript`で校正します。新しい書き起こしや発話時刻を推測する機能ではありません。クラウド書き起こしには元素材ごとの許可が必要です。字幕を言い換えたり、読む時間を増やすために時刻を変更したりしません。

## 指定と候補作成

描画済みの発話セッションから、実際の表示順・時刻・単語IDを取り出します。

```sh
uv run --no-sync video-harness session caption-source SESSION RENDER_ID > caption-source.json
```

結果の`word_stream_sha256`、`words`とカット境界`junctions`を使います。同じ単語IDが繰り返される場合は`occurrence_index`で区別し、整数IDは整数のまま指定します。すべての表示単語を一度ずつ、順番どおりに含めてください。

次のJSONは形の説明です。hash・ID・出現番号は実際の結果から取得し、例を素材データとして使わないでください。

```json
{
  "version": 1,
  "word_stream_sha256": "REPLACE_WITH_OBSERVED_WORD_STREAM_SHA256",
  "language": "ja",
  "protected_phrases": ["ではありません。", "120 fps"],
  "groups": [{
    "id": "negation",
    "word_refs": [{"word_id": "OBSERVED_WORD_ID", "occurrence_index": 0}],
    "reason": "否定表現を含む実際の句を一緒に表示する"
  }],
  "reading": {"minimum_seconds": 0.8, "maximum_units_per_second": 12}
}
```

`language`は`ja`または`en`です。保護語句は実際に結合される字幕と完全一致させます。英数字同士の単語間には従来どおり空白を入れるため、「120」「fps」に分かれた素材では「120 fps」です。出現しない語句は字幕に追加しません。保護語句を途中で分割する案は拒否します。

読み時間の数値は編集者が選ぶ点検の目安です。日本語は空白以外のUnicodeコードポイント数、英語は空白で区切られた語数を秒数で割ります。書記素・表示幅・理解難度の測定ではなく、長い英単語も1語と数えるため、これだけで読みやすさは保証できません。

```sh
uv run --no-sync video-harness session caption-groups SESSION RENDER_ID \
  --spec-file caption-groups.json --actor codex --note "実際の句を確認して字幕案を作成"
uv run --no-sync video-harness session render SESSION --candidate-id CANDIDATE_ID --full
```

提案時に字幕文と、短い表示・速い読み量・句読点の区切り・字幕同士の時間重なりを返します。警告は人が見直すためのもので、時刻の自動変更や自動承認をしません。候補作成は採用中のprojectを変更しません。

## 時刻と検査

元の単語時刻をフレームにそろえた実カットから出力時刻へ移します。発話retimeでは実際の単語保護フレーム、J/Lカットでは実際に聞こえる単語のPCMサンプルを使います。単語ID・順番・表記が保たれる変速では同じ区切りを使えます。単語の省略・並べ替え・表記修正でhashが変わる場合は新しい案が必要です。カットをまたぐ区切り、未知・重複・欠落したIDを拒否します。

`subtitles.srt`と`caption-evidence.json`には、表示時刻・区切り・理由・警告とSRTのSHAを記録し、セッション登録と納品でもSHAを検査します。単語証跡のない旧renderは元設定で再描画してください。実単語のないvisualセッションには適用しません。

意味の区切りを記録・検証する機能で、意味や文節の完全な自動理解ではありません。句読点の警告は基本的な点検で、日本語組版の全要件への適合は保証しません。[表示幅・禁則の折り返し](CAPTION_LAYOUT.ja.md)は別の描画工程です。通常のYouTubeでは別SRTで、縦型MP4に焼き込む場合は`tiktok-export --subtitles`を使い、完成映像の正確なSHAを再レビューします。

スマホ実寸で字幕・主役・投稿UIの重なり、読む時間、内容の理解を確認し、音声のみでも意味が保たれるか試聴してください。合成試験は人の承認ではありません。MP4のアップロードはユーザー本人が行います。
