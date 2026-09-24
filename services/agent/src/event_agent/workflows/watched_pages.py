"""利用者がイベントのページを登録し、エージェントが毎朝見守る（ADR-014）。

検索グラウンディングの結果のリンクから読むページを決めることは規約で禁じられて
いるが、利用者が自分で貼った URL はその対象ではない。登録されたページは、収集と
同じ「ページを読む → 行を引用 → 日付を解析 → 検証 → 重複統合 → 保存」に乗せる。

- https だけ。宛先は収集と同じ SSRF 対策（page_fetcher）を通る
- robots.txt で断られているサイトは読まない
- 回数を抑える: 1 セッション 10 件/日、全体 200 件/日
- 毎朝、内容が変わったページだけ読み直す。3 回続けて読めなければ見守りを止める
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit

from event_agent.clients import robots
from event_agent.clients.page_fetcher import FetchedPage, page_fetcher
from event_agent.config import settings
from event_agent.domain.normalize import normalize_url
from event_agent.schemas import (
    SYSTEM_USER_ID,
    ApiEvent,
    RunActivity,
    WatchedPage,
    WatchedPageResponse,
)
from event_agent.security.url_guard import UnsafeUrl, check_hostname, classify_address
from event_agent.storage.store import store
from event_agent.workflows.collect import (
    _new_run,
    execute_collect_workflow,
    scheduled_idempotency_key,
)
from event_agent.workflows.pool import invalidate_pool_cache
from event_agent.workflows.themes import WATCHED_THEME, CollectionTheme

JST = timezone(timedelta(hours=9))
PER_SESSION_DAILY = 10
GLOBAL_DAILY = 200
WATCH_LIMIT = 100
MAX_FAILURES = 3

# 登録のときだけ使うテーマ。毎朝の見守りは WATCHED_THEME
REGISTER_THEME = CollectionTheme(
    "user-registered", "利用者が登録したページ", ("全国",),
    kind="hackathon", allowed_kinds=WATCHED_THEME.allowed_kinds, source="watched",
)

MESSAGES = {
    "added": "ページを読んで、一覧に追加しました。これから毎朝見直します。",
    "exists": "このページはすでに登録されています。",
    "bad_url": "https:// で始まるイベントのページの URL を入れてください。",
    "quota": "今日の登録の回数を使い切りました。明日またお試しください。",
    "robots": "このサイトは自動での読み取りを断っているため、登録できません。",
    "unavailable": "ページを読めませんでした。URL を確かめて、時間をおいてお試しください。",
    "no_event": "開催日を読み取れなかったか、すでに終わったイベントのため、一覧に追加できませんでした。",
}

Note = Callable[[str, str, str], None]


def watch_id_for(url: str) -> str:
    return hashlib.sha256(normalize_url(url).encode("utf-8")).hexdigest()[:24]


def _check_url(url: str) -> str | None:
    """形と宛先だけを見る（取得は page_fetcher が改めて SSRF を検査する）。"""
    parts = urlsplit(url.strip())
    if parts.scheme.casefold() != "https":
        return None
    host = (parts.hostname or "").strip().rstrip(".")
    try:
        check_hostname(host)
    except UnsafeUrl:
        return None
    if classify_address(host) not in (None, "not-an-ip"):
        return None
    return url.strip()


def _reject(reason: str, activity: list[RunActivity]) -> WatchedPageResponse:
    return WatchedPageResponse(status="rejected", reason=reason, message=MESSAGES[reason], activity=activity)


async def _read(url: str, note: Note) -> FetchedPage | str:
    """robots.txt を確かめてから読む。読めなければ理由（MESSAGES のキー）。"""
    if not await robots.allowed(url):
        note("searcher", f"robots.txt で断られているため読みません: {urlsplit(url).hostname}", "warn")
        return "robots"
    page = await page_fetcher.fetch(url)
    if not isinstance(page, FetchedPage):
        note("searcher", f"ページを読めませんでした: {urlsplit(url).hostname}", "warn")
        return "unavailable"
    note("searcher", f"ページを読みました: {urlsplit(page.final_url).hostname}", "info")
    return page


def _saved_event(run_id: str, page: FetchedPage) -> ApiEvent | None:
    """この Run で保存された、そのページのイベント。"""
    events = [e for e in store.list_events(run_id) if e.validation_status in ("verified", "partial")]
    wanted = {normalize_url(page.final_url), normalize_url(page.requested_url)}
    return next((e for e in events if e.normalized_official_url in wanted), events[0] if events else None)


async def register_page(
    url: str,
    session_id: str,
    *,
    now: datetime | None = None,
    on_note: Note | None = None,
) -> WatchedPageResponse:
    now = now or datetime.now(timezone.utc)
    activity: list[RunActivity] = []

    def note(agent: str, message: str, level: str = "info") -> None:
        activity.append(RunActivity(agent=agent, message=message[:300], level=level, at=datetime.now(timezone.utc)))  # type: ignore[arg-type]
        if on_note:
            on_note(agent, message, level)

    checked = _check_url(url)
    if checked is None:
        return _reject("bad_url", activity)
    watch_id = watch_id_for(checked)
    existing = store.get_watched_page(watch_id)
    if existing is not None:
        event = store.get_event(existing.event_id) if existing.event_id else None
        return WatchedPageResponse(status="exists", message=MESSAGES["exists"], event=event, activity=activity)

    day = now.astimezone(JST).date().isoformat()
    if not store.reserve_quota(f"watch:{day}:{session_id}", cap=PER_SESSION_DAILY) or not store.reserve_quota(
        f"watch:{day}:all", cap=GLOBAL_DAILY
    ):
        return _reject("quota", activity)

    note("planner", "登録されたページを読みに行きます", "info")
    page = await _read(checked, note)
    if isinstance(page, str):
        return _reject(page, activity)

    run = _new_run(None, trigger_type="manual", user_id=SYSTEM_USER_ID, theme_id=REGISTER_THEME.id)
    store.create_run(run)

    def forward(agent: str, message: str, level: str) -> None:
        note(agent, message, level)

    await execute_collect_workflow(
        run.run_id,
        REGISTER_THEME.preferences(now=now),
        now=now,
        theme=REGISTER_THEME,
        seed_pages=[page],
        on_note=forward,
    )
    event = _saved_event(run.run_id, page)
    if event is None:
        return _reject("no_event", activity)

    store.save_watched_page(
        WatchedPage(
            watchId=watch_id,
            url=checked,
            normalizedUrl=normalize_url(checked),
            eventId=event.event_id,
            contentHash=page.content_hash,
            addedAt=now,
            lastCheckedAt=now,
        )
    )
    invalidate_pool_cache()
    return WatchedPageResponse(status="added", message=MESSAGES["added"], event=event, activity=activity)


async def watch_all(*, now: datetime | None = None, limit: int = WATCH_LIMIT) -> tuple[int, int, bool]:
    """毎朝の見守り。戻り値は（読み直した件数, 変わらなかった件数, 走ったか）。

    同じ JST 日に二度は走らない（定期収集と同じ冪等キー、§9.3）。
    """
    now = now or datetime.now(timezone.utc)
    key = scheduled_idempotency_key(
        f"theme:{WATCHED_THEME.id}", now=now, schedule_version=settings.run_schedule_version
    )
    run = _new_run(key, trigger_type="scheduled", user_id=SYSTEM_USER_ID, theme_id=WATCHED_THEME.id)
    if store.create_run(run).run_id != run.run_id:
        return 0, 0, False

    changed: list[FetchedPage] = []
    unchanged: list[str] = []
    watched = store.list_watched_pages(limit=limit)
    by_page: dict[str, WatchedPage] = {}

    def quiet(agent: str, message: str, level: str = "info") -> None:
        run.log(agent, message, level=level)  # type: ignore[arg-type]

    for item in watched:
        page = await _read(item.url, quiet)
        if isinstance(page, str):
            failures = item.failures + 1
            store.save_watched_page(
                item.model_copy(
                    update={"failures": failures, "active": failures < MAX_FAILURES, "last_checked_at": now}
                )
            )
            continue
        if item.content_hash == page.content_hash:
            if item.event_id:
                unchanged.append(item.event_id)
            store.save_watched_page(item.model_copy(update={"failures": 0, "last_checked_at": now}))
            continue
        changed.append(page)
        by_page[page.requested_url] = item

    # 内容が変わらなかったページは、見た印（lastSeenAt）だけ進める
    if unchanged:
        keys = [e.dedup_key for e in (store.get_event(i) for i in unchanged) if e is not None]
        store.touch_events(keys, last_seen_at=now)
    store.update_run(run)

    if changed:
        await execute_collect_workflow(
            run.run_id, WATCHED_THEME.preferences(now=now), now=now, theme=WATCHED_THEME, seed_pages=changed
        )
        for page in changed:
            item = by_page[page.requested_url]
            event = _saved_event_for_page(run.run_id, page)
            store.save_watched_page(
                item.model_copy(
                    update={
                        "content_hash": page.content_hash,
                        "event_id": event.event_id if event else item.event_id,
                        "failures": 0,
                        "last_checked_at": now,
                    }
                )
            )
    else:
        run.status = "succeeded"
        run.current_step = "completed"
        run.completed_at = datetime.now(timezone.utc)
        store.update_run(run)
    invalidate_pool_cache()
    return len(changed), len(unchanged), True


def _saved_event_for_page(run_id: str, page: FetchedPage) -> ApiEvent | None:
    wanted = {normalize_url(page.final_url), normalize_url(page.requested_url)}
    return next(
        (e for e in store.list_events(run_id) if e.normalized_official_url in wanted),
        None,
    )
