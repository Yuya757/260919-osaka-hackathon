from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field

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
    run_id: str = Field(alias="runId")
    status: AgentRunStatus
    current_step: str | None = Field(default=None, alias="currentStep")
    verified_count: int = Field(default=0, alias="verifiedCount")
    partial_count: int = Field(default=0, alias="partialCount")
    error_message: str | None = Field(default=None, alias="errorMessage")

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
    event_start: datetime = Field(alias="eventStart")
    event_end: datetime | None = Field(default=None, alias="eventEnd")
    timezone: str = "Asia/Tokyo"

    model_config = {"populate_by_name": True, "serialize_by_alias": True}


class Recommendation(BaseModel):
    score: int
    reason: str


class ApiEvent(BaseModel):
    event_id: str = Field(alias="eventId")
    title: str
    organizer: str | None = None
    category: str
    summary: str
    location: EventLocation
    dates: EventDates
    official_url: str | None = Field(default=None, alias="officialUrl")
    application_url: str | None = Field(default=None, alias="applicationUrl")
    validation_status: Literal[
        "verified", "partial", "quarantined", "rejected"
    ] = Field(default="verified", alias="validationStatus")
    recommendation: Recommendation | None = None
    source: str = "公式サイトで確認済み"

    model_config = {"populate_by_name": True, "serialize_by_alias": True}


class EventsResponse(BaseModel):
    events: list[ApiEvent]


class EventRouteResponse(BaseModel):
    event_id: str = Field(alias="eventId")
    arrive_by: datetime = Field(alias="arriveBy")
    route: RouteSummary

    model_config = {"populate_by_name": True, "serialize_by_alias": True}
