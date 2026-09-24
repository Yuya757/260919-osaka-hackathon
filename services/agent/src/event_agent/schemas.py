from datetime import date, datetime, timezone
from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field, model_validator

from event_agent.domain.normalize import compute_dedup_key, normalize_title, normalize_url

DEMO_USER_ID = "demo-user"
# テーマ単位の定期収集（ADR-008）は特定のユーザーの Run ではない
SYSTEM_USER_ID = "system"

from event_agent.clients.ekispert import RouteSummary


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
    # チャットで更新した関心条件をそのまま使う。無ければ既定の条件で探す
    session_id: str | None = Field(default=None, alias="sessionId")

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


RunAgent = Literal["planner", "searcher", "extractor", "organizer"]

# Run 文書を小さく保つ。超えたら古い行から捨てる
RUN_ACTIVITY_MAX = 80


class RunActivity(BaseModel):
    """パイプラインの各役割が何をしたかの1行。UI の「エージェントの動き」に出す。

    ユーザー向けの文だけを入れる。プロンプト・秘密・スタックトレースは禁止（§8.2）。
    """

    agent: RunAgent
    message: str = Field(max_length=300)
    level: Literal["info", "warn"] = "info"
    at: datetime

    model_config = {"populate_by_name": True, "serialize_by_alias": True}


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
    rejected_count: int = Field(default=0, ge=0, alias="rejectedCount")
    duplicate_count: int = Field(default=0, ge=0, alias="duplicateCount")
    error_count: int = Field(default=0, ge=0, alias="errorCount")
    # ユーザー向けの要約のみ。内部情報を入れてはならない（§8.2）
    error_message: str | None = Field(default=None, alias="errorMessage")
    started_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc), alias="startedAt"
    )
    completed_at: datetime | None = Field(default=None, alias="completedAt")
    # テーマ単位の定期収集（ADR-008）。手動 Run では None
    theme_id: str | None = Field(default=None, alias="themeId")
    # 課金単位の記録（§11.2）。Grounding 検索は 1,000 クエリ単位で課金される
    grounding_calls: int = Field(default=0, ge=0, alias="groundingCalls")
    model_calls: int = Field(default=0, ge=0, alias="modelCalls")
    skipped_known_count: int = Field(default=0, ge=0, alias="skippedKnownCount")
    activity: list[RunActivity] = Field(default_factory=list)

    model_config = {"populate_by_name": True, "serialize_by_alias": True}

    def log(self, agent: RunAgent, message: str, *, level: Literal["info", "warn"] = "info") -> None:
        """Append one activity line, dropping the oldest beyond the cap."""
        self.activity.append(
            RunActivity(agent=agent, message=message[:300], level=level, at=datetime.now(timezone.utc))
        )
        if len(self.activity) > RUN_ACTIVITY_MAX:
            del self.activity[: len(self.activity) - RUN_ACTIVITY_MAX]


class UsageRecord(BaseModel):
    """1 日（JST）の検索・生成の使用量（ADR-008 決定5）。`usage/{jstDate}`。"""

    day: str
    grounding_calls: int = Field(default=0, ge=0, alias="groundingCalls")
    model_calls: int = Field(default=0, ge=0, alias="modelCalls")
    updated_at: datetime | None = Field(default=None, alias="updatedAt")

    model_config = {"populate_by_name": True, "serialize_by_alias": True}


class HealthResponse(BaseModel):
    status: str = "ok"
    demo_mode: bool
    model: str | None = None
    # 手動の Grounding 探索を受け付けるか（ADR-008）。UI が「探す」の意味を切り替える
    manual_runs_enabled: bool = Field(default=True, alias="manualRunsEnabled")

    model_config = {"populate_by_name": True, "serialize_by_alias": True}


class EventLocation(BaseModel):
    type: Literal["online", "offline", "hybrid", "unknown"] = "unknown"
    venue: str | None = None
    region: str | None = None
    nearest_station: str | None = Field(default=None, alias="nearestStation")

    model_config = {"populate_by_name": True, "serialize_by_alias": True}


EventKind = Literal[
    "hackathon", "contest", "accelerator", "cocreation", "exhibition", "subsidy", "meetup"
]


