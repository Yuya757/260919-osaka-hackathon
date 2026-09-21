from __future__ import annotations

import logging

import httpx
from fastapi import FastAPI, Header, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from event_agent.agents.chat import handle_chat
from event_agent.config import get_settings
from event_agent.demo_catalog import demo_catalog
from event_agent.ekispert import (
    EkispertError,
    EkispertNotConfigured,
    RouteNotFound,
    StationNotFound,
    ekispert_client,
)
from event_agent.schemas import (
    AgentRun,
    AgentRunCreateRequest,
    AgentRunCreateResponse,
    ApiEvent,
    ChatRequest,
    ChatResponse,
    EventRouteResponse,
    EventsResponse,
    EvidenceListResponse,
    HealthResponse,
)
from event_agent.store import store
from event_agent.workflows.collect import schedule_collect_run

logging.basicConfig(level=logging.INFO)
# httpx logs full request URLs (including API keys in query strings) at INFO.
logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)

settings = get_settings()

app = FastAPI(
    title="Event Agent Service",
    version="0.1.0",
    description="Osaka hackathon MVP — event discovery agent (ADK-style workflow)",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    return HealthResponse(
        status="ok",
        demo_mode=not settings.use_vertex,
        model=settings.gemini_model if settings.use_vertex else None,
    )


@app.post("/api/chat", response_model=ChatResponse)
async def chat(body: ChatRequest) -> ChatResponse:
    return await handle_chat(body)


@app.post("/api/agent-runs", response_model=AgentRunCreateResponse)
async def create_agent_run(
    body: AgentRunCreateRequest,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> AgentRunCreateResponse:
    session = store.get_or_create_session(None)
    run = schedule_collect_run(
        session.preferences,
        force_refresh=body.force_refresh,
        idempotency_key=idempotency_key,
    )
    return AgentRunCreateResponse(runId=run.run_id, status="queued")


@app.get("/api/agent-runs/{run_id}", response_model=AgentRun)
async def get_agent_run(run_id: str) -> AgentRun:
    record = store.get_run(run_id)
    if not record:
        raise HTTPException(status_code=404, detail="Run not found")
    return record


@app.get("/api/events", response_model=EventsResponse)
async def list_events(
    sourceRunId: str | None = Query(default=None, description="Agent run ID"),
) -> EventsResponse:
    if sourceRunId:
        record = store.get_run(sourceRunId)
        if not record:
            raise HTTPException(status_code=404, detail="Run not found")
    events = [
        e
        for e in store.list_events(sourceRunId)
        if e.validation_status in ("verified", "partial")
    ]
    return EventsResponse(events=events)


def _find_event(event_id: str) -> ApiEvent | None:
    stored = store.get_event(event_id)
    if stored:
        return stored
    # デモカタログは保存されないことがあるため、最後に見る。
    for event in demo_catalog():
        if event.event_id == event_id:
            return event
    return None


@app.get("/api/events/{event_id}/evidence", response_model=EvidenceListResponse)
async def get_event_evidence(event_id: str) -> EvidenceListResponse:
    """根拠（§7.2）を返す。S-08 の根拠シートが使う。

    quarantined / rejected のイベントは通常UIへ出さないため、根拠も返さない（§8.3）。
    """
    event = _find_event(event_id)
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")
    if event.validation_status not in ("verified", "partial"):
        raise HTTPException(status_code=404, detail="Event not found")
    return EvidenceListResponse(
        eventId=event.event_id,
        evidence=store.get_evidence(event.source_run_id, event.evidence_ids),
    )


@app.get("/api/events/{event_id}/route", response_model=EventRouteResponse)
async def get_event_route(
    event_id: str,
    origin: str = Query(alias="from", min_length=1, max_length=40, description="出発駅名"),
) -> EventRouteResponse:
    event = _find_event(event_id)
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")
    if event.location.type == "online":
        raise HTTPException(status_code=400, detail="オンライン開催のため経路検索はできません。")
    destination_name = event.location.nearest_station or event.location.region
    if not destination_name:
        raise HTTPException(status_code=400, detail="会場の最寄駅が未確認のため経路検索できません。")
    if not ekispert_client.configured:
        raise HTTPException(status_code=503, detail="経路検索は現在利用できません。")

    try:
        origin_station = await ekispert_client.find_station(origin)
        destination_station = await ekispert_client.find_station(destination_name)
        route = await ekispert_client.search_route_arriving_by(
            origin_station, destination_station, event.dates.event_start
        )
    except EkispertNotConfigured as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except StationNotFound as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except RouteNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except EkispertError as exc:
        logger.warning("route search failed for %s: %s", event_id, exc)
        raise HTTPException(status_code=502, detail="経路検索サービスでエラーが発生しました。") from exc
    except httpx.HTTPError as exc:
        logger.warning("route search transport error for %s: %s %s", event_id, type(exc).__name__, exc)
        raise HTTPException(status_code=502, detail="経路検索サービスに接続できませんでした。") from exc

    return EventRouteResponse(eventId=event.event_id, arriveBy=event.dates.event_start, route=route)
