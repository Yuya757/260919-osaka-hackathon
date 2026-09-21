from __future__ import annotations

import asyncio
import re
from datetime import datetime, timezone
from uuid import uuid4

from event_agent.config import settings
from event_agent.demo_catalog import demo_catalog
from event_agent.demo_evidence import demo_evidence
from event_agent.enrichment import score_event
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


def _validate(
    events: list[ApiEvent], run_id: str
) -> tuple[list[ApiEvent], list[ApiEvent], list[ApiEvent]]:
    """Attach evidence, score confidence app-side, and bucket by status.

    Confidence and validationStatus are derived in ``enrichment`` from the
    evidence and the date checks, never from a model's self-report (§7.5).
    """
    catalog = demo_evidence()
    now = datetime.now(timezone.utc)
    verified: list[ApiEvent] = []
    partial: list[ApiEvent] = []
    quarantined: list[ApiEvent] = []

    for event in events:
        if not event.title or not event.dates.event_start:
            continue
        evidence = catalog.get(event.event_id, [])
        scored = score_event(
            event.model_copy(update={"source_run_id": run_id, "last_seen_at": now}),
            evidence,
            threshold=settings.verified_confidence_threshold,
        )
        store.save_evidence(evidence)
        if scored.validation_status == "verified":
            verified.append(scored)
        elif scored.validation_status == "partial":
            partial.append(scored)
        else:
            quarantined.append(scored)
    return verified, partial, quarantined


def _dedupe(events: list[ApiEvent]) -> list[ApiEvent]:
    """Collapse duplicates on the stable dedupKey (§9.3)."""
    seen: set[str] = set()
    unique: list[ApiEvent] = []
    for event in events:
        if event.dedup_key in seen:
            continue
        seen.add(event.dedup_key)
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
        verified, partial, quarantined = _validate(candidates, run.run_id)

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

        # §6.9: partial_success は「一部候補だけ失敗した」場合。validationStatus が
        # partial のイベントは取得に成功しており、失敗ではない。保留(quarantined)に
        # 落ちた候補があるときだけ partial_success とする。
        run.status = "partial_success" if quarantined else "succeeded"
        run.verified_count = len(verified)
        run.partial_count = len(partial)
        run.quarantined_count = len(quarantined)
        run.candidate_count = len(candidates)
        run.query_count = len(queries)
        run.current_step = "completed"
        run.completed_at = datetime.now(timezone.utc)
        store.update_run(run)
    except Exception as exc:
        run.status = "failed"
        run.error_message = "イベント収集中にエラーが発生しました。"
        run.current_step = "failed"
        run.error_count += 1
        run.completed_at = datetime.now(timezone.utc)
        store.update_run(run)
        raise exc


def _new_run(idempotency_key: str | None) -> AgentRun:
    """Create a queued run. Manual runs take the client key, else server-issued (§9.3)."""
    return AgentRun(
        runId=str(uuid4()),
        idempotencyKey=idempotency_key or str(uuid4()),
        triggerType="manual",
        status="queued",
        currentStep="queued",
        model=settings.gemini_model,
    )


def schedule_collect_run(
    preferences: UserPreferences,
    force_refresh: bool = False,
    idempotency_key: str | None = None,
) -> AgentRun:
    run = _new_run(idempotency_key)
    store.create_run(run)
    asyncio.create_task(execute_collect_workflow(run.run_id, preferences, force_refresh))
    return run


async def run_collect_workflow(
    preferences: UserPreferences,
    force_refresh: bool = False,
) -> AgentRun:
    """Run workflow to completion (used from chat when immediate feedback is ok)."""
    run = _new_run(None)
    store.create_run(run)
    await execute_collect_workflow(run.run_id, preferences, force_refresh)
    updated = store.get_run(run.run_id)
    return updated or run