class EventMilestone(BaseModel):
    """締切と実施日のあいだの節目（一次選考通過発表、最終審査会、結果発表など）。

    ビジコンやアクセラは「締切 → 実施」の 2 軸に潰すと時系列が落ちるので、
    残りをここに持つ。2 軸表示そのものは変えない。
    """

    label: str = Field(min_length=1, max_length=40)
    at: datetime
    precision: Literal["datetime", "date"] = "date"

    model_config = {"populate_by_name": True, "serialize_by_alias": True}


class EventDates(BaseModel):
    application_deadline: datetime | None = Field(
        default=None, alias="applicationDeadline"
    )
    # 精度。'date' のとき UI は時刻を表示してはならない（§3.2 / §6.6）
    application_deadline_precision: Literal["datetime", "date", "unknown"] = Field(
        default="unknown", alias="applicationDeadlinePrecision"
    )
    # 実施（開始）日時。締切だけが分かっている告知では None（ビジコン・補助金）
    event_start: datetime | None = Field(default=None, alias="eventStart")
    event_start_precision: Literal["datetime", "date", "unknown"] = Field(
        default="datetime", alias="eventStartPrecision"
    )
    event_end: datetime | None = Field(default=None, alias="eventEnd")
    milestones: list[EventMilestone] = Field(default_factory=list)
    timezone: str = "Asia/Tokyo"

    model_config = {"populate_by_name": True, "serialize_by_alias": True}

    @model_validator(mode="after")
    def _default_precisions(self) -> "EventDates":
        if self.event_start is None:
            object.__setattr__(self, "event_start_precision", "unknown")
        elif self.event_start_precision == "unknown":
            object.__setattr__(self, "event_start_precision", "datetime")
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


class EvidencePreview(BaseModel):
    """一覧に添える根拠の要約（出典と引用）。全文は evidence API で返す。"""

    source_url: str = Field(alias="sourceUrl")
    source_type: Literal["official", "organizer", "aggregator", "other"] = Field(alias="sourceType")
    supports: list[SupportedField]
    excerpt: str = Field(max_length=160)

    model_config = {"populate_by_name": True, "serialize_by_alias": True}


PREVIEW_FIELDS = ("dates.applicationDeadline", "dates.eventStart", "dates.eventEnd", "title")


def preview_evidence(evidence: list[Evidence], limit: int = 4) -> list[EvidencePreview]:
    """締切 → 開催日 → タイトルの順に、抜粋のある根拠を最大 limit 件にまとめる。"""
    picked: list[EvidencePreview] = []
    seen: set[tuple[str, str]] = set()
    for field in PREVIEW_FIELDS:
        for item in evidence:
            if field not in item.supports or not item.excerpt:
                continue
            key = (item.source_url, item.excerpt)
            if key in seen:
                continue
            seen.add(key)
            picked.append(
                EvidencePreview(
                    sourceUrl=item.canonical_url or item.source_url,
                    sourceType=item.source_type,
                    supports=list(item.supports),
                    excerpt=item.excerpt[:160],
                )
            )
            if len(picked) >= limit:
                return picked
    return picked


class OrganizerEditValues(BaseModel):
    """主催者が直せる項目（ADR-013）。None は「直していない」で、収集した値のまま。"""

    nearest_station: str | None = Field(default=None, alias="nearestStation", max_length=40)
    venue: str | None = Field(default=None, max_length=120)
    application_deadline: datetime | None = Field(default=None, alias="applicationDeadline")
    application_url: str | None = Field(default=None, alias="applicationUrl")

    model_config = {"populate_by_name": True, "serialize_by_alias": True}


