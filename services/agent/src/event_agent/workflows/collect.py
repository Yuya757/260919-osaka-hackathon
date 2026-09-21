from __future__ import annotations

import asyncio
import hashlib
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from event_agent.config import settings
from event_agent.demo.catalog import demo_catalog
from event_agent.demo.evidence import demo_evidence
from event_agent.demo.pages import DEMO_PAGE_SOURCES, demo_search_hits
from event_agent.domain.dedup import group_duplicates, merge_group
from event_agent.domain.ranking import score_recommendation
from event_agent.domain.validation import score_event
from event_agent.extraction import extract_candidates
from event_agent.clients.gemini import gemini_client
from event_agent.clients.page_fetcher import FetchedPage, SearchHit, page_fetcher
from event_agent.schemas import (
    DEMO_USER_ID,
    AgentRun,
    ApiEvent,
    Recommendation,
    UserPreferences,
)
from event_agent.security import prompt_guard
from event_agent.storage.store import store
from event_agent.trajectory import ToolTrajectory

logger = logging.getLogger(__name__)


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


def _filter_catalog(preferences: UserPreferences) -> list[ApiEvent]:
    """Demo catalog fallback, used only when extraction produced nothing."""
    selected: list[ApiEvent] = []
    for event in demo_catalog():
        if event.dates.event_start.year != preferences.target_year:
            continue
        if not preferences.online_allowed and event.location.type == "online":
            continue
        selected.append(event)
    return selected[: settings.max_candidates]


def _rank(
    events: list[ApiEvent],
    preferences: UserPreferences,
    *,
    run_id: str,
    now: datetime,
) -> list[ApiEvent]:
    """Apply the §6.8 deterministic score and sort by it."""
    ranked: list[ApiEvent] = []
    for event in events:
        evidence = store.get_evidence(run_id, event.evidence_ids)
        score = score_recommendation(event, evidence, preferences, now=now)
        reason = event.recommendation.reason if event.recommendation else ""
        ranked.append(
            event.model_copy(
                update={
                    "recommendation": Recommendation(score=score, reason=reason)
                }
            )
        )
    ranked.sort(
        key=lambda item: item.recommendation.score if item.recommendation else 0,
        reverse=True,
    )
    return ranked


async def _search_step(
    queries: list[str], trajectory: ToolTrajectory | None = None
) -> list[SearchHit]:
    """Collect search hits (§6.4).

    This used to discard the results, which meant nothing flowed from search
    into the candidate list. In demo mode there is no Vertex, so fixture hits
    stand in and the rest of the pipeline runs unchanged.
    """
    hits: list[SearchHit] = []
    seen: set[str] = set()

    if gemini_client.demo_mode:
        for hit in demo_search_hits(queries):
            if hit.url not in seen:
                seen.add(hit.url)
                hits.append(hit)
        if trajectory is not None:
            for query in queries:
                trajectory.record("search_with_grounding", query)
        return hits[: settings.max_candidates]

    for query in queries:
        if trajectory is not None:
            trajectory.record("search_with_grounding", query)
        for raw in await gemini_client.search_with_grounding(query):
            url = raw.get("url", "")
            if url and url not in seen:
                seen.add(url)
                hits.append(
                    SearchHit(
                        url=url,
                        title=raw.get("title", ""),
                        excerpt=raw.get("excerpt", ""),
                        query=query,
                    )
                )
        await asyncio.sleep(0.05)
    return hits[: settings.max_candidates]


async def _fetch_step(
    hits: list[SearchHit], trajectory: ToolTrajectory | None = None
) -> tuple[list[FetchedPage], list[str]]:
    """Fetch each hit. Rejected URLs are reported, not raised (§9.1 候補単位)."""
    pages: list[FetchedPage] = []
    rejected: list[str] = []
    for hit in hits[: settings.max_candidates]:
        result = await page_fetcher.fetch(hit.url, trajectory)
        if isinstance(result, FetchedPage):
            _note_injection_attempt(result, trajectory)
            pages.append(result)
        else:
            rejected.append(f"{result.reason}:{hit.url}")
    return pages, rejected


