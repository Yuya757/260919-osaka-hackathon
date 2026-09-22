# Event Agent Service

FastAPI + ADK-style deterministic workflow for event discovery. Uses Vertex AI Gemini when `GCP_PROJECT_ID` is set; otherwise serves curated demo events for local UI development.

## API

- `GET /api/health`
- `POST /api/chat` — `{ "sessionId?", "message" }` → `{ sessionId, reply, actions? }`
- `POST /api/agent-runs` — `{ "forceRefresh?", "sessionId?" }` → `{ runId, status }`。`sessionId` を渡すとそのチャットの関心条件で探す。`MANUAL_RUNS_ENABLED=false` のときは 403
- `GET /api/agent-runs/{runId}` の `activity[]` — 各役割（planner / searcher / extractor / organizer）の行動。UI の「エージェントの動き」用
- `GET /api/agent-runs/{runId}`
- `GET /api/events?sourceRunId=&sessionId=` — `sourceRunId` があればその Run、無ければ共有プール（ADR-008）を `sessionId` の関心で採点した順。`lastCollectedAt` を添える
- `GET /api/events/{eventId}/route?from=<出発駅名>` — 駅すぱあと API でイベント開始時刻に到着する経路を 1 件返す（`EKISPERT_API_KEY` 必須。未設定時は 503）
- `POST /api/organizer-posts/preview` — 主催者投稿の下書き → `{ event|null, linkedEvent|null, issues[] }`。何も保存しない（F-06）
- `POST /api/organizer-posts` — 投稿を保存 → `201 { post, warnings[] }`。命令様の本文・非公開URLは `400`
- `GET /api/organizer-posts` — フィード。公開中で開催前の投稿を固定 → 優先 → 新しい順で返す

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
(§14 Phase 2). **It is not deployed**: no Job or Scheduler exists for it yet.

```bash
PYTHONPATH=src python -m event_agent.entrypoints.job [userId]
```

Its idempotency key is `userId + JST date + RUN_SCHEDULE_VERSION`, so a retried
execution finds the day already claimed and exits without collecting again.

## Docker

```bash
docker build -t event-agent .
docker run -p 8080:8080 -e AGENT_DEMO_MODE=true event-agent
```

Grounding search and function calling are never combined in a single Gemini request (`clients/gemini.py`).
