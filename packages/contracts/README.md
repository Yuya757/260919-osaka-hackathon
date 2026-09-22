# @event-agent/contracts

Shared [JSON Schema](https://json-schema.org/) definitions for HTTP API payloads and persisted event documents used by `apps/web` and `services/agent`.

Field names follow `docs/Agent詳細要件定義書.md` sections 7 (data) and 8 (interfaces).

| File | Schemas |
| --- | --- |
| `schemas/chat.json` | `ChatRequest`, `ChatResponse`, `ChatAction`, `UserPreferences` |
| `schemas/agent-run.json` | `CreateAgentRunRequest`, `CreateAgentRunResponse`, `AgentRun` |
| `schemas/event.json` | `Event`, `EventLocation`, `EventDates`, `EventRecommendation`, `GoogleCalendarEventIds` |
| `schemas/evidence.json` | `Evidence`, `EvidenceListResponse` (section 7.2) |
| `schemas/route.json` | `Station`, `RouteLeg`, `RouteSummary`, `EventRouteResponse` |
| `schemas/pool-search.json` | `PoolSearchRequest`, `SearchIntent`, `SearchActivity`, `PoolSearchResponse`（ADR-010） |
| `schemas/organizer-post.json` | `OrganizerPost`, `OrganizerPostRequest`, `PostIssue`, `PostPlacement`, and the preview / create / list responses (F-06, ADR-006) |
| `schemas/index.json` | Catalog of all schema documents |

Timestamps are ISO 8601 strings (`date-time`). Agent run `status` values match the Firestore lifecycle in section 7.1.

## Conformance

Every `Event` object has `additionalProperties: false` and 16 required fields. `services/agent/tests/test_contracts.py` validates the live API responses against these schemas, so a backend model that drifts from the contract fails the test suite. Update the schema here **before** changing the API or Firestore shape, per `AGENTS.md`.

## Design decisions

- **Calendar registration state lives in `Event.googleCalendarEventIds`, not in `status`.** The top-level requirements (§6.2) list `added_to_calendar` as a lifecycle status, but §7.3 models the two calendar entries separately. Keeping them apart lets a user bookmark an event and register only its deadline. `EventLifecycleStatus` therefore stays `suggested | bookmarked | dismissed`.
- **`Event.source` is deprecated.** It is a Phase 1 display string. Once `Evidence.sourceType` is populated for every event, the UI should derive the label from evidence and the field should be removed.
- **An `OrganizerPost` embeds its derived `Event` and `Evidence[]`; it is not an `Event`.** Posts are never written to `events/`, so `GET /api/events` and the run-scoped evidence lookup stay untouched. `organizer-post.json` is the first schema to `$ref` across documents (`event.json`, `evidence.json`).
- **Evidence stores excerpts, never full pages** (§7.2): the minimum quote needed for verification, plus the URL and a content hash.
