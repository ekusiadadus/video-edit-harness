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

[Symphony Creative Studioの編集機能](https://ads.tiktok.com/resources/help/article/how-to-edit-videos-with-symphony-creative-studio)には音楽と区間エフェクトがある。Studioで使える機能を、そのまま公開APIの機能として推測しない。[Symphony APIの公式入口](https://ads.tiktok.com/creative/creativeCenter/tools/api?aioChannel=creative_center)と[Business APIのVideo Soundtrack仕様](https://www.postman.com/tiktok/tiktok-api-for-business/request/hvcbkdi/video-soundtrack)は別の接続経路として、アカウントの利用権限・仕様・素材と音楽の用途を確認する。現在のクライアントにはこれらの処理を実装・接続していない。

現在の実環境は`status`で未構成・未接続、リモート検証未実施。開発者サイトのログイン／Sandboxテストユーザー登録は済んでいても、ローカルの認証設定と本人API応答は別の証拠。Businessログイン待ちのStudioからは素材転送・曲／効果適用を実施していない。ローカルで描画した音ハメ・残像・ズームを「TikTokネイティブ」と表示しない。ユーザーが完成MP4を自分で投稿する現在の方針も維持する。

## 公式資料

- [Desktop Login Kit：redirect、state、PKCE](https://developers.tiktok.com/docs/en/login-kit-desktop)
- [User Access Token Management：交換・更新](https://developers.tiktok.com/docs/en/oauth-user-access-token-management)
- [Display API概要とscope](https://developers.tiktok.com/docs/en/display-api-overview)
- [Get User Info](https://developers.tiktok.com/docs/en/tiktok-api-v2-get-user-info)
- [List Videos](https://developers.tiktok.com/docs/en/tiktok-api-v2-video-list)
- [Video Objectのフィールド](https://developers.tiktok.com/doc/tiktok-api-v2-video-object)
