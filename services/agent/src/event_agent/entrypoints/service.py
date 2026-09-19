from __future__ import annotations

import logging

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from event_agent.agents.chat import handle_chat
from event_agent.config import get_settings
from event_agent.schemas import (
    AgentRunCreateRequest,
    AgentRunCreateResponse,
    AgentRun,
    ChatRequest,
    ChatResponse,
    EventsResponse,
    HealthResponse,
)
from event_agent.store import store
from event_agent.workflows.collect import schedule_collect_run

logging.basicConfig(level=logging.INFO)
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
async def create_agent_run(body: AgentRunCreateRequest) -> AgentRunCreateResponse:
    session = store.get_or_create_session(None)
    run = schedule_collect_run(session.preferences, force_refresh=body.force_refresh)
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
