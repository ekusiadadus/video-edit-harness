# 演出パターン・BGM・音ハメの操作

対象: この作業ツリーの未リリース実装。公開alpha.5には含まれない。GUIや試聴の未確認事項は[進捗台帳](EDITING_PATTERNS_IMPLEMENTATION_STATUS.ja.md)を参照。

`natural`を既定とし、`gentle_vlog`、`clear_explainer`、`cinematic_story`、`beat_montage`、`playful_short`を作品ごとに指定する。媒体名だけで強い演出を選ばない。`style`は色、`use_case`は撮影状況、`editing_pattern`は演出を表す。

## ローカル素材の登録と比較

作品フォルダの`assets/`へ実際の音源・写真・補助映像と利用条件の根拠を置く。元ファイルを保持する。無料という価格条件と、掲載先・商用利用・改変・帰属・分離音声／元素材の受渡し条件を別々に記録する。

```sh
uv run video-harness doctor
uv run video-harness production --help
uv run video-harness production register assets/music.wav --metadata assets/music-metadata.json --output assets/music-record.json
uv run video-harness production validate assets/music-record.json --policy asset-policy.json
uv run video-harness session candidate harness/session --changes-file direction.json --actor codex --note '依頼された控えめBGMを比較'
uv run video-harness session render harness/session --candidate-id CANDIDATE_ID
uv run video-harness session compare-candidates harness/session NATURAL_RENDER_ID MUSIC_RENDER_ID
```

`direction.json`には`editing_pattern`、`asset_policy`、登録したrecordを含む`assets`を指定する。`assets`の更新は配列全体を置き換えるため、visual原素材など既存の必要recordも残す。例として控えめ版は`{"editing_pattern":{"id":"gentle_vlog","music":"intro_outro","sfx":"off","beat_sync":"off"}}`。これは既に登録済み素材がプロジェクトへ保存されている場合の変更例。

比較後は`session adopt-candidate SESSION CANDIDATE_ID --actor ACTOR --note REASON`で明示的に選択し、`session render SESSION --full`で全編を作る。候補選択は人のレビューを意味しない。正確な全編SHAへ視聴・試聴・権利確認を記録して納品する。自然版への戻しにも同じ候補選択を使う。

## 拍の解析とカット提案

```sh
uv run video-harness production beats assets/music.wav --manual-beats-file reviewed-beats.json --output music-beats.json
uv run video-harness session propose-beats harness/session CURRENT_RENDER_ID --spec-file beat-spec.json --actor codex --note '確認した無発話区間だけ音ハメを提案'
```

`reviewed-beats.json`は実際に確認した元音源の秒数配列。代わりに`--bpm NUMBER`を指定できる。`--librosa`は`uv sync --locked --extra beat-analysis`で任意依存を準備した場合だけ利用する。ASRやクラウド送信は行わない。

`beat-spec.json`の項目:

- `asset_id`: 現行レンダーで使用したmusic recordのID。
- `beat_map`: `music-beats.json`のオブジェクト全体。元音源SHAが一致する必要がある。
- `allowed_intervals`: 実際に確認し、カット移動を許可した無発話の出力秒数区間。
- `protected_intervals`: 移動や横断を禁止する出力秒数区間。
- `max_shift`、`min_hold`: 最大移動秒数と最短保持秒数。分数文字列も使用可能。

visual v4計画はレビュー待ちの新計画になる。`session approve`後に再レンダーし、配置・対応表を再生成する。古い明示cue planは新しい出力時刻へ流用しない。発話のv2/v3計画は拍マークの記録だけで、単語や呼吸の時刻を動かさない。beat syncがオフ、音源SHAが違う、古いレンダー、未許可区間の場合はカット提案を通さない。

## FCPから戻したproduction XML

```sh
uv run video-harness session import-production-fcp harness/session CURRENT_FULL_RENDER_ID returned.fcpxml --actor codex --note 'FCPで調整した配置を比較候補へ'
```

editableモードの対応する配置・ゲイン・フェード変更は、未採用のcandidate changesファイルとして返す。表示されたファイルを`session candidate --changes-file`へ渡し、レンダー・比較・明示選択・全編レビューを行う。mixモードは完成ミックスの比較記録であり、原ショットや分離cueへ逆変換しない。未知の効果や原ショット変更は理由付きで拒否し、返却XMLとレポートを残す。

FCP納品は許諾された依存だけを同梱し、XMLから同梱`media/`を相対参照する。finished-pictureには色が焼き込まれているため、変換LUTを再適用しない。XMLの構文合格は実FCPでの読込・同期・再生・再exportの証拠にはならない。

## 外部画像・動画の検索と取得

Pexelsは画像・動画用で、BGM検索を提供するアダプターではない。音源サービスは公式画面で取得した素材をローカル登録する。API鍵は環境変数`PEXELS_API_KEY`だけに置く。プロジェクト、レシート、ログへ書かない。

```sh
uv run video-harness production search 'mountain landscape' --kind video --policy asset-policy.json --output candidates.json
uv run video-harness production fetch chosen-candidate.json --policy asset-policy.json --folder assets/downloads --output download-receipt.json
```

ポリシーには実際の掲載先と、検索の`search_network: on`、取得の`download_network: on`をそれぞれ明示する。検索語は公開してよい一般語だけにする。`chosen-candidate.json`は検索結果配列から選んだ一件。取得後も権利は未確認であり、個別の使用条件を確認して`register`する。失敗時はローカル素材を利用できる。

検索結果・クレジット・レシートは作者とPexelsのリンクを保持する。APIの動画検索は現在の`/v1/videos/search`を使用する。[Pexels公式API文書](https://www.pexels.com/api/documentation/)。認証情報の別ホストへの転送を避けるため、自動redirectは行わない。

傾向は`production trend ID`で確認し、出典・対象・期限を持つ新しい調査版だけを`production import-trend PROFILE --root ROOT`で登録する。既存作品の音源やパターンを最新情報で自動差し替えしない。

### Content ID未確認の素材でローカル試作する

無料素材の利用許諾と、YouTubeで実際にclaimが出るかは別の確認である。`content_id`を推測で`none`にしてはならない。ライセンス自体は確認済みで、Content IDだけが未確認の場合は、`asset_policy.content_id_check: "pending_local_review"`を明示してローカルの埋込MP4を試作できる。未確認状態は記録に残る。既定は`required`であり、元素材・完成音声の別配布にはこの例外を使えない。未確認モードのproductionは`session package`などの配布bundleで拒否する。試作品の視聴は公開承認ではない。

実映像の前後比較は同じsource frame coverageを使い、尺、ショット数、拍への丸め誤差を報告する。画質や魅力の改善率を捏造しない。ダンスの動作自体を曲に合わせてretimeしていない場合、音ハメはカット・エフェクトの同期であると説明する。比較MP4には音声を埋め込み、BGMの原MP3やmusic-only書き出しは公開しない。