class OrganizerEdit(BaseModel):
    """本人確認した主催者が直した値。再収集でも保ち、保存のたびに当て直す（ADR-013）。"""

    verified_at: datetime = Field(alias="verifiedAt")
    page_url: str = Field(alias="pageUrl")
    edited_at: datetime | None = Field(default=None, alias="editedAt")
    values: OrganizerEditValues = Field(default_factory=OrganizerEditValues)

    model_config = {"populate_by_name": True, "serialize_by_alias": True}


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
    # 機会の種別。絞り込みとラベル表の切り替えに使う（ジャンル拡張計画）
    kind: EventKind = "hackathon"
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
    theme_id: str | None = Field(default=None, alias="themeId")
    # 既知ページの照合キー。officialUrl から導出する
    normalized_official_url: str = Field(default="", alias="normalizedOfficialUrl")
    # 本文から実際に抽出した時刻。既知ページの省略では進まない（ADR-008）
    last_extracted_at: datetime | None = Field(default=None, alias="lastExtractedAt")
    # ジャンル固有の値（賞金・支援内容・対象ステージ…）。ページの行をそのまま持つ
    attributes: dict[str, str] = Field(default_factory=dict)
    # 本人確認した主催者が直した値（ADR-013）
    organizer_edit: OrganizerEdit | None = Field(default=None, alias="organizerEdit")
    status: Literal["suggested", "bookmarked", "dismissed"] = "suggested"
    google_calendar_event_ids: GoogleCalendarEventIds = Field(
        default_factory=GoogleCalendarEventIds, alias="googleCalendarEventIds"
    )
    # 一覧用の根拠の要約。保存はせず、list 応答でサーバーが添える
    evidence_preview: list[EvidencePreview] = Field(default_factory=list, alias="evidencePreview")
    # 非推奨。Evidence.sourceType へ統合して廃止する
    source: str = "公式サイトで確認済み"

    model_config = {"populate_by_name": True, "serialize_by_alias": True}

    @model_validator(mode="after")
    def _cap_attributes(self) -> "ApiEvent":
        """契約どおり 10 項目・各 60 字に収める。抽出側の取りこぼしで契約を割らない。"""
        if self.attributes:
            capped = {
                key: value.strip()[:60]
                for key, value in list(self.attributes.items())[:10]
                if key and value and value.strip()
            }
            if capped != self.attributes:
                object.__setattr__(self, "attributes", capped)
        return self

    @model_validator(mode="after")
    def _derive(self) -> "ApiEvent":
        if not self.normalized_title:
            object.__setattr__(self, "normalized_title", normalize_title(self.title))
        if not self.normalized_official_url:
            object.__setattr__(
                self, "normalized_official_url", normalize_url(self.official_url)
            )
        if not self.dedup_key:
            object.__setattr__(
                self,
                "dedup_key",
                compute_dedup_key(
                    self.official_url,
                    self.normalized_title,
                    self.dates.event_start,
                    self.organizer,
                    self.dates.application_deadline,
                ),
            )
        return self


class EventsResponse(BaseModel):
    events: list[ApiEvent]
    last_collected_at: datetime | None = Field(default=None, alias="lastCollectedAt")

    model_config = {"populate_by_name": True, "serialize_by_alias": True}


# ---------------------------------------------------------------- organizer posts

# 投稿から派生した Event の sourceRunId。agentRuns には対応するドキュメントを作らない。
# 根拠は投稿に埋め込むので Store.get_evidence を通らない（ADR-006）。
ORGANIZER_POST_RUN_ID = "organizer-posts"
ORGANIZER_POST_BODY_MAX = 4000

PostIssueCode = Literal[
    "EVENT_DATE_MISSING",
    "YEAR_AMBIGUOUS",
    "EVENT_FINISHED",
    "DATE_CONFLICT",
    "DEADLINE_MISSING",
    "DUPLICATE_OF_EVENT",
]


class PostPlacement(BaseModel):
    """固定/優先表示の枠（要件定義書 §7-2）。作成時は必ず normal。変更 API は無い。"""

    kind: Literal["normal", "pinned", "priority"] = "normal"
    until: datetime | None = None


class PostIssue(BaseModel):
    """投稿本文の抽出結果に対する指摘。error は投稿を拒み、warning は投稿者に確認を求める。"""

    code: PostIssueCode
    severity: Literal["error", "warning"]
    message: str


class OrganizerPostRequest(BaseModel):
    organizer_name: str = Field(min_length=1, max_length=80, alias="organizerName")
    contact_url: str = Field(min_length=1, max_length=2048, alias="contactUrl")
    title: str = Field(min_length=1, max_length=120)
    body: str = Field(min_length=1, max_length=ORGANIZER_POST_BODY_MAX)

    model_config = {"populate_by_name": True, "serialize_by_alias": True}


