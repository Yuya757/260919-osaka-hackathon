"""技術イベントを Doorkeeper の公開 API から作る（ADR-012）。

補助金（workflows/subsidies.py）と同じく、構造化データをそのまま貰うので
抽出もモデル呼び出しも要らない。ここがやるのは写し替えだけで、検証・重複判定・
保存は他のジャンルと同じ経路に乗せる。

申込締切にあたる項目は API に無い。締切は推測せず null のまま持つ（§6.5）。
検証の規則はそのままなので、締切が分からない技術イベントは ``partial`` になる。
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from event_agent.clients.doorkeeper import (
    PAGE_SIZE,
    DoorkeeperClient,
    MeetupListing,
    MeetupSource,
)
from event_agent.domain.regions import prefecture_of
from event_agent.schemas import ApiEvent, EventDates, EventLocation, Evidence, SYSTEM_USER_ID
from event_agent.security import prompt_guard

JST = timezone(timedelta(hours=9))

# Doorkeeper のイベントページは主催者が自分で書いて公開するページ。
# 集約サイトの転載ではないので organizer 扱いにする（ADR-012）
SOURCE_TYPE = "organizer"

# 会場欄や住所にこれがあればオンライン配信がある
_ONLINE_WORDS = ("オンライン", "online", "zoom", "youtube", "teams", "google meet", "discord", "配信")
_TAGS = re.compile(r"<[^>]+>")

# タイトル → 表示用の細分。どれにも当たらなければ meetup
_CATEGORY_WORDS = (
    ("conference", ("カンファレンス", "conference", "summit", "サミット")),
    ("workshop", ("ハンズオン", "ワークショップ", "workshop", "hands-on")),
    ("meetup", ("勉強会", "もくもく", "lt", "meetup", "ミートアップ")),
)


def _event_id(event_id: str) -> str:
    return hashlib.sha256(f"doorkeeper:{event_id}".encode()).hexdigest()[:16]


def _clean(value: str | None, *, max_chars: int = 60) -> str | None:
    """外部入力なので素通しにしない（§10.1）。空になったら持たない。"""
    if not value:
        return None
    cleaned = prompt_guard.sanitize_free_text(value, fallback="", max_chars=max_chars)
    return cleaned or None


def _category(title: str) -> str:
    lowered = title.casefold()
    for category, words in _CATEGORY_WORDS:
        if any(word in lowered for word in words):
            return category
    return "meetup"


def _location(listing: MeetupListing) -> EventLocation:
    """会場欄と住所から開催形式を決める。どちらも無ければ unknown（推測しない）。"""
    venue = _clean(listing.venue_name, max_chars=120)
    address = _clean(listing.address, max_chars=120)
    text = f"{venue or ''} {address or ''}".casefold()
    online = any(word in text for word in _ONLINE_WORDS)
    if address and online:
        kind = "hybrid"
    elif address:
        kind = "offline"
    elif online:
        kind = "online"
    else:
        kind = "unknown"
    region = prefecture_of(address) or (address[:60] if address else None)
    return EventLocation(type=kind, venue=venue, region=region)


def _attributes(listing: MeetupListing) -> dict[str, str]:
    found: dict[str, str] = {}
    if listing.ticket_limit:
        found["定員"] = f"{listing.ticket_limit}人"
    if listing.participants is not None:
        found["参加登録"] = f"{listing.participants}人"
    address = _clean(listing.address, max_chars=120)
    if address:
        found["住所"] = address
    return found


def _evidence(listing: MeetupListing, *, now: datetime) -> list[Evidence]:
    """根拠は API が返した値そのもの。引用元は Doorkeeper のイベントページ。

    ページ本文の引用ではないので、抜粋には項目名と値を書く（§7.2）。
    """
    url = listing.public_url
    records = [
        Evidence(
            evidenceId=f"dk-{listing.event_id}-title",
            sourceUrl=url,
            sourceType=SOURCE_TYPE,
            title=listing.title[:200],
            excerpt=f"title: {listing.title}"[:500],
            supports=["title"],
            retrievedAt=now,
        )
    ]
    if listing.starts_at:
        supports = ["dates.eventStart"] + (["dates.eventEnd"] if listing.ends_at else [])
        excerpt = f"starts_at: {listing.starts_at.isoformat()}"
        if listing.ends_at:
            excerpt += f" / ends_at: {listing.ends_at.isoformat()}"
        records.append(
            Evidence(
                evidenceId=f"dk-{listing.event_id}-dates",
                sourceUrl=url,
                sourceType=SOURCE_TYPE,
                title=listing.title[:200],
                excerpt=excerpt[:500],
                supports=supports,  # type: ignore[arg-type]
                retrievedAt=now,
            )
        )
    if listing.venue_name or listing.address:
        records.append(
            Evidence(
                evidenceId=f"dk-{listing.event_id}-location",
                sourceUrl=url,
                sourceType=SOURCE_TYPE,
                title=listing.title[:200],
                excerpt=(
                    f"venue_name: {listing.venue_name or ''} / address: {listing.address or ''}"
                )[:500],
                supports=["location"],
                retrievedAt=now,
            )
        )
    return records


def event_from_meetup(
    listing: MeetupListing, *, now: datetime, run_id: str, theme_id: str | None = None
) -> tuple[ApiEvent, list[Evidence]] | None:
    """一覧 1 件を Event に写す。開催日時が読めないものは載せない。

    技術イベントは開催日が主軸で、申込締切は API に無い。開催日も無ければ
    このプロダクトで見せる意味が無い。
    """
    if listing.starts_at is None:
        return None
    title = _clean(listing.title, max_chars=200)
    if not title:
        return None
    description = _TAGS.sub(" ", listing.description or "")
    ends_at = listing.ends_at if listing.ends_at and listing.ends_at >= listing.starts_at else None
    event = ApiEvent(
        eventId=_event_id(listing.event_id),
        userId=SYSTEM_USER_ID,
        title=title,
        organizer=_clean(listing.group_name, max_chars=120),
        category=_category(title),
        kind="meetup",
        summary=_clean(description, max_chars=200) or "",
        location=_location(listing),
        dates=EventDates(
            applicationDeadline=None,
            eventStart=listing.starts_at,
            eventStartPrecision="datetime",
            eventEnd=ends_at,
        ),
        attributes=_attributes(listing),
        officialUrl=listing.public_url,
        applicationUrl=listing.public_url,
        firstSeenAt=now,
        lastSeenAt=now,
        lastExtractedAt=now,
        sourceRunId=run_id,
        themeId=theme_id,
        source="Doorkeeper",
    )
    return event, _evidence(listing, now=now)


# ------------------------------------------------------- 収集（テーマ Run から）


@dataclass
class MeetupCandidate:
    """`_validate` に渡す形。ページ抽出の候補と同じ顔をしていればよい。"""

    event: ApiEvent
    evidence: list[Evidence]
    headline_kind: str | None = "meetup"


async def collect_meetups(
    theme,
    *,
    run_id: str,
    now: datetime,
    source: MeetupSource | None = None,
    window_days: int = 45,
    pages: int = 3,
) -> tuple[list[MeetupCandidate], int]:
    """テーマのキーワードで、これから始まる技術イベントを集める。戻り値は候補と API 呼び出し数。

    キーワードごとに開催日順で ``pages`` ページまで引く。同じイベントは 1 件にまとめる。
    """
    client = source or meetup_source()
    today = now.astimezone(JST).date()
    until = today + timedelta(days=window_days)
    found: dict[str, MeetupListing] = {}
    calls = 0
    for keyword in theme.keywords:
        for page in range(1, pages + 1):
            listings = await client.search(keyword, since=today, until=until, page=page)
            calls += 1
            for listing in listings:
                if listing.starts_at is None or listing.starts_at < now:
                    continue
                found.setdefault(listing.event_id, listing)
            if len(listings) < PAGE_SIZE:
                break

    candidates: list[MeetupCandidate] = []
    for listing in sorted(found.values(), key=lambda item: (item.starts_at, item.event_id)):
        mapped = event_from_meetup(listing, now=now, run_id=run_id, theme_id=theme.id)
        if mapped is None:
            continue
        event, evidence = mapped
        candidates.append(MeetupCandidate(event=event, evidence=evidence))
    return candidates, calls


_source: MeetupSource | None = None


def set_meetup_source(source: MeetupSource | None) -> None:
    """テストとデモで差し替える。"""
    global _source
    _source = source


def meetup_source() -> MeetupSource:
    """本番は Doorkeeper、それ以外は固定のデモデータ（ネットワークに出ない）。"""
    global _source
    if _source is None:
        from event_agent.config import settings

        if settings.use_vertex:
            _source = DoorkeeperClient()
        else:
            from event_agent.demo.meetups import DemoMeetupSource

            _source = DemoMeetupSource()
    return _source
