# 編集パターン実装計画の要求監査

監査日: 2026-10-06。基準コミット `ff39aa9496ed8180a8c0387f4c092643eb52f218` と、その上の共有作業ツリーを静的に確認した。対象は [実装計画](EDITING_PATTERNS_PLAN_2026.ja.md) の全節。**証明済み**は対応するコードと合成テストが存在する範囲、**弱い**は経路はあるが受入条件の一部が未検証、**未完**は要求された動作が未実装の意味。今回はテスト・レンダー・外部API・FCP GUIを実行していないため、過去のテスト名を合格の再確認とは扱わない。

## 優先して閉じるギャップ

1. **自動提案は音楽だけ（未完、§1・3・4.2・5.3・7・13.2）。** `video_harness/cues.py:130-186` の `plan_cues` は `music == off` なら空で終了し、その後も音楽cueしか生成しない。`clear_explainer` の既定は `music: off, sfx: selected` (`editing_patterns/clear_explainer.json`) なので、章切替の効果音を提案できない。`playful_short` のアクセント、本人写真・図・見出しも自動配置されない。明示cueの検証・描画経路は `production.py:76-104`、`visual.py:229-291` にあるが別の機能。章境界・イベントの根拠を入力とするSFX／画像／title提案器と、疎さ・重複制限・理由の合成テストが必要。
2. **選定順位は文脈を評価しない（未完、§4.2・13.2）。** `assets.py:204-223` は権利ゲート後、宣言済みタグの重複数とIDで並べる。場面、感情、エネルギー推移、歌、音数、長さ、拍、画角、不明属性の推定表示、除外理由の保存はない。`plan_cues` は候補順位すら使わず、適格音楽の最小IDを選ぶ (`cues.py:145-156`)。`tests/test_assets.py:33-43` は単一のタグ一致のみ。自動選定を「適合性の高い素材」と呼ぶ前に、証拠付き属性と棄却理由を比較結果に残す必要がある。
3. **実写の比較・視聴・FCP往復が受入未達（弱い、§7・9・10・13.3）。** 合成fixtureではsilent/multi-source、BGM、画像、XML、portable bundle、再importを検証するテストがある (`tests/test_visual_editing.py`, `test_production_fcp.py`, `test_portable_production.py`, `test_production_import.py`)。ただし `visual.py:290-291` 自体が被写体との重なりを未確認と記す。字幕・顔・実演対象を全区間で確認した視覚証拠、実素材の音量・継ぎ目の試聴、移動先からのFCP GUI import/playback/re-export観察は未確認。P1/P3完成やFCP再現をこれらの合成試験だけで宣言しない。
4. **依頼解釈・好み・trendがレンダーへ自動接続されない（弱い／未完、§1・5.1・9・13.2）。** 六定義の厳格解決とSHA固定は `patterns.py:33-62`、`production.py:16-48` にある。明示的な好みの保存・読出しは単独API (`patterns.py:100-118`) だが、優先順位「今回の指示→作品→保存済み好み→定義→全体既定」を組み立てるSession/CLI経路は見当たらない。`trends.py:45-66` は期限付き版の保管・読出しだけで、対象と目的から自然版／演出版を作る処理ではない。スキルの人手解釈 (`.agents/skills/video-editing/SKILL.md:25-39`) と実装保証を区別する。
5. **比較と採用の意思決定証拠が弱い（弱い、§4.2・5.4・10）。** `Session.compare_candidates` (`session.py:737-765`) は同一plan/briefのみを検査し、原映像・声のゲイン・比較区間の固定、自然版の同席、選定／棄却理由の記録までは保証しない。`adopt_candidate` (`session.py:716-735`) は実actorと理由を保存し、候補のレンダーを要求するが本人選択は確認しない。これは意図的に人のレビューと区別されている (`tests/test_session_candidates.py:14-35`)。比較記録に固定条件・各素材の採否理由・本人選択の根拠を結び付ける必要がある。

## 節別の確認

| 計画の節 | 状態と根拠 | 次の判定条件 |
|---|---|---|
| §1・3 方針と六パターン | **証明済み（一部）**: `editing_patterns/*.json`、`patterns.py:33-70` は自然既定・個別off・定義SHA・natural reset。`tests/test_patterns.py:9-45` が境界を扱う。 | 上記のSFX／視覚自動提案と、媒体名だけで強演出を選ばない依頼解釈。 |
| §2 一次資料の解釈 | **未再検証**: この監査は計画に記載された外部資料を再閲覧していない。`trend_profiles` は日付・対象を保持する。 | 公開時に引用元の範囲と日付を別途確認し、効果保証に転用しない。 |
| §4 素材と権利 | **証明済み（一部）**: `assets.py:112-202` はSHA、権利・媒体・費用・受渡し用途を検証。`asset_providers.py:85-151` はPexels検索・取得を分離し、取得後も権利不明。`tests/test_assets.py`, `test_asset_providers.py` は合成テスト。 | 素材別の実許諾・404等、順位と棄却理由、実APIは別証拠。 |
| §5 設定・cue・候補 | **証明済み（一部）**: schema・freeze、mapping SHA付きcue (`production.py:76-90`)、不変候補・採用 (`session.py:673-735`) がある。`tests/test_production.py`, `test_session_candidates.py`。 | preference優先順位、候補ごとの比較条件・採否記録。 |
| §6 音・拍 | **弱い**: `audio_mix.py`, `beats.py`, `beat_editing.py` と `tests/test_audio_mix.py`, `test_beats.py`, `test_beat_editing.py`, `test_session_beats.py` に合成fixtureの時刻・duck・境界試験がある。 | 実音源でLUFS/true peak、ポンピング、楽句・loop・音声の明瞭さを試聴。 |
| §7 FCP／補助素材 | **弱い**: 明示cue描画、三handoff mode、権利別package、戻りXMLの厳格検査がある (`visual.py`, `production_fcp.py`, `production_import.py`, `delivery_production.py`)。 | 被写体・字幕の全区間確認とFCP GUI往復。editableのduck・grade・overlay再現は手動事項として残す。 |
| §8 スキル・接続 | **弱い**: 3スキルは共通契約を参照 (`.agents/skills/video-editing/SKILL.md:25-39`, youtube/tiktok)。Session/CLIの操作は存在する。 | 依頼文からの自動解決・個人好み・trend適用はスキル判断に依存。 |
| §9・10 受入・検証 | **未完**: 合成試験はP0–P4の部分契約を覆うが、計画が要求する人の実写レビュー・FCP GUI・実API・クリーン配布の証拠ではない。 | 対象ごとの試験結果SHA、実地観察者、対象render SHAを台帳へ。 |
| §11 範囲外 | **証明済み（方針）**: 自動作曲・投稿等を受入条件に含めない。 | 範囲外を完成宣言へ混ぜない。 |
| §12・13 操作と順序 | **弱い**: production CLI、Session候補・beat提案・visual plan・XML import は存在する。`tests/test_session_production_import.py` は返却XMLの保全と未採用を模擬で確認。 | 上記ギャップを閉じてからREADME／スキルの提供範囲を確定。 |

判定の境界: この文書は共有作業ツリーの読取監査であり、未コミット変更のリリース受入、外部サイト条件の最新性、FCP GUI互換性を証明しない。