class OrganizerPost(BaseModel):
    """主催者投稿（F-06）。Mirrors packages/contracts/schemas/organizer-post.json.

    ``event`` は投稿本文から決定論的に抽出した Event の写し。``linkedEventId`` は
    AI 収集イベントと重複と判定されたときの相手で、相手側は書き換えない。
    """

    post_id: str = Field(alias="postId")
    user_id: str = Field(default=DEMO_USER_ID, alias="userId")
    origin: Literal["organizer", "bot"]
    organizer_name: str = Field(alias="organizerName")
    contact_url: str = Field(alias="contactUrl")
    title: str
    body: str
    event: ApiEvent
    evidence: list[Evidence] = Field(default_factory=list)
    status: Literal["published", "hidden"] = "published"
    placement: PostPlacement = Field(default_factory=PostPlacement)
    linked_event_id: str | None = Field(default=None, alias="linkedEventId")
    linked_dedup_key: str | None = Field(default=None, alias="linkedDedupKey")
    injection_flags: list[str] = Field(default_factory=list, alias="injectionFlags")
    # 管理者が主催者の本人性を確認した印（ADR-009）。再投稿で戻らない。ボット投稿は不可
    organizer_confirmed: bool = Field(default=False, alias="organizerConfirmed")
    confirmed_at: datetime | None = Field(default=None, alias="confirmedAt")
    created_at: datetime = Field(alias="createdAt")
    updated_at: datetime = Field(alias="updatedAt")

    model_config = {"populate_by_name": True, "serialize_by_alias": True}


# ---------------------------------------------------------------- metrics (ADR-009)

GoKind = Literal["official", "application", "contact"]


class MetricCounts(BaseModel):
    clicks: int = Field(default=0, ge=0)
    calendar: int = Field(default=0, ge=0)


class ClickCounts(BaseModel):
    official: int = Field(default=0, ge=0)
    application: int = Field(default=0, ge=0)
    contact: int = Field(default=0, ge=0)


class EventMetrics(BaseModel):
    """イベント単位の成果計測。アプリ内のクリックとカレンダー登録を数える。`eventMetrics/{eventId}`。"""

    event_id: str = Field(alias="eventId")
    clicks: ClickCounts = Field(default_factory=ClickCounts)
    calendar: int = Field(default=0, ge=0)
    daily: dict[str, MetricCounts] = Field(default_factory=dict)
    updated_at: datetime | None = Field(default=None, alias="updatedAt")

    model_config = {"populate_by_name": True, "serialize_by_alias": True}


class PostMetricsResponse(BaseModel):
    post_id: str = Field(alias="postId")
    event_id: str = Field(alias="eventId")
    linked_event_id: str | None = Field(default=None, alias="linkedEventId")
    metrics: EventMetrics
    linked_metrics: EventMetrics | None = Field(default=None, alias="linkedMetrics")

    model_config = {"populate_by_name": True, "serialize_by_alias": True}


class MetricEventRequest(BaseModel):
    kind: Literal["calendar"]


class OrganizerPostPreviewResponse(BaseModel):
    event: ApiEvent | None = None
    linked_event: ApiEvent | None = Field(default=None, alias="linkedEvent")
    issues: list[PostIssue] = Field(default_factory=list)

    model_config = {"populate_by_name": True, "serialize_by_alias": True}


class OrganizerPostCreateResponse(BaseModel):
    post: OrganizerPost
    warnings: list[PostIssue] = Field(default_factory=list)


class OrganizerPostListResponse(BaseModel):
    posts: list[OrganizerPost]


class EventRouteResponse(BaseModel):
    event_id: str = Field(alias="eventId")
    arrive_by: datetime = Field(alias="arriveBy")
    route: RouteSummary

    model_config = {"populate_by_name": True, "serialize_by_alias": True}


# ---------------------------------------------------------------- pool search (ADR-010)

SearchAgent = Literal["interpreter", "filter", "scorer", "presenter"]


class SearchIntent(BaseModel):
    """問いかけの構造化。モデルの出力は検証してから採用する。"""

    interests_prompt: str = Field(default="", alias="interestsPrompt")
    locations: list[str] = Field(default_factory=list)
    online_only: bool = Field(default=False, alias="onlineOnly")
    date_from: date | None = Field(default=None, alias="dateFrom")
    date_to: date | None = Field(default=None, alias="dateTo")
    keywords: list[str] = Field(default_factory=list)
    # 機会の種別（ジャンル拡張計画）。空なら種別では絞らない
    kinds: list[EventKind] = Field(default_factory=list)
    # 並び順。既定は適合順（ジャンル拡張計画 段階2）
    order: Literal["score", "deadline", "held"] = "score"

    model_config = {"populate_by_name": True, "serialize_by_alias": True}


class SearchActivity(BaseModel):
    agent: SearchAgent
    message: str = Field(max_length=300)
    level: Literal["info", "warn"] = "info"
    at: datetime

    model_config = {"populate_by_name": True, "serialize_by_alias": True}


