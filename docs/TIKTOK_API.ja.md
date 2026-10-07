# TikTok公式APIとの読み取り専用接続

確認日: 2026-10-06。現行作業ツリーの `video-harness tiktok-api` は、TikTok Login Kit（Desktop OAuth）とDisplay APIの最小接続を対象にする。**模擬HTTPテストの成功は実アカウント接続ではない。** TikTok投稿・動画アップロード、他人の動画検索、流行ランキング、商用音源ライブラリ（CML）の取得や音源利用許諾は、この接続では行わない。

## 接続に必要なもの

TikTok for Developersでアプリを用意し、Login KitとDisplay APIを設定する。Client key、Client secret、登録済みのDesktop用redirect URI（`localhost`／`127.0.0.1`、固定パスとポート）、`user.info.basic` と `video.list` の利用承認、対象ユーザーのOAuth同意が必要。追加scopeはアプリ側の事前承認が必要な場合がある。`configure` は3項目を非表示入力からmacOS Keychainへ保存する。環境変数 `TIKTOK_CLIENT_KEY`、`TIKTOK_CLIENT_SECRET`、`TIKTOK_REDIRECT_URI` からの読込も可能だが、値を表示しない。認証情報をproject JSON、ログ、リポジトリへ保存しない。

```sh
uv run video-harness tiktok-api configure
uv run video-harness tiktok-api status
uv run video-harness tiktok-api connect --network
uv run video-harness tiktok-api auth-url --scopes user.info.basic
uv run video-harness tiktok-api exchange --network
uv run video-harness tiktok-api profile --network
uv run video-harness tiktok-api videos --network --max-count 10
uv run video-harness tiktok-api refresh --network
```

`connect --network` は登録済みの `127.0.0.1` callbackポートだけを開き、認可URLをすぐ表示する。本人がURLをブラウザで開いて同意すると、同じプロセスがcallbackを受け、stateとpathを照合してtokenを交換する。待機は最大10分。callbackのcodeやURLはログに残さない。登録済みredirectが `localhost` の場合などは、`auth-url` と `exchange --network` を分け、返却されたcallback URLを後者の**非表示入力**へ貼る。URLやcodeをCLI引数・シェル履歴へ書かない。`auth-url` のscope既定は `user.info.basic,video.list` で、承認されている一方だけを指定することもできる。

`auth-url` はローカルで暗号学的にランダムなstateと毎回新しいPKCE verifierを作り、verifierとstateをmacOS Keychainへ保管する。callbackのscheme/host/path、state、10分の期限を照合してからtoken交換する。TikTok DesktopのPKCE challengeはverifierのSHA-256を**16進文字列**で送る。token交換・refreshの応答からaccess/refresh tokenをKeychainへ保管し、CLI出力には含めない。`status` はネットワークを呼ばず、環境変数の設定有無、Keychain設定の有無、接続状態・scope・有効期限のみを返す。今回の模擬テストは隔離したKeychain値とローカルcallbackを確認したが、OAuth同意と実API応答は別途確認が必要。

開発版の`status`／`doctor`は、保存の有無と実行可能性を分けます。既存の`connected`は「認可情報が保存済み」の互換フィールドです。現在の状態は`authorization_state`（未設定、認可待ち、有効、更新必要、認可期限切れ）、`access_token_valid`／`refresh_token_valid`、scope別の`readiness.profile`／`readiness.videos`、次の操作を示す`next_action`で確認してください。有効期限とscopeが揃っていても、失効・アプリ審査・サーバー側の利用可否はローカルでは証明できません。`remote_verification: not_performed`を返し、実際の`profile --network`／`videos --network`の成功と区別します。破損した保存情報は固定エラーで拒否し、秘密値を出力しません。この診断追加は公開alpha.7後の開発機能です。

`profile` は認可された本人の `open_id`・表示名・アバターURLを取得する。`videos` は本人が公開した動画のメタデータを最大20件ずつ読み、cursorで続きを指定できる。`video.list` は**読み取り用scope**であり、投稿権限ではない。OAuthの `refresh` もメディアを送らない。これらのネットワーク呼び出しは明示的な `--network` が必要で、HTTPSの公式host、固定endpoint、redirect禁止、10秒timeout、1MiB応答上限を使う。トークンやserverの生エラーをCLIへ出さない。

投稿を希望する場合でも、Content Posting APIの別製品・scope・審査・利用者操作・対象動画の権利確認が必要。このクライアントには投稿処理を含めない。TikTok側のCMLや「最新の流行」をDisplay APIの動画一覧から推定して、作品への利用権や編集効果として自動採用しない。

## ネイティブ音楽・エフェクトの現在の境界（2026-10-07確認）

