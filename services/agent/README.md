# Event Agent Service

FastAPI + ADK-style deterministic workflow for event discovery. Uses Vertex AI Gemini when `GCP_PROJECT_ID` is set; otherwise serves curated demo events for local UI development.

## API

- `GET /api/health`
- `POST /api/chat` — `{ "sessionId?", "message" }` → `{ sessionId, reply, actions? }`
- `POST /api/agent-runs` — `{ "forceRefresh?", "sessionId?" }` → `{ runId, status }`。`sessionId` を渡すとそのチャットの関心条件で探す。`MANUAL_RUNS_ENABLED=false` のときは 403
- `GET /api/agent-runs/{runId}` の `activity[]` — 各役割（planner / searcher / extractor / organizer）の行動。UI の「エージェントの動き」用
- `GET /api/agent-runs/{runId}`
- `GET /api/events?sourceRunId=&sessionId=` — `sourceRunId` があればその Run、無ければ共有プール（ADR-008）を `sessionId` の関心で採点した順。`lastCollectedAt` を添える
- `POST /api/pool-search` — `{ "sessionId?", "query" }` → 解釈・絞り込み・採点・提示の `activity[]` と採点済み `events[]`（ADR-010、Gemini 2 回、Web には出ない）。「ビジコン」のような種別の語があれば `intent.kinds` で絞り、「締切が近い順」「実施が近い順」で `intent.order` を切り替える
- `GET /api/events/{eventId}/route?from=<出発駅名>&to=<到着駅名>` — 駅すぱあと API でイベント開始時刻に到着する経路を 1 件返す（`EKISPERT_API_KEY` 必須。未設定時は 503）。`to` 省略時はイベントの最寄駅。最寄駅が未確認なら 400（会場名を駅名として送らない）
- `POST /api/organizer-posts/preview` — 主催者投稿の下書き → `{ event|null, linkedEvent|null, issues[] }`。何も保存しない（F-06）
- `POST /api/organizer-posts` — 投稿を保存 → `201 { post, warnings[] }`。命令様の本文・非公開URLは `400`
- `GET /api/organizer-posts` — フィード。公開中で開催前の投稿を固定 → 優先 → 新しい順で返す
- `GET /api/go/{eventId}/{official|application|contact}` — 計測付きリダイレクト（302、utm を付与、ADR-009）
- `POST /api/events/{eventId}/metrics` — `{ "kind": "calendar" }` を数える（204）
- `GET /api/organizer-posts/{postId}/metrics` — 投稿の成果（自イベントと結び付いた AI 収集イベント）

## Event kinds

`Event.kind` は機会の種別（`hackathon` / `contest` / `accelerator` / `cocreation` /
`exhibition` / `subsidy`）で、抽出のラベル表と一覧の絞り込みを切り替える
（`docs/ジャンル拡張計画.md`）。ハッカソンは実施日が必須のままだが、ビジコンなど
実施日が書かれない告知は締切だけで載せる（`dates.eventStart` は null）。
締切と実施日のあいだの節目は `dates.milestones` に持ち、ジャンル固有の値
（賞金・支援内容・対象ステージなど）は `attributes` にページの行のまま持つ。

## Admin commands

主催者確認・PR 枠・非表示は認証が無い間、管理者が手で行う（ADR-009）:

```bash
FIRESTORE_ENABLED=true GCP_PROJECT_ID=osaka-hackathon-260919 PYTHONPATH=src \
  python -m event_agent.entrypoints.admin confirm <postId>
# pin <postId> --until 2026-10-15 / unpin / hide / show / metrics
```

## Local run (WSL)

```bash
cd services/agent
pip install -r requirements.txt
cp .env.example .env
export PYTHONPATH=src
uvicorn event_agent.entrypoints.service:app --reload --host 0.0.0.0 --port 8080
```

## Persistence

`storage/store.py` holds two interchangeable backends behind one `Store` protocol.

| `FIRESTORE_ENABLED` | Backend | Used by |
| --- | --- | --- |
| `false`（既定） | `MemoryStore` | デモ、単体テスト、評価データセット |
| `true` | `FirestoreStore` | Cloud Run。§7 のコレクションへ書く |

Both honour §9.3: a repeated `Idempotency-Key` returns the first run instead of
starting a second, and re-collecting an event writes to the same `dedupKey`
document, keeping its `eventId`, `firstSeenAt` and the user's own
`status` / `googleCalendarEventIds`. See
[ADR-002](../../docs/ADR-002-Firestore永続化.md).

## Tests

```bash
export PYTHONPATH=src
pytest tests/ -q
```

Firestore tests skip themselves unless `FIRESTORE_EMULATOR_HOST` is set. To run
them, use the emulator (needs Java):

```bash
./scripts/run-integration-tests.sh          # リポジトリルートから
```

`tests/test_load.py` covers §13.3 Load: the §9.3 locks under concurrent manual
and scheduled runs, the §9.2 per-run quotas, and the §11.1 acceptance latency.
It runs against both store backends. See
[ADR-003](../../docs/ADR-003-定期Runのロックと負荷試験.md).

## Untrusted input

`security/prompt_guard.py` holds the §10.1 defences. External text reaches the
model only inside a nonced delimiter, system prompts are sandwiched between two
copies of the defence and carry a canary, and text is scanned deterministically
first.

Detection is asymmetric on purpose: a chat message that trips a `block` rule is
refused without a model call, while a fetched page is only recorded. Dropping
the page would let anyone hide a legitimate event by injecting one line into it.
See [ADR-004](../../docs/ADR-004-プロンプトインジェクション対策.md).

## Scheduled collection

`entrypoints/job.py` is the Cloud Run Job entry point for the daily run
(§14 Phase 2, ADR-008). It is deployed as `event-agent-daily` with 17 tasks run
one at a time — one theme per task (`hackathon-*` 4, `contest-*` 3,
`accelerator-*` 3, `cocreation-*` 3, `subsidy-*` 4) — and Cloud Scheduler
`event-agent-daily-0700` starts it every morning at 07:00 JST. Each theme
carries its own `kind`, lead query and `site:` queries: contests search
公募サイト / go.jp / ac.jp, accelerators and co-creation search Creww Growth and
AUBA (eiicon). Candidates whose own page says a different genre are dropped
before validation.

```bash
PYTHONPATH=src python -m event_agent.entrypoints.job                  # all themes, in order
PYTHONPATH=src python -m event_agent.entrypoints.job hackathon-kansai # one theme
```

Its idempotency key is `theme:<id> + JST date + RUN_SCHEDULE_VERSION`, so a
retried execution finds the day already claimed and exits without collecting
again. Pages extracted within `KNOWN_URL_REFRESH_DAYS` (7) are not sent to the
model again, and the day's Grounding searches are capped by
`DAILY_GROUNDING_CAP` (90) via the `usage/{jstDate}` document.

## Docker

```bash
docker build -t event-agent .
docker run -p 8080:8080 -e AGENT_DEMO_MODE=true event-agent
```

Grounding search and function calling are never combined in a single Gemini request (`clients/gemini.py`).

## Subsidies (jGrants)

`subsidy-*` themes do not search the web. They read the public jGrants API
(`clients/jgrants.py`), so they cost no Grounding queries and no model calls, and
the deadline comes from `acceptance_end_datetime` instead of a page. Subsidies
carry no event date: the UI shows 実施日 as 「なし」. See
[ADR-011](../../docs/ADR-011-補助金はAPIから取る.md).

```bash
PYTHONPATH=src python -m event_agent.entrypoints.job subsidy-dx
```

Demo mode and the tests use the fixtures in `demo/subsidies.py` and never reach
the network.