def _note_injection_attempt(
    page: FetchedPage, trajectory: ToolTrajectory | None
) -> None:
    """Record injected instructions in a page without discarding the page.

    §13.2 asks for「悪意あるページによるTool逸脱 0件」— that the agent ignores the
    instruction, not that it drops the event. Quarantining on detection would
    let anyone hide a legitimate event from users by adding one line to its
    page, so detection here is observational: it goes to the log and to the
    tool trajectory that the evaluation inspects.
    """
    findings = prompt_guard.scan(page.text)
    if not findings:
        return
    codes = prompt_guard.codes(findings)
    logger.warning(
        "PROMPT_INJECTION_IN_PAGE url=%s codes=%s", page.final_url, codes
    )
    if trajectory is not None:
        trajectory.record(
            "detect_injection", page.final_url, outcome=",".join(codes)
        )


@dataclass
class Buckets:
    verified: list[ApiEvent]
    partial: list[ApiEvent]
    quarantined: list[ApiEvent]
    rejected: list[ApiEvent]

    def displayable(self) -> list[ApiEvent]:
        return [*self.verified, *self.partial]


def _validate(
    candidates: list,
    run_id: str,
    *,
    now: datetime,
    target_year: int | None = None,
) -> Buckets:
    """Attach evidence, score confidence app-side, and bucket by status.

    Confidence and validationStatus are derived in ``domain.validation`` from the
    evidence and the date checks, never from a model's self-report (§7.5).
    ``now`` is injected so the 終了済み check is reproducible (§13.2).
    """
    buckets = Buckets([], [], [], [])

    for candidate in candidates:
        event = candidate.event if hasattr(candidate, "event") else candidate
        evidence = (
            candidate.evidence
            if hasattr(candidate, "evidence")
            else demo_evidence().get(event.event_id, [])
        )
        if not event.title or not event.dates.event_start:
            continue
        scored = score_event(
            event.model_copy(update={"source_run_id": run_id, "last_seen_at": now}),
            evidence,
            threshold=settings.verified_confidence_threshold,
            now=now,
            target_year=target_year,
            aggregator_min_confidence=settings.aggregator_only_min_confidence,
        )
        store.save_evidence(run_id, evidence)
        scored = scored.model_copy(
            update={"evidence_ids": [e.evidence_id for e in evidence]}
        )
        if scored.validation_status == "verified":
            buckets.verified.append(scored)
        elif scored.validation_status == "partial":
            buckets.partial.append(scored)
        elif scored.validation_status == "rejected":
            buckets.rejected.append(scored)
        else:
            buckets.quarantined.append(scored)
    return buckets


def _dedupe(events: list[ApiEvent]) -> tuple[list[ApiEvent], int]:
    """Collapse duplicates using the §6.7 priority order. Returns the count too."""
    groups = group_duplicates(
        events, similarity_threshold=settings.title_similarity_threshold
    )
    merged = [merge_group(group) for group in groups]
    return merged, len(events) - len(merged)


async def execute_collect_workflow(
    run_id: str,
    preferences: UserPreferences,
    force_refresh: bool = False,
    *,
    now: datetime | None = None,
    trajectory: ToolTrajectory | None = None,
) -> None:
    """The 8-step collection workflow (§6).

    ``now`` is injected so the 終了済み check and the deadline-headroom score are
    reproducible; ``trajectory`` records tool calls for the evaluation's
    「Tool逸脱 0件」 check.
    """
    run = store.get_run(run_id)
    if not run:
        return
    _ = force_refresh
    now = now or datetime.now(timezone.utc)
    delay = settings.step_delay_seconds
    # §9.2 の「1 Run最大15回」はRunごと。シングルトンの積算を毎回戻す。
    gemini_client.reset_call_budget()

    try:
        await _set_step(run, "normalize")
        await asyncio.sleep(delay)
        normalized = _normalize_preferences(preferences)

        await _set_step(run, "plan")
        await asyncio.sleep(delay)
        queries = _plan_queries(normalized)

        await _set_step(run, "search")
        hits = await _search_step(queries, trajectory)

        pages, fetch_rejected = await _fetch_step(hits, trajectory)

        await _set_step(run, "extract_validate")
        await asyncio.sleep(delay)
        hits_by_url = {hit.url: hit for hit in hits}
        candidates = extract_candidates(
            pages,
            hits=hits_by_url,
            run_id=run.run_id,
            now=now,
            user_id=run.user_id,
            source_types=DEMO_PAGE_SOURCES,
        )
        if trajectory is not None:
            for candidate in candidates:
                trajectory.record("extract", candidate.event.official_url)

        # 抽出が0件のときだけデモカタログで補う。実運用では抽出結果を使う。
        if not candidates and settings.demo_catalog_fallback:
            candidates = _filter_catalog(normalized)

        buckets = _validate(
            candidates, run.run_id, now=now, target_year=normalized.target_year
        )

        await _set_step(run, "dedupe")
        await asyncio.sleep(delay)
        events, duplicate_count = _dedupe(buckets.displayable())

        await _set_step(run, "rank")
        events = _rank(events, normalized, run_id=run.run_id, now=now)

        await _set_step(run, "save")
        store.save_events(run.run_id, events)
        if trajectory is not None:
            trajectory.record("save_agent_results", run.run_id)

        # §6.9: partial_success は「一部候補だけ失敗した」場合。validationStatus が
        # partial のイベントは取得に成功しており、失敗ではない。保留(quarantined)や
        # 取得できなかった候補があるときだけ partial_success とする。
        dropped = len(buckets.quarantined) + len(fetch_rejected)
        run.status = "partial_success" if dropped else "succeeded"
        run.verified_count = len(buckets.verified)
        run.partial_count = len(buckets.partial)
        run.quarantined_count = len(buckets.quarantined)
        run.rejected_count = len(buckets.rejected)
        run.duplicate_count = duplicate_count
        run.candidate_count = len(candidates)
        run.query_count = len(queries)
        run.error_count = len(fetch_rejected)
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


