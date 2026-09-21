from datetime import datetime, timezone
from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field, model_validator

from event_agent.enrichment import compute_dedup_key, normalize_title

DEMO_USER_ID = "demo-user"

from event_agent.ekispert import RouteSummary


class UserPreferences(BaseModel):
    interests_prompt: str = Field(
        default="ハッカソン、生成AI、GCP、関西", alias="interestsPrompt"
    )
    target_year: int = Field(default=2026, alias="targetYear")
    online_allowed: bool = Field(default=True, alias="onlineAllowed")
    locations: list[str] = Field(default_factory=lambda: ["関西", "大阪"])

    model_config = {"populate_by_name": True, "serialize_by_alias": True}


def preferences_to_api_dict(prefs: UserPreferences) -> dict[str, Any]:
    return prefs.model_dump(by_alias=True)


class ChatRequest(BaseModel):
    session_id: str | None = Field(default=None, alias="sessionId")
    message: str = Field(min_length=1, max_length=2000)

    model_config = {"populate_by_name": True}


class AgentRunStartedAction(BaseModel):
    type: Literal["agent_run_started"] = "agent_run_started"
    run_id: str = Field(alias="runId")

    model_config = {"populate_by_name": True, "serialize_by_alias": True}


class PreferencesUpdatedAction(BaseModel):
    type: Literal["preferences_updated"] = "preferences_updated"
    preferences: dict[str, Any]


class EventsReadyAction(BaseModel):
    type: Literal["events_ready"] = "events_ready"
    count: int


ChatAction = Annotated[
    AgentRunStartedAction | PreferencesUpdatedAction | EventsReadyAction,
    Field(discriminator="type"),
]


class ChatResponse(BaseModel):
    session_id: str = Field(alias="sessionId")
    reply: str
    actions: list[ChatAction] = Field(default_factory=list)
    # Grounding由来の生成文を表示する画面は、このHTMLを無改変で描画する（§6.4）
    search_suggestions_html: str | None = Field(
        default=None, alias="searchSuggestionsHtml"
    )

    model_config = {"populate_by_name": True, "serialize_by_alias": True}


class AgentRunCreateRequest(BaseModel):
    force_refresh: bool = Field(default=False, alias="forceRefresh")

    model_config = {"populate_by_name": True}


class AgentRunCreateResponse(BaseModel):
    run_id: str = Field(alias="runId")
    status: Literal["queued", "running"] = "queued"

    model_config = {"populate_by_name": True, "serialize_by_alias": True}


AgentRunStatus = Literal[
    "queued",
    "running",
    "succeeded",
    "partial_success",
    "failed",
    "cancelled",
]


class AgentRun(BaseModel):
    """Agent run record (§7.1). Mirrors packages/contracts/schemas/agent-run.json.

    ``GET /api/agent-runs/{runId}`` returns this as-is, so it must never carry
    internal prompts, secrets or stack traces (§8.2).
    """

    run_id: str = Field(alias="runId")
    user_id: str = Field(default=DEMO_USER_ID, alias="userId")
    trigger_type: Literal["manual", "scheduled"] = Field(
        default="manual", alias="triggerType"
    )
    idempotency_key: str = Field(alias="idempotencyKey")
    status: AgentRunStatus
    current_step: str | None = Field(default=None, alias="currentStep")
    model: str | None = None
    query_count: int = Field(default=0, ge=0, alias="queryCount")
    candidate_count: int = Field(default=0, ge=0, alias="candidateCount")
    verified_count: int = Field(default=0, ge=0, alias="verifiedCount")
    partial_count: int = Field(default=0, ge=0, alias="partialCount")
    quarantined_count: int = Field(default=0, ge=0, alias="quarantinedCount")
    duplicate_count: int = Field(default=0, ge=0, alias="duplicateCount")
    error_count: int = Field(default=0, ge=0, alias="errorCount")
    # ユーザー向けの要約のみ。内部情報を入れてはならない（§8.2）
    error_message: str | None = Field(default=None, alias="errorMessage")
    started_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc), alias="startedAt"
    )
    completed_at: datetime | None = Field(default=None, alias="completedAt")

    model_config = {"populate_by_name": True, "serialize_by_alias": True}


class HealthResponse(BaseModel):
    status: str = "ok"
    demo_mode: bool
    model: str | None = None


class EventLocation(BaseModel):
    type: Literal["online", "offline", "hybrid", "unknown"] = "unknown"
    venue: str | None = None
    region: str | None = None
    nearest_station: str | None = Field(default=None, alias="nearestStation")

    model_config = {"populate_by_name": True, "serialize_by_alias": True}


