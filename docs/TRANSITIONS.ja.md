# 素材を重ねるトランジション

alpha.7後の開発版は、`session transitions` で隣接カットのディゾルブ／上下左右プッシュを未採用の比較候補として作れます。immutableなalpha.7には含まれません。自然版／演出オフ、リタイム・J/Lカットとの組み合わせ、Apple Log／HDR、編集可能なFCPトランジションは非対応です。

まず非自然パターンを選び、ソースのカット位置を選択した全編を描画してください。そのrender IDを使います。CLIの `--help` で手元の版の対応を確認します。

```sh
uv run --no-sync video-harness session transitions SESSION RENDER_ID \
  --request-file transitions.json --actor codex --note '指定したカットを左へのプッシュでつなぐ'
uv run --no-sync video-harness session render SESSION --full --candidate-id CANDIDATE_ID
```

`transitions.json` の例です。IDは実際の選択済みplanに置き換えてください。最初のショットの後ろ、次のショットの前に十分な実素材がある必要があります。

```json
{
  "version": 1,
  "events": [{
    "id": "push-1",
    "left_segment_id": "actual-left-segment-id",
    "before_frames": 3,
    "after_frames": 3,
    "type": "push",
    "direction": "left",
    "reason": "観察した移動方向を続ける指定の演出"
  }]
}
```

`type` は `dissolve` または `push`。`direction` はpushだけに指定し、left/right/up/downを選びます。窓はカットの前後に各1フレーム以上、合計1秒以内かつ120フレーム以内で、隣接区間をはみ出す指定や窓の重複を拒否します。方向は自動推測しません。動きの測定は `session motion-cuts` の別機能であり、方向が近いことだけで動作の意味や美しいつながりを保証しません。

準備時と描画時に登録素材の権利・ソースSHA・バイト数・fps・フレーム数を検証します。保持した `visual-base.mp4` のSHAに提案を結び付け、同じプレビュー／全解像度条件で候補を描画します。尺・出力フレーム数・fpsを保ち、環境音声は元のカット順を維持します。既存のcue／effects／構図ガイドは新mappingに対して作り直すため、候補では解除します。後から追加する演出は候補renderに結び付けてください。

各出力フレームに両素材の実source frame IDと混合比／方向を残します。混在fpsではnormalized CFRの位相を維持するため、境界のsource frame IDが反復する場合があります。選択範囲の外に実素材がない場合は拒否し、欠落フレームを捏造・クローン補充しません。画像は同じcanvasへfit/padして1フレームずつ合成します。ディゾルブはencoded RGBの整数混合であり、linear-light合成やHDRではありません。プッシュは実際の2素材を整数ピクセルで動かします。

自然版は同じplan・ソース・色・音声条件で候補として作成し、`session compare-candidates SESSION NATURAL_RENDER TRANSITION_RENDER` で同期比較できます。元のカットmappingを検証したうえで、各案の合成mapping SHAとトランジション指定を別々に残します。通常のfeedbackとinspectは両映像の実フレームを返し、元カットは `cut_reference` として明記します。inspectの `audio_source_spans` は環境音声の元カット対応で、映像の余白を音声として扱いません。

成功したdecodeは人の視聴レビューではありません。実素材で全編を見て、動作・顔・手・画面端・テンポ・音とのつながりを確認し、最終MP4の正確なSHAを指定したreviewに `transitions` のvisualチェックを追加してください。候補の採用と最終reviewは別です。MP4／FCPのmix・video_only納品には合成済み映像を使います。`original-cut-reference.fcpxml` は元のハードカットの参照で、編集可能なトランジションではありません。自然版へ戻す候補ではtransitionsも解除します。

内部処理は `transition_mapping.compile_transitions`、`transitions.prepare_transitions`／`render_transition_setting`、`transition_feedback.attach_transitions` です。低レベルbackendの全編video/audio decode・fps・フレーム数・PCM一致と、候補→feedback→比較→review→MP4納品の検証は合成テスト素材で行いました。実ダンス素材の6秒比較でもdecode・フレーム数・PCM一致を確認しましたが、今回のつなぎでは顔や手の二重像／画面端の分断が見え、自然な編集の案として採用していません。合成済みpushのFCP GUI読み込みと再生進行は確認済みです。人の全編視聴・聴取、最終MP4の受入と配信後再生は未確認です。詳細は `docs/RELEASE_VALIDATION.md` を参照してください。YouTubeへのアップロードはユーザーが行います。