class PoolSearchRequest(BaseModel):
    session_id: str | None = Field(default=None, alias="sessionId")
    query: str = Field(default="", max_length=500)
    # 渡すと動きを 1 行ずつ保存し、探索中でも読める（PoolSearchActivity）
    search_id: str | None = Field(
        default=None, alias="searchId", pattern=r"^[A-Za-z0-9-]{8,64}$"
    )

    model_config = {"populate_by_name": True}


class PoolSearchActivity(BaseModel):
    search_id: str = Field(alias="searchId")
    activity: list[SearchActivity] = Field(default_factory=list)

    model_config = {"populate_by_name": True, "serialize_by_alias": True}


class PoolSearchResponse(BaseModel):
    session_id: str = Field(alias="sessionId")
    reply: str
    intent: SearchIntent
    events: list[ApiEvent]
    activity: list[SearchActivity] = Field(default_factory=list)
    last_collected_at: datetime | None = Field(default=None, alias="lastCollectedAt")
    model_calls: int = Field(default=0, ge=0, alias="modelCalls")

    model_config = {"populate_by_name": True, "serialize_by_alias": True}


# ---------------------------------------------------------------- event claims (ADR-013)

ClaimStatus = Literal["verified", "code_not_found", "page_unavailable", "expired", "too_many_attempts"]


class EventClaim(BaseModel):
    """主催者の申請。API には出さない（鍵はハッシュだけを持つ）。"""

    claim_id: str = Field(alias="claimId")
    event_id: str = Field(alias="eventId")
    code: str
    page_urls: list[str] = Field(alias="pageUrls")
    created_at: datetime = Field(alias="createdAt")
    expires_at: datetime = Field(alias="expiresAt")
    attempts: int = 0
    verified_at: datetime | None = Field(default=None, alias="verifiedAt")
    verified_page_url: str | None = Field(default=None, alias="verifiedPageUrl")
    edit_token_hash: str | None = Field(default=None, alias="editTokenHash")
    token_expires_at: datetime | None = Field(default=None, alias="tokenExpiresAt")

    model_config = {"populate_by_name": True, "serialize_by_alias": True}


class EventClaimStartRequest(BaseModel):
    event_id: str = Field(alias="eventId", min_length=1, max_length=64)

    model_config = {"populate_by_name": True}


class EventClaimStartResponse(BaseModel):
    claim_id: str = Field(alias="claimId")
    event_id: str = Field(alias="eventId")
    code: str
    page_urls: list[str] = Field(alias="pageUrls")
    expires_at: datetime = Field(alias="expiresAt")

    model_config = {"populate_by_name": True, "serialize_by_alias": True}


class EventClaimVerifyRequest(BaseModel):
    claim_id: str = Field(alias="claimId", min_length=1, max_length=64)

    model_config = {"populate_by_name": True}


class EventClaimVerifyResponse(BaseModel):
    claim_id: str = Field(alias="claimId")
    status: ClaimStatus
    edit_token: str | None = Field(default=None, alias="editToken")
    token_expires_at: datetime | None = Field(default=None, alias="tokenExpiresAt")
    message: str

    model_config = {"populate_by_name": True, "serialize_by_alias": True}


class EventEditRequest(BaseModel):
    claim_id: str = Field(alias="claimId", min_length=1, max_length=64)
    edit_token: str = Field(alias="editToken", min_length=1, max_length=128)
    values: OrganizerEditValues

    model_config = {"populate_by_name": True}


class EventEditResponse(BaseModel):
    event: ApiEvent

    model_config = {"populate_by_name": True, "serialize_by_alias": True}


# ---------------------------------------------------------------- web search (ADR-014)


class WebSearchRequest(BaseModel):
    session_id: str | None = Field(default=None, alias="sessionId")
    query: str = Field(min_length=1, max_length=300)

    model_config = {"populate_by_name": True}


class WebSource(BaseModel):
    title: str
    uri: str


class WebSearchResponse(BaseModel):
    """Google 検索グラウンディングの答え。質問した本人にだけ返し、保存しない。"""

    session_id: str = Field(alias="sessionId")
    answer: str
    search_entry_point_html: str | None = Field(alias="searchEntryPointHtml")
    sources: list[WebSource] = Field(default_factory=list)
    generated_at: datetime = Field(alias="generatedAt")

    model_config = {"populate_by_name": True, "serialize_by_alias": True}