「TikTokと接続したらTikTokの曲やエフェクトをMP4へ付けられる」とは扱わない。[Direct Postの現行スキーマ](https://developers.tiktok.com/docs/en/content-posting-api-reference-direct-post)には投稿設定と完成素材の転送はあるが、動画への曲やエフェクトの指定はない。Display API接続を完了しても、この編集機能は増えない。

現在の`session native-finish`は参照URLと時間指定を封印する**指示書の作成**までで、Studioの操作・音楽合成・エフェクト描画・MP4取得は実行しない。指示書を作れたことを適用成功と表示しない。編集APIを追加する際は、Display APIとは別のBusiness／Symphony認証と実仕様、処理ジョブの完了、取得MP4のSHA・映像・音声を確認する必要がある。

[Symphony Creative Studioの編集機能](https://ads.tiktok.com/resources/help/article/how-to-edit-videos-with-symphony-creative-studio)には音楽と区間エフェクトがある。Studioで使える機能を、そのまま公開APIの機能として推測しない。[Symphony APIの公式入口](https://ads.tiktok.com/creative/creativeCenter/tools/api?aioChannel=creative_center)と[Business APIのVideo Soundtrack仕様](https://www.postman.com/tiktok/tiktok-api-for-business/request/hvcbkdi/video-soundtrack)は別の接続経路として、アカウントの利用権限・仕様・素材と音楽の用途を確認する。現在のクライアントにはこれらの処理を実装・接続していない。

2026-10-07の実環境では`doctor`が未構成・未接続、リモート検証未実施を報告した。開発者サイトのログイン／Sandboxテストユーザー登録は済んでいても、ローカルの認証設定と本人API応答は別の証拠。

SymphonyのBusinessログイン待ちは解消し、実編集画面でStockの21.9秒ダンス素材へNightclubカテゴリの区間エフェクトを追加した。タイムラインの効果レイヤーと横方向ブラーを確認し、Downloadから実MP4を保存した。1080×1920、30fps、657フレーム、21.9秒、全AVデコード成功。音声トラックはあるが測定値は−91 dBで実質無音。K-pop音楽カタログの検索・選択はできたが、音楽レイヤー追加は未確認で、選択曲は完成MP4へ入っていない。これは**Studio UIの機能確認**であり、APIによる編集でも、音ハメの完成デモでもない。素材／曲のYouTube用途への権利確認、人の全編視聴・試聴も未実施。

ローカル証跡は`output/implementation-maya/tiktok-native-live-20261007/`の`observations.json`、`doctor.json`、`probe.json`、`decode.log`、`audio-level.log`、`native-export.jpg`と`native-effect-demo.mp4`。動画SHA-256は`73567571e63d2bba409b1bc6019859dc8e4a6b157f214960e87bb7cb6af40ad3`。個人のローカル素材は送信していない。ローカルで描画した音ハメ・残像・ズームを「TikTokネイティブ」と表示しない。完成MP4の投稿はユーザー自身が行う。

## 外部仕上げのMP4を戻す（開発版）

まず、取得したMP4だけを調べる場合:

```sh
uv run --no-sync video-harness native-inspect returned.mp4 \
  --require-music --output output/native-inspection
```

`--require-music`は音楽入りの依頼を検査するときに指定する。全編の映像・音声デコードと最初の音声トラックのピーク測定を保存する。音声トラックなし、またはピークが−90 dB以下なら`requested_music_not_demonstrated`となる。音が存在しても、それが選択した曲か、音ハメが合うか、人が聞きやすいかは未確認。自然な無音版には指定しない。診断コマンドの正常終了は作品の採用や音楽利用許諾を意味しない。MP4として読み、ネットワークプレイリストとしての読み込みを拒否する。

Sessionの提案から戻す場合は、`native-finish`が返した提案IDと、実際のベース／返却動画SHAを使う。旧提案はartifactのSHAをIDの代わりに指定できる。

```sh
uv run --no-sync video-harness session native-result SESSION PROPOSAL_ID \
  --video-file returned.mp4 --receipt-file native-receipt.json \
  --actor codex --note '実際の外部仕上げを保持してレビュー待ちにする'
```

`native-receipt.json`の形（SHAとURLは実データへ置換）:

```json
{
  "base_video_sha256": "提案のbase_video.sha256",
  "result_video_sha256": "取得MP4のSHA-256",
  "method": "studio_ui",
  "reference_url": "https://ads.tiktok.com/creative/creativestudio/edit?tempId=実際の下書きID",
  "reported_music_applied": true,
  "reported_effect_ids": ["提案にあるエフェクトID"],
  "note": "実際に見た選択曲・区間・書き出し操作を記録する"
}
```

`method`は`studio_ui`／`business_api`／`symphony_api`。これは実行者の申告でありAPI疎通の証明ではない。参照URLへOAuth code・token等を入れない。効果IDは元の提案にあるものだけを指定する。音楽未適用なら`false`とし、適用していない効果を列挙しない。

返却MP4をSessionへコピーし、提案・申告・検査・生ログをSHAで保持する。`session status --deep`／`resume`はこれらの改変も検出する。ベースとの長さの差を示すが、**元の時間対応・字幕・拍・追跡・レビューを継承しない**。採用中のproject、plan、renders、reviewsは変えない。実際に元動画を使ったか、曲・効果の実適用、権利、正確な返却SHAへの全編視聴・試聴を別途確認する。この取り込みは外部サービス操作の自動化ではなく、公開alpha.7にも含まない。

## 公式資料

- [Desktop Login Kit：redirect、state、PKCE](https://developers.tiktok.com/docs/en/login-kit-desktop)
- [User Access Token Management：交換・更新](https://developers.tiktok.com/docs/en/oauth-user-access-token-management)
- [Display API概要とscope](https://developers.tiktok.com/docs/en/display-api-overview)
- [Get User Info](https://developers.tiktok.com/docs/en/tiktok-api-v2-get-user-info)
- [List Videos](https://developers.tiktok.com/docs/en/tiktok-api-v2-video-list)
- [Video Objectのフィールド](https://developers.tiktok.com/doc/tiktok-api-v2-video-object)
