# ADR-005 PWA化とキャッシュ方針

- 状態: 採用
- 日付: 2026-09-22
- 関連: 画面設計書 §1.4（レイアウト方針）、§6.3（日時の扱い）、Agent詳細要件定義書 §8.3（一覧API）

## 背景

締切を見逃さないためのアプリなので、スマホのホーム画面から1タップで開けることに
価値がある。Firebase Hosting の SPA は manifest と Service Worker を足せば
インストール可能になるが、Service Worker のキャッシュは**古い一覧を新しいものとして
見せてしまう**危険がある。申込締切が過ぎたイベントを「あと2日」と表示するのは、
このプロダクトにとって最悪の故障である。

## 決定

### 決定1: `/api/` は Service Worker で一切キャッシュしない

一覧・詳細・根拠・Run・チャットのすべてがこの経路を通る。オフラインや
ネットワーク失敗のときは、最後に取得した一覧を出すのではなく、画面側の
「取得できませんでした」の状態に落とす。古い情報を出すよりも、出せないと
伝えるほうが安全である。

### 決定2: アプリシェルだけをキャッシュし、`index.html` はネットワーク優先

| 経路 | 戦略 | 理由 |
| --- | --- | --- |
| ナビゲーション（`index.html`） | ネットワーク優先、失敗時のみキャッシュ | オンラインなら常に最新のビルドを読む。更新通知バナーを作らずに済む |
| `/assets/*`（ハッシュ付き） | キャッシュ優先 | 中身が変われば名前も変わる。Hosting の `immutable` と同じ前提 |
| それ以外の同一オリジン GET | ネットワーク優先 | manifest やアイコン。頻繁には変わらない |
| 他オリジン（Web フォント等） | 触らない | ブラウザの HTTP キャッシュに任せる。オフライン時は代替フォントで描画する |

キャッシュ名に版（`shell-v1`）を持ち、activate 時に他の版を消す。

### 決定3: 依存を増やさず、Service Worker は手書きする

`vite-plugin-pwa`（Workbox）は precache と更新通知を自動化するが、この規模では
上の3経路の分岐で足りる。依存を増やすとロックファイルの差分が増え、`develop` への
マージ＝デプロイという運用で戻しにくくなる。`apps/web/public/sw.js` は 70 行程度で、
挙動が読めることを優先した。

### 決定4: 開発サーバでは登録しない

`import.meta.env.PROD` のときだけ `navigator.serviceWorker.register('/sw.js')` を呼ぶ。
開発サーバで登録すると、キャッシュした `index.html` が HMR と食い違う。

## 検証

`vite preview` で本番ビルドを配信し、Playwright で確認した。

- 初回ロードで `shell-v1` に `/index.html` が入る。2回目のロードで `/assets/*.js` `/assets/*.css` が乗る
- キャッシュに `/api/` の項目は入らない
- オフラインにして `/calendar` へ遷移しても画面が描画される（一覧は取得失敗の状態）

## 結果

- `apps/web/public/`: `manifest.webmanifest`、`sw.js`、アイコン（192 / 512 / maskable 512 / apple-touch 180）
- `apps/web/index.html`: manifest とホーム画面用の meta
- `apps/web/src/main.tsx`: 本番ビルドでのみ登録
- `firebase.json`: `/sw.js` と `/manifest.webmanifest` を `no-cache` にし、更新が即座に届くようにする

## 限界

- iOS は manifest のアイコンを使わないため `apple-touch-icon.png` を別に置いている。iOS の PWA はプッシュ通知に制約があり、Phase 2 の「毎朝7時の自動更新」通知には別途検討がいる
- Web フォントはオフラインで読めない。代替フォントで崩れない程度に `styles.css` の font-family に fallback を並べている
- 古い `/assets/*` はキャッシュ名の版を上げるまで残る。容量が問題になる規模ではない
