# ADR-002 Firestore永続化

- 状態: 採用
- 日付: 2026-09-21
- 関連: Agent詳細要件定義書 §7（データ要件）、§9.3（冪等性）、§10.2（認証・認可）、§13.3（テスト区分）

## 背景

`services/agent` の保存層は `MemoryStore` だけで、プロセスが落ちるとRun、イベント、
Evidenceがすべて消えていた。設計書 §7 が要求する `agentRuns` / `evidence` / `events`
コレクションは存在せず、§13.3 の Integration（Firestore Emulator）も、検証対象そのものが
無いため着手できなかった。

同時に §9.3 の冪等性も未実装だった。`Idempotency-Key` ヘッダは受け取るものの `AgentRun`
に記録するだけで、同じキーで二度叩けば収集が二重に走った。

## 決定

`Store` プロトコルの下に `MemoryStore` と `FirestoreStore` を置き、`FIRESTORE_ENABLED`
で選択する。既定は `false` で、デモ・単体テスト・評価データセットはインメモリのまま動く。

### コレクション構成

| パス | 内容 | 出典 |
| --- | --- | --- |
| `agentRuns/{runId}` | Run記録 | §7.1 |
| `agentRuns/{runId}/evidence/{evidenceId}` | 最小限の引用 | §7.2 |
| `events/{dedupKey}` | イベント候補 | §7.3 |
| `agentRunKeys/{hash(idempotencyKey)}` | Runの冪等キー索引 | §9.3 |
| `sessions/{hash(sessionId)}` | チャットセッション | — |
| `appState/latestRun` | 最新Runへのポインタ | — |

### 決定1: イベントのドキュメントIDを `eventId` ではなく `dedupKey` にする

§7.3 は `eventId` を "stable-id" と書いているが、同一イベントを再収集したときに書き込み先を
決めるのは §9.3 の `dedupKey` である。`dedupKey` をパスにすると、再収集は同じパスへの
上書きになり、**読んで探してから書く**という競合しやすい手順が不要になる。冪等性が
実装の副作用ではなく構造から出る。

`eventId` での参照（`GET /api/events/{eventId}/evidence` など）は `eventId` 等価クエリで
引く。単一フィールドの等価条件なのでFirestoreの自動インデックスで足り、複合インデックスは
要らない（`firestore.indexes.json` が空なのはこのため）。

### 決定2: 再収集はユーザーの決定を上書きしない

`merge_saved_event()` は、新しく収集した事実（日付、Evidence、信頼度、推薦スコア）を
採用しつつ、次の4つだけ既存の値を残す。

- `eventId` — UIとCalendar登録が指しているID
- `firstSeenAt` — 初回検出時刻。後ろに動いてはならない
- `status` — `bookmarked` / `dismissed`。ユーザーの操作結果
- `googleCalendarEventIds` — 登録済みCalendarエントリ

これを残さないと、毎朝の定期実行がユーザーの保存済みイベントを解除してしまう。

### 決定3: §7 に無いコレクションを2つ足す

`agentRunKeys` は §9.3 の「手動Run: クライアントのIdempotency-Key」を競合なく実現するために
要る。キーから導いたパスにドキュメントを作るのがキーを確保する唯一の方法で、
クエリで探してから作る方式では同時リクエストが二重にRunを起動しうる。トランザクションで
キー確保とRun作成を一度に行う。

`appState/latestRun` は `GET /api/events`（`sourceRunId` 無し）の「最新の結果」に答えるために
要る。順序付きクエリで代替すると複合インデックスが必要になり、得るものが釣り合わない。

### 決定4: `reset()` はEmulatorでしか動かさない

評価ハーネスはケースごとに `store.reset()` を呼ぶ。`FIRESTORE_EMULATOR_HOST` が未設定の
ときは `RuntimeError` にする。設定を誤ったまま評価を回して本番データを消すことを、
コード側で不可能にしておく。

### 決定5: Security Rulesはすべて拒否する

WebはFirestoreへ直接アクセスせず、Cloud Run の `/api` を通す。Cloud Run のサービス
アカウントはAdmin権限でRulesを迂回するため、クライアント経路は全面拒否でよい。
§10.2 の「Rulesだけに依存せず、サーバー側で `userId` 所有権を確認する」は引き続き
サーバー側の責務として残る。

## 結果

- §13.3 の Integration が実施可能になった。`scripts/run-integration-tests.sh` が
  Firestore Emulator を起動し、`tests/test_store_contract.py` の同じ表明を両バックエンドへ
  流し、`tests/test_firestore_workflow.py` が収集ワークフローとAPIをEmulator上で通す。
- `Idempotency-Key` の再送が二重収集を起こさなくなった。
- Emulator が無い環境では Firestore のテストが自動でスキップされるため、`pytest` 単体は
  Javaもネットワークも要らないままになっている。

## 本番での有効化（2026-09-21 実施）

| 手順 | 状態 |
| --- | --- |
| Firestore Native データベースの作成（`(default)` / `asia-northeast1`） | 完了 |
| Cloud Run 環境変数に `FIRESTORE_ENABLED=true` を追加 | 本ADR時点のPRで実施 |
| `firestore.rules` の反映 | `deploy-develop.yml` の `firestore_rules` ジョブで実施 |
| `firestore.indexes.json` の反映 | 不要（空。下記） |

ランタイムサービスアカウント `event-agent-runtime` には `roles/datastore.user` が
既に付いており、追加のIAM作業なしで動く。

### Rules は防御の追加ではなく、意図の固定である

有効化した時点では `firebaserules.googleapis.com` にルールのリリースが1件も存在
しなかったが、クライアント経路は既に塞がっていた。認証なしでのREST読み取りを実測
した結果は `403 PERMISSION_DENIED`（Missing or insufficient permissions）である。
ルール未公開のFirestoreはクライアントアクセスを拒否する。

したがって `firestore.rules` の反映は、塞がっていないものを塞ぐ作業ではなく、
**全拒否という意図をバージョン管理に固定する**作業である。デプロイは
`deploy-develop.yml` の `firestore_rules` ジョブが行う。

### インデックスを反映しない理由

デプロイは `--only firestore:rules` に絞っている。`firestore.indexes.json` は空で、
`list_events` も `get_event` も単一フィールドの等価クエリしか使わない（Firestoreが
自動でインデックスする）。複合インデックスを足す日が来たら、`--only firestore` に
広げたうえでデプロイ用サービスアカウントに `roles/datastore.indexAdmin` が要る。
それまで持たせる理由はない。

## 残件

- ユーザー削除時の関連データ削除（§10.3）は未実装。`userId` によるスコープ分離を先に入れる。
- Run詳細ログの30日保持（§10.3）は、`agentRuns` のTTLポリシーで行う想定。未設定。
- §13.3 の Load は `services/agent/tests/test_load.py` で実施した（ADR-003）。
  Cloud Run Job と Cloud Scheduler のデプロイは Phase 2 のまま残っている。
