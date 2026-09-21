# ADR-003 定期Runのロックと負荷試験

- 状態: 採用
- 日付: 2026-09-21
- 関連: Agent詳細要件定義書 §9.2（上限）、§9.3（冪等性）、§11.1（性能）、§13.3（テスト区分）、§14 Phase 2
- 前提: [ADR-002 Firestore永続化](./ADR-002-Firestore永続化.md)

## 背景

§13.3 の Load は「同時手動Runと定期Job重複時のロック・クォータ動作」を見よ、と書いている。
これが保留のままだったのは、測定対象が3つとも存在しなかったからである。定期Runの入口が
無く、§9.3 が定めるその冪等キー（`userId + JST日付 + scheduleVersion`）も未実装で、
Cloud Run Job も Cloud Scheduler も Phase 2 のまま作られていない。

ロック対象を作らずに負荷試験だけ書いても、通ることに意味が無い。

## 決定

Cloud Run Job と Cloud Scheduler のデプロイは Phase 2 に残したまま、**ロックとクォータの
実体をアプリケーション側に実装し、そこに負荷試験を当てる**。デプロイされていない
インフラに依存せず、§13.3 が本当に見たい「重複時の挙動」を検証できる。

### 決定1: 定期Runのキーは JST の日付から導出する

```
sha256(f"{userId}|{JSTの日付}|{scheduleVersion}")
```

UTC ではなく JST を使う。スケジュールは「毎朝7時（JST）」であり（画面設計書§8-4）、
07:00 JST は UTC では前日である。UTC 日付でキーを作ると、狙った実行時刻がちょうど
日付の境界をまたぎ、1回の日本の朝に2つのキーが生まれる。

キーが決定論的なので、Jobの再実行、スケジュールの二重発火、手動トリガの重複が
すべて同じドキュメントに着地し、最初の1つだけが収集する。ロックのための追加機構は
要らない。ADR-002 の `agentRunKeys` をそのまま使う。

`run_daily_collection()` は `(run, started)` を返す。呼び出し側は `started` を見て、
自分が担当なのか既に別の実行が持っているのかを判断する。

### 決定2: Gemini呼び出し予算を ContextVar に移す

§9.2 は「Gemini呼び出し: 1 Run最大15回」と定める。実装は `GeminiClient` の
インスタンス変数で数えており、各Runの冒頭で `reset_call_budget()` していた。
`GeminiClient` はモジュールシングルトンなので、**Runが同時に走るとこの上限は
1 Runあたりではなくなる**。後から始まったRunのリセットが、先行Runの消費済み回数を
0に戻すためである。2本が重なれば合計30回まで呼べてしまい、§11.2 のコスト上限の
前提も崩れる。

予算を `ContextVar` に移した。`asyncio.create_task` はコンテキストをコピーするので、
Runごとに独立した残数を持つ。これは負荷試験を書こうとして見つけた欠陥であり、
§13.3 が Load を要求している理由そのものでもある。

### 決定3: 負荷試験は両バックエンドで回す

`tests/test_load.py` は `store_backend` フィクスチャで MemoryStore と FirestoreStore の
両方に対して走る。ロックの実体が前者ではミューテックス、後者ではトランザクションで
まったく別物であり、本番で使うのは後者だからである。Emulator が無い環境では
Firestore 側だけ自動でスキップする。

検証する4点。

| 観点 | 表明 |
| --- | --- |
| §9.3 定期Run | 8本同時に発火しても収集は1回、全員に同じ `runId` が返る |
| §9.3 手動Run | 同じ `Idempotency-Key` の同時POST 8本で `runId` は1つ |
| §9.2 クォータ | 同時実行下でも各Runの `queryCount` ≤ 8、`candidateCount` ≤ 30、呼び出し予算がRun間で漏れない |
| §11.1 受付性能 | 同時POST 8本の受付 p95 < 2秒 |

### 決定4: Job入口は置くが、デプロイはしない

`entrypoints/job.py` を置く。`run_daily_collection()` の呼び出し元が無いと、ロックは
テストからしか使われない機能になる。FastAPIサービスはリクエストを捌くものであって
バッチではないため、入口を分ける（§11.3 保守性、ドメインロジックをCloud Run入口から
独立させる方針）。

Cloud Run Job の作成、Cloud Scheduler の登録、デプロイワークフローへの追加はしない。
本番は `develop` へのマージで即座に反映されるため、動かす判断は別に行う。

## 結果

- §13.3 の Load が実施済みになった。区分で未着手なのは Cloud Run Job / Cloud Scheduler の
  デプロイを伴う部分だけになった。
- §9.2 の「1 Run最大15回」が、同時実行下で実際に1 Runあたりの上限として働くようになった。
- 定期実行を Phase 2 で動かすとき、二重収集の防止は既に済んでいる状態から始められる。

## デプロイ状況（2026-09-21 更新）

| 対象 | 状態 |
| --- | --- |
| Cloud Run Job `event-agent-daily` | `deploy-develop.yml` からデプロイする |
| Cloud Scheduler | **未作成**（下記） |

Job は同じコンテナイメージを `python -m event_agent.entrypoints.job` で起動する。
`--task-timeout 300s` を付けたので、§9.2 の「Run全体300秒で強制終了」はJob経路に限り
インフラ側で満たされる。アプリ内のタイムアウトは引き続き未実装である。

`--max-retries 0` は意図的な選択である。§9.3 のロックは二重収集を防ぐが、キーを
claim した実行が途中で落ちた場合の再開はしない。自動リトライを入れると、再試行は
「今日は既に担当済み」と判断して収集せずに成功終了し、Runが `running` のまま残る。
失敗は成功に見えないほうがよい。

### Cloud Scheduler を作るには

デプロイ用サービスアカウントに `roles/cloudscheduler.admin` が無く、Scheduler が
Job を起動するための `roles/run.invoker` も付与できていないため、未作成である。
`scripts/bootstrap-gcp.sh` には前者を追加済み。既存プロジェクトでは次を実行する。

```bash
PROJECT=osaka-hackathon-260919
REGION=asia-northeast1
SA="event-agent-scheduler@${PROJECT}.iam.gserviceaccount.com"

gcloud iam service-accounts create event-agent-scheduler \
  --display-name="Cloud Scheduler invoker" --project="$PROJECT"

gcloud run jobs add-iam-policy-binding event-agent-daily \
  --member="serviceAccount:${SA}" --role="roles/run.invoker" \
  --region="$REGION" --project="$PROJECT"

# 毎朝7時 JST（画面設計書§8-4）
gcloud scheduler jobs create http event-agent-daily-0700 \
  --location="$REGION" --project="$PROJECT" \
  --schedule="0 7 * * *" --time-zone="Asia/Tokyo" \
  --uri="https://${REGION}-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/${PROJECT}/jobs/event-agent-daily:run" \
  --http-method=POST \
  --oauth-service-account-email="$SA"
```

動作確認は手動実行でできる。

```bash
gcloud run jobs execute event-agent-daily --region=asia-northeast1 --wait
```

## 残件

- Cloud Scheduler の作成（上記コマンド。IAM付与が前提）。
- 対象ユーザーの列挙。現在の `job.py` は引数のユーザー1件だけを処理する。
  複数ユーザーへ広げるときは §11.2 の1日あたり費用上限を先に決める必要がある。
- claim 後に落ちた実行の再開。現状は `RUN_SCHEDULE_VERSION` を上げるか翌日を待つしかない。
- §9.2 の「Run全体300秒で強制終了」のアプリ内実装。Job経路は `--task-timeout` で
  代替しているが、手動Runには効かない。