class EventDates(BaseModel):
    application_deadline: datetime | None = Field(
        default=None, alias="applicationDeadline"
    )
    # 精度。'date' のとき UI は時刻を表示してはならない（§3.2 / §6.6）
    application_deadline_precision: Literal["datetime", "date", "unknown"] = Field(
        default="unknown", alias="applicationDeadlinePrecision"
    )
    event_start: datetime = Field(alias="eventStart")
    event_start_precision: Literal["datetime", "date"] = Field(
        default="datetime", alias="eventStartPrecision"
    )
    event_end: datetime | None = Field(default=None, alias="eventEnd")
    timezone: str = "Asia/Tokyo"

    model_config = {"populate_by_name": True, "serialize_by_alias": True}

    @model_validator(mode="after")
    def _default_deadline_precision(self) -> "EventDates":
        if self.application_deadline is None:
            object.__setattr__(self, "application_deadline_precision", "unknown")
        elif self.application_deadline_precision == "unknown":
            object.__setattr__(self, "application_deadline_precision", "datetime")
        return self


class GoogleCalendarEventIds(BaseModel):
    deadline_event_id: str | None = Field(default=None, alias="deadlineEventId")
    main_event_id: str | None = Field(default=None, alias="mainEventId")

    model_config = {"populate_by_name": True, "serialize_by_alias": True}


class GroundingMetadata(BaseModel):
    chunk_index: int = Field(alias="chunkIndex")
    support_score: float | None = Field(default=None, alias="supportScore")

    model_config = {"populate_by_name": True, "serialize_by_alias": True}


SupportedField = Literal[
    "title",
    "summary",
    "organizer",
    "category",
    "location",
    "dates.eventStart",
    "dates.eventEnd",
    "dates.applicationDeadline",
    "officialUrl",
    "applicationUrl",
]


class Evidence(BaseModel):
    """根拠（§7.2）。ページ全文ではなく検証に必要な最小限の引用のみを保持する。"""

    evidence_id: str = Field(alias="evidenceId")
    query: str | None = None
    source_url: str = Field(alias="sourceUrl")
    canonical_url: str | None = Field(default=None, alias="canonicalUrl")
    source_type: Literal["official", "organizer", "aggregator", "other"] = Field(
        alias="sourceType"
    )
    title: str | None = None
    excerpt: str | None = Field(default=None, max_length=500)
    supports: list[SupportedField]
    retrieved_at: datetime = Field(alias="retrievedAt")
    grounding_metadata: GroundingMetadata | None = Field(
        default=None, alias="groundingMetadata"
    )
    content_hash: str | None = Field(default=None, alias="contentHash")

    model_config = {"populate_by_name": True, "serialize_by_alias": True}


class EvidenceListResponse(BaseModel):
    event_id: str = Field(alias="eventId")
    evidence: list[Evidence]

    model_config = {"populate_by_name": True, "serialize_by_alias": True}


class Recommendation(BaseModel):
    score: int
    reason: str


class ApiEvent(BaseModel):
    """Event candidate (§7.3). Mirrors packages/contracts/schemas/event.json.

    ``normalizedTitle`` and ``dedupKey`` are derived, so callers may omit them;
    the validator fills them from the other fields.
    """

    event_id: str = Field(alias="eventId")
    user_id: str = Field(default=DEMO_USER_ID, alias="userId")
    title: str
    normalized_title: str = Field(default="", alias="normalizedTitle")
    organizer: str | None = None
    category: str
    summary: str
    location: EventLocation
    dates: EventDates
    # §6.6「必須項目: title、eventStart、source URLが存在」により non-null
    official_url: str = Field(alias="officialUrl")
    application_url: str | None = Field(default=None, alias="applicationUrl")
    validation_status: Literal[
        "verified", "partial", "quarantined", "rejected"
    ] = Field(default="verified", alias="validationStatus")
    # アプリ側で算出する。LLMの自己申告値を使ってはならない（§7.5）
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    evidence_ids: list[str] = Field(default_factory=list, alias="evidenceIds")
    dedup_key: str = Field(default="", alias="dedupKey")
    recommendation: Recommendation | None = None
    first_seen_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc), alias="firstSeenAt"
    )
    last_seen_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc), alias="lastSeenAt"
    )
    source_run_id: str = Field(default="demo", alias="sourceRunId")
    status: Literal["suggested", "bookmarked", "dismissed"] = "suggested"
    google_calendar_event_ids: GoogleCalendarEventIds = Field(
        default_factory=GoogleCalendarEventIds, alias="googleCalendarEventIds"
    )
    # 非推奨。Evidence.sourceType へ統合して廃止する
    source: str = "公式サイトで確認済み"

    model_config = {"populate_by_name": True, "serialize_by_alias": True}

    @model_validator(mode="after")
    def _derive(self) -> "ApiEvent":
        if not self.normalized_title:
            object.__setattr__(self, "normalized_title", normalize_title(self.title))
        if not self.dedup_key:
            object.__setattr__(
                self,
                "dedup_key",
                compute_dedup_key(
                    self.official_url,
                    self.normalized_title,
                    self.dates.event_start,
                    self.organizer,
                ),
            )
        return self


class EventsResponse(BaseModel):
    events: list[ApiEvent]


class EventRouteResponse(BaseModel):
    event_id: str = Field(alias="eventId")
    arrive_by: datetime = Field(alias="arriveBy")
    route: RouteSummary

    model_config = {"populate_by_name": True, "serialize_by_alias": True}
