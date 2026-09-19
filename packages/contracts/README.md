# @event-agent/contracts

Shared [JSON Schema](https://json-schema.org/) definitions for HTTP API payloads and persisted event documents used by `apps/web` and `services/agent`.

Field names follow `docs/Agent詳細要件定義書.md` sections 7 (data) and 8 (interfaces).

| File | Schemas |
| --- | --- |
| `schemas/chat.json` | `ChatRequest`, `ChatResponse`, `ChatAction`, `UserPreferences` |
| `schemas/agent-run.json` | `CreateAgentRunRequest`, `CreateAgentRunResponse`, `AgentRun` |
| `schemas/event.json` | `Event`, `EventLocation`, `EventDates`, `EventRecommendation` |
| `schemas/index.json` | Catalog of all schema documents |

Timestamps are ISO 8601 strings (`date-time`). Agent run `status` values match the Firestore lifecycle in section 7.1.