JST = timezone(timedelta(hours=9))


def _new_run(
    idempotency_key: str | None,
    *,
    trigger_type: str = "manual",
    user_id: str = DEMO_USER_ID,
) -> AgentRun:
    """Create a queued run. Manual runs take the client key, else server-issued (§9.3)."""
    return AgentRun(
        runId=str(uuid4()),
        userId=user_id,
        idempotencyKey=idempotency_key or str(uuid4()),
        triggerType=trigger_type,
        status="queued",
        currentStep="queued",
        model=settings.gemini_model,
    )


def scheduled_idempotency_key(
    user_id: str, *, now: datetime, schedule_version: str
) -> str:
    """§9.3 の定期Runキー: ``userId + JST日付 + scheduleVersion``.

    The date is taken in JST because the schedule is "毎朝7時" in Japan; using
    UTC would give two different keys to a single Japanese morning whenever the
    job runs before 09:00 JST, which is exactly when it is meant to run.
    """
    jst_date = now.astimezone(JST).date().isoformat()
    material = f"{user_id}|{jst_date}|{schedule_version}"
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def schedule_collect_run(
    preferences: UserPreferences,
    force_refresh: bool = False,
    idempotency_key: str | None = None,
) -> AgentRun:
    run = _new_run(idempotency_key)
    stored = store.create_run(run)
    if stored.run_id != run.run_id:
        # The key was already claimed. Return that run rather than collecting
        # the same thing twice (§9.3).
        return stored
    asyncio.create_task(execute_collect_workflow(run.run_id, preferences, force_refresh))
    return run


async def run_collect_workflow(
    preferences: UserPreferences,
    force_refresh: bool = False,
    *,
    now: datetime | None = None,
    trajectory: ToolTrajectory | None = None,
) -> AgentRun:
    """Run workflow to completion (used from chat and from the evaluation)."""
    run = _new_run(None)
    run = store.create_run(run)
    await execute_collect_workflow(
        run.run_id, preferences, force_refresh, now=now, trajectory=trajectory
    )
    updated = store.get_run(run.run_id)
    return updated or run


async def run_daily_collection(
    preferences: UserPreferences,
    *,
    user_id: str = DEMO_USER_ID,
    now: datetime | None = None,
) -> tuple[AgentRun, bool]:
    """定期収集（§14 Phase 2 の Cloud Run Job が呼ぶ想定）。

    Returns the run and whether this call is the one that started it. The key
    is derived, not random, so a retried Job execution, an overlapping schedule
    and a duplicate trigger all land on the same document and only the first
    one collects (§9.3).
    """
    now = now or datetime.now(timezone.utc)
    key = scheduled_idempotency_key(
        user_id, now=now, schedule_version=settings.run_schedule_version
    )
    run = _new_run(key, trigger_type="scheduled", user_id=user_id)
    stored = store.create_run(run)
    if stored.run_id != run.run_id:
        return stored, False
    await execute_collect_workflow(run.run_id, preferences, False, now=now)
    return store.get_run(run.run_id) or run, True
