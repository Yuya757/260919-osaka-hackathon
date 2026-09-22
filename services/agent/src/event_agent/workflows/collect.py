from __future__ import annotations

import asyncio
import hashlib
import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit
from uuid import uuid4

from event_agent.config import settings
from event_agent.demo.catalog import demo_catalog
from event_agent.demo.evidence import demo_evidence
from event_agent.demo.pages import DEMO_PAGE_SOURCES, demo_search_hits
from event_agent.domain.dedup import group_duplicates, merge_group
from event_agent.domain.ranking import score_recommendation
from event_agent.domain.validation import score_event
from event_agent.extraction import extract_candidates
from event_agent.extraction.model_locator import extract_with_model
from event_agent.extraction.sources import ARTICLE_HOSTS, is_article_host, source_type_for
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
from event_agent.workflows.organizer_posts import seed_bot_posts

logger = logging.getLogger(__name__)


async def _set_step(run: AgentRun, step: str) -> AgentRun:
    run.current_step = step
    run.status = "running"
    return store.update_run(run)


Note = Callable[..., None]


def _noop_note(agent: str, message: str, *, level: str = "info") -> None:
    del agent, message, level


def _host(url: str) -> str:
    return urlsplit(url).netloc or url


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
    # 一般検索と、イベントサイトを指名した検索を混ぜる。告知ページは
    # connpass / Peatix / Doorkeeper に集まっており、一般検索だとまとめ記事に
    # 押されて出てこないことが多い。クエリ数は §9.2 の呼び出し予算（1 Run 15回）
    # の中で、抽出の呼び出し分を残すために抑える。
    queries = [
        f"{year} {location} {base} イベント 申込",
        f"site:connpass.com {location} {base} {year}",
        f"site:peatix.com {location} {base} {year}",
        f"site:doorkeeper.jp OR site:techplay.jp {location} {base} {year}",
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
    queries: list[str],
    trajectory: ToolTrajectory | None = None,
    note: Note = _noop_note,
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
        for query in queries:
            note("searcher", f"「{query}」を検索（デモ用の固定結果）")
        note("searcher", f"検索結果 {len(hits)} 件")
        return hits[: settings.max_candidates]

    since = datetime.now(timezone.utc) - timedelta(days=settings.search_recency_days)
    for query in queries:
        if trajectory is not None:
            trajectory.record("search_with_grounding", query)
    # 検索は互いに独立なので並列に投げる（1回 10〜30 秒かかる）
    results = await asyncio.gather(
        *(
            # 半年より古いページは今年の告知ではない。まとめ記事の基盤は検索段階で外す
            gemini_client.search_with_grounding(query, since=since, exclude_domains=ARTICLE_HOSTS)
            for query in queries
        )
    )
    for query, raws in zip(queries, results):
        found = 0
        for raw in raws:
            url = raw.get("url", "")
            if url and url not in seen:
                seen.add(url)
                found += 1
                hits.append(
                    SearchHit(
                        url=url,
                        title=raw.get("title", ""),
                        excerpt=raw.get("excerpt", ""),
                        query=query,
                    )
                )
        note("searcher", f"「{query}」を検索 → 新規 {found} 件")
    note("searcher", f"検索結果 {len(hits)} 件")
    return hits[: settings.max_candidates]


async def _fetch_step(
    hits: list[SearchHit],
    trajectory: ToolTrajectory | None = None,
    note: Note = _noop_note,
) -> tuple[list[FetchedPage], list[str]]:
    """Fetch each hit. Rejected URLs are reported, not raised (§9.1 候補単位)."""
    pages: list[FetchedPage] = []
    rejected: list[str] = []
    # 直列だと候補30件 × タイムアウト10秒で数分かかる。同時数を絞って並列に取る
    semaphore = asyncio.Semaphore(settings.fetch_concurrency)

    async def fetch_one(hit: SearchHit):
        async with semaphore:
            return await page_fetcher.fetch(hit.url, trajectory)

    results = await asyncio.gather(*(fetch_one(hit) for hit in hits[: settings.max_candidates]))
    for hit, result in zip(hits, results):
        if isinstance(result, FetchedPage):
            _note_injection_attempt(result, trajectory)
            pages.append(result)
            note("searcher", f"ページ取得: {_host(result.final_url)}")
        else:
            rejected.append(f"{result.reason}:{hit.url}")
            note("searcher", f"取得を見送り（{result.reason}）: {_host(hit.url)}", level="warn")
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

    def note(agent: str, message: str, *, level: str = "info") -> None:
        """UI の「エージェントの動き」に出す1行。行ごとに保存し、ポーリングで追える。"""
        run.log(agent, message, level=level)  # type: ignore[arg-type]
        store.update_run(run)

    try:
        await _set_step(run, "normalize")
        await asyncio.sleep(delay)
        normalized = _normalize_preferences(preferences)
        note(
            "planner",
            "関心条件を整理: "
            f"{normalized.interests_prompt} / {'・'.join(normalized.locations) or '地域指定なし'}"
            f" / {normalized.target_year}年 / オンライン{'可' if normalized.online_allowed else '不可'}",
        )

        await _set_step(run, "plan")
        await asyncio.sleep(delay)
        queries = _plan_queries(normalized)
        note("planner", f"検索クエリを {len(queries)} 件作成")
        for query in queries:
            note("planner", f"クエリ: {query}")

        await _set_step(run, "search")
        hits = await _search_step(queries, trajectory, note)

        pages, fetch_rejected = await _fetch_step(hits, trajectory, note)
        # まとめ記事やブログは告知ページではない。記事中の日付を開催日にしない
        articles = [p for p in pages if is_article_host(p.final_url)]
        pages = [p for p in pages if not is_article_host(p.final_url)]
        fetch_rejected.extend(f"article-host:{p.final_url}" for p in articles)
        for article in articles:
            note("searcher", f"記事サイトのため対象外: {_host(article.final_url)}", level="warn")

        await _set_step(run, "extract_validate")
        await asyncio.sleep(delay)
        hits_by_url = {hit.url: hit for hit in hits}
        source_types = {
            url: source_type_for(url, DEMO_PAGE_SOURCES)
            for page in pages
            for url in (page.final_url, page.requested_url)
        }
        candidates = extract_candidates(
            pages,
            hits=hits_by_url,
            run_id=run.run_id,
            now=now,
            user_id=run.user_id,
            source_types=source_types,
        )
        if trajectory is not None:
            for candidate in candidates:
                trajectory.record("extract", candidate.event.official_url)

        note("extractor", f"{len(pages)} ページから {len(candidates)} 件の候補を行ラベルで抽出")

        # 行ラベルで開催日が取れなかったページは、モデルに該当行を引用させてから
        # 同じパーサで読む（extraction/model_locator）。デモモードでは呼ばれない。
        if not gemini_client.demo_mode:
            extracted_urls = {c.event.official_url for c in candidates}
            leftover = [p for p in pages if p.final_url not in extracted_urls]
            semaphore = asyncio.Semaphore(settings.locate_concurrency)

            async def locate(page: FetchedPage):
                async with semaphore:
                    return await extract_with_model(
                        page,
                        hit=hits_by_url.get(page.requested_url) or hits_by_url.get(page.final_url),
                        run_id=run.run_id,
                        now=now,
                        user_id=run.user_id,
                        source_type=source_types.get(page.final_url, "other"),
                    )

            if leftover:
                note("extractor", f"{len(leftover)} ページはモデルに該当行の引用を依頼")
            for page, located in zip(leftover, await asyncio.gather(*(locate(p) for p in leftover))):
                if trajectory is not None:
                    trajectory.record(
                        "locate_with_model", page.final_url, outcome="ok" if located else "none"
                    )
                if located is not None:
                    candidates.append(located)
                    note("extractor", f"引用から日程を確認: {_host(page.final_url)}")
                else:
                    note("extractor", f"日程を特定できず: {_host(page.final_url)}", level="warn")

        # 抽出が0件のときだけデモカタログで補う。実運用では抽出結果を使う。
        if not candidates and settings.demo_catalog_fallback:
            candidates = _filter_catalog(normalized)
            note("extractor", f"抽出 0 件のためデモカタログ {len(candidates)} 件で補完", level="warn")

        buckets = _validate(
            candidates, run.run_id, now=now, target_year=normalized.target_year
        )
        note(
            "extractor",
            f"日程を検証: 確認済み {len(buckets.verified)} / 要確認 {len(buckets.partial)}"
            f" / 保留 {len(buckets.quarantined)} / 除外 {len(buckets.rejected)}",
        )

        await _set_step(run, "dedupe")
        await asyncio.sleep(delay)
        events, duplicate_count = _dedupe(buckets.displayable())
        note("organizer", f"重複 {duplicate_count} 件を統合 → {len(events)} 件")

        await _set_step(run, "rank")
        events = _rank(events, normalized, run_id=run.run_id, now=now)
        note("organizer", "関心との適合でおすすめ順に並べ替え")

        await _set_step(run, "save")
        store.save_events(run.run_id, events)
        note("organizer", f"{len(events)} 件を保存")
        # 収集したイベントをボット投稿としてフィードへ流す（F-06）。失敗しても
        # Run 自体は成功で、フィードが埋まらないだけ。
        try:
            seeded = seed_bot_posts(events, now=now)
            note("organizer", f"フィードへ {len(seeded)} 件を投稿")
        except Exception:  # noqa: BLE001
            logger.exception("bot seeding failed for run %s", run.run_id)
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
        run.log("organizer", "エラーで中断しました", level="warn")
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
