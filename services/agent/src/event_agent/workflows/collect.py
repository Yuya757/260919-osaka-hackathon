from __future__ import annotations

import asyncio
import re
from uuid import uuid4

from event_agent.config import settings
from event_agent.demo_catalog import demo_catalog
from event_agent.gemini_client import gemini_client
from event_agent.schemas import AgentRun, ApiEvent, UserPreferences
from event_agent.store import store


async def _set_step(run: AgentRun, step: str) -> AgentRun:
    run.current_step = step
    run.status = "running"
    return store.update_run(run)


def _normalize_preferences(preferences: UserPreferences) -> UserPreferences:
    prompt = preferences.interests_prompt.strip() or "ハッカソン、生成AI、GCP"
    locations = list(preferences.locations)
    if any(token in prompt for token in ("関西", "大阪", "京都", "神戸")) and not locations:
        locations = ["関西"]
    return preferences.model_copy(
        update={
            "interests_prompt": prompt,
            "locations": locations,
            "target_year": preferences.target_year or 2026,
        }
    )


def _plan_queries(preferences: UserPreferences) -> list[str]:
    base = preferences.interests_prompt
    year = preferences.target_year
    location = " ".join(preferences.locations) if preferences.locations else "日本"
    queries = [
        f"{year} {location} {base} イベント 応募締切",
        f"{year} {base} ハッカソン",
        f"{year} {base} ミートアップ",
    ]
    return queries[: settings.max_search_queries]


def _score_event(event: ApiEvent, preferences: UserPreferences) -> int:
    text = (
        f"{event.title} {event.summary} {event.category} "
        f"{event.location.region or ''}"
    ).lower()
    score = 40
    tokens = re.split(r"[\s、,/]+", preferences.interests_prompt.lower())
    for token in tokens:
        if token and token in text:
            score += 8
    if preferences.online_allowed and event.location.type in {"online", "hybrid"}:
        score += 10
    if preferences.locations:
        for location in preferences.locations:
            if location and location in (event.location.region or ""):
                score += 12
    if event.dates.event_start.year == preferences.target_year:
        score += 10
    return min(score, 99)


def _filter_catalog(preferences: UserPreferences) -> list[ApiEvent]:
    selected: list[ApiEvent] = []
    for event in demo_catalog():
        if event.dates.event_start.year != preferences.target_year:
            continue
        if not preferences.online_allowed and event.location.type == "online":
            continue
        score = _score_event(event, preferences)
        rec = event.recommendation
        selected.append(
            event.model_copy(
                update={
                    "recommendation": rec.model_copy(update={"score": score}) if rec else None,
                }
            )
        )
    selected.sort(
        key=lambda item: item.recommendation.score if item.recommendation else 0,
        reverse=True,
    )
    return selected[: settings.max_candidates]


async def _search_step(queries: list[str]) -> None:
    """Grounding search when Vertex is configured; otherwise demo catalog only."""
    if gemini_client.demo_mode:
        return
    for query in queries:
        await gemini_client.search_with_grounding(query)
        await asyncio.sleep(0.05)


def _validate(events: list[ApiEvent]) -> tuple[list[ApiEvent], list[ApiEvent]]:
    verified: list[ApiEvent] = []
    partial: list[ApiEvent] = []
    for event in events:
        if not event.title or not event.dates.event_start:
            continue
        if event.dates.application_deadline and event.dates.application_deadline > event.dates.event_start:
            continue
        if event.dates.application_deadline is None:
            partial.append(event.model_copy(update={"validation_status": "partial"}))
        else:
            verified.append(event.model_copy(update={"validation_status": "verified"}))
    return verified, partial


def _dedupe(events: list[ApiEvent]) -> list[ApiEvent]:
    seen: set[str] = set()
    unique: list[ApiEvent] = []
    for event in events:
        key = f"{event.title}|{event.dates.event_start.date()}|{event.official_url or ''}"
        if key in seen:
            continue
        seen.add(key)
        unique.append(event)
    return unique


async def execute_collect_workflow(
    run_id: str,
    preferences: UserPreferences,
    force_refresh: bool = False,
) -> None:
    run = store.get_run(run_id)
    if not run:
        return
    _ = force_refresh

    try:
        await _set_step(run, "normalize")
        await asyncio.sleep(0.15)
        normalized = _normalize_preferences(preferences)

        await _set_step(run, "plan")
        await asyncio.sleep(0.1)
        queries = _plan_queries(normalized)

        await _set_step(run, "search")
        await _search_step(queries)
        candidates = _filter_catalog(normalized)

        await _set_step(run, "extract_validate")
        await asyncio.sleep(0.1)
        verified, partial = _validate(candidates)

        await _set_step(run, "dedupe")
        await asyncio.sleep(0.1)
        events = _dedupe([*verified, *partial])

        await _set_step(run, "rank")
        events.sort(
            key=lambda item: item.recommendation.score if item.recommendation else 0,
            reverse=True,
        )

        await _set_step(run, "save")
        store.save_events(run.run_id, events)

        run.status = "succeeded" if verified else "partial_success"
        run.verified_count = len(verified)
        run.partial_count = len(partial)
        run.current_step = "completed"
        store.update_run(run)
    except Exception as exc:
        run.status = "failed"
        run.error_message = "イベント収集中にエラーが発生しました。"
        run.current_step = "failed"
        store.update_run(run)
        raise exc


def schedule_collect_run(
    preferences: UserPreferences,
    force_refresh: bool = False,
) -> AgentRun:
    run = AgentRun(runId=str(uuid4()), status="queued", currentStep="queued")
    store.create_run(run)
    asyncio.create_task(execute_collect_workflow(run.run_id, preferences, force_refresh))
    return run


async def run_collect_workflow(
    preferences: UserPreferences,
    force_refresh: bool = False,
) -> AgentRun:
    """Run workflow to completion (used from chat when immediate feedback is ok)."""
    run = AgentRun(runId=str(uuid4()), status="queued", currentStep="queued")
    store.create_run(run)
    await execute_collect_workflow(run.run_id, preferences, force_refresh)
    updated = store.get_run(run.run_id)
    return updated or run
