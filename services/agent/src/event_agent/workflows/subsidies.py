"""補助金を jGrants の公開 API から作る（ジャンル拡張計画 段階4）。

他のジャンルは「検索 → 取得 → 本文から抽出」だが、補助金は構造化データが
そのまま貰えるので、抽出もモデル呼び出しも要らない。ここがやるのは写し替えだけで、
検証・重複判定・保存は他のジャンルと同じ経路に乗せる。

補助金に実施日（会場に集まる日）は無い。2 軸のうち実施日は null のまま、
公募終了日時を申込締切に入れる。事業実施期間や補助率は `attributes` に持つ。
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from event_agent.clients.jgrants import (
    JGrantsClient,
    SubsidyDetail,
    SubsidyListing,
    SubsidySource,
    public_page_url,
)
from event_agent.schemas import (
    ApiEvent,
    EventDates,
    EventLocation,
    EventMilestone,
    Evidence,
    SYSTEM_USER_ID,
)
from event_agent.security import prompt_guard

JST = timezone(timedelta(hours=9))

# 補助金の掲載は jGrants 自体が一次情報なので official 扱い
SOURCE_TYPE = "official"


def _event_id(subsidy_id: str) -> str:
    return hashlib.sha256(f"jgrants:{subsidy_id}".encode()).hexdigest()[:16]


def _clean(value: str | None, *, max_chars: int = 60) -> str | None:
    """外部入力なので素通しにしない（§10.1）。空になったら持たない。"""
    if not value:
        return None
    cleaned = prompt_guard.sanitize_free_text(value, fallback="", max_chars=max_chars)
    return cleaned or None


def _attributes(listing: SubsidyListing, detail: SubsidyDetail | None) -> dict[str, str]:
    """補助金固有の値。API の値をそのまま持ち、換算も丸めもしない。"""
    found: dict[str, str] = {}
    rate = _clean(detail.subsidy_rate if detail else None)
    if rate:
        found["補助率"] = rate
    if listing.max_limit:
        found["上限額"] = f"{listing.max_limit:,}円"
    area = _clean(listing.target_area or (detail.target_area if detail else None))
    if area:
        found["対象地域"] = area
    employees = _clean(listing.target_employees)
    if employees:
        found["従業員数"] = employees
    purpose = _clean(detail.use_purpose if detail else None)
    if purpose:
        found["利用目的"] = purpose
    industry = _clean(detail.industry if detail else None)
    if industry:
        found["対象業種"] = industry
    if listing.acceptance_start:
        found["受付開始"] = listing.acceptance_start.strftime("%Y年%m月%d日")
    return found


def _evidence(
    listing: SubsidyListing, url: str, *, now: datetime
) -> list[Evidence]:
    """根拠は API が返した値そのもの。引用元は jGrants の公開ページ。

    ページ本文の引用ではないので、抜粋には項目名と値を書く。どこから来た値かを
    あとから突き合わせられる形にしておく（§7.2）。
    """
    records = [
        Evidence(
            evidenceId=f"jg-{listing.subsidy_id}-title",
            sourceUrl=url,
            sourceType=SOURCE_TYPE,
            title=listing.title[:200],
            excerpt=f"title: {listing.title}"[:500],
            supports=["title"],
            retrievedAt=now,
        )
    ]
    if listing.acceptance_end:
        records.append(
            Evidence(
                evidenceId=f"jg-{listing.subsidy_id}-deadline",
                sourceUrl=url,
                sourceType=SOURCE_TYPE,
                title=listing.title[:200],
                excerpt=(
                    "acceptance_end_datetime: "
                    f"{listing.acceptance_end.isoformat()}"
                )[:500],
                supports=["dates.applicationDeadline"],
                retrievedAt=now,
            )
        )
    return records


def event_from_subsidy(
    listing: SubsidyListing,
    detail: SubsidyDetail | None,
    *,
    now: datetime,
    run_id: str,
    theme_id: str | None = None,
) -> tuple[ApiEvent, list[Evidence]] | None:
    """一覧 1 件を Event に写す。締切が読めないものは載せない。

    締切も実施日も無い補助金は、このプロダクトで見せる意味が無い（§6.6 の
    「推測しない」に従い、無い締切を作らない）。
    """
    if listing.acceptance_end is None:
        return None
    title = _clean(listing.title, max_chars=200)
    if not title:
        return None
    url = public_page_url(detail, listing.subsidy_id)
    organizer = _clean(listing.institution or (detail.institution if detail else None), max_chars=120)
    area = _clean(listing.target_area, max_chars=60)

    milestones = []
    if listing.acceptance_start:
        milestones.append(
            EventMilestone(label="受付開始", at=listing.acceptance_start, precision="date")
        )

    event = ApiEvent(
        eventId=_event_id(listing.subsidy_id),
        userId=SYSTEM_USER_ID,
        title=title,
        organizer=organizer,
        category="subsidy",
        kind="subsidy",
        summary=_clean(listing.name, max_chars=200) or "",
        location=EventLocation(type="unknown", region=area),
        dates=EventDates(
            applicationDeadline=listing.acceptance_end,
            applicationDeadlinePrecision="datetime",
            eventStart=None,
            milestones=milestones,
        ),
        attributes=_attributes(listing, detail),
        officialUrl=url,
        applicationUrl=url,
        firstSeenAt=now,
        lastSeenAt=now,
        lastExtractedAt=now,
        sourceRunId=run_id,
        themeId=theme_id,
        source="jGrants（デジタル庁）",
    )
    return event, _evidence(listing, url, now=now)


# ------------------------------------------------------- 収集（テーマ Run から）


@dataclass
class SubsidyCandidate:
    """`_validate` に渡す形。ページ抽出の候補と同じ顔をしていればよい。"""

    event: ApiEvent
    evidence: list[Evidence]
    headline_kind: str | None = "subsidy"


def _matches_area(listing: SubsidyListing, areas: tuple[str, ...]) -> bool:
    if not areas:
        return True
    area = listing.target_area or ""
    return any(word in area for word in areas)


async def collect_subsidies(
    theme,
    *,
    run_id: str,
    now: datetime,
    source: "SubsidySource | None" = None,
    detail_limit: int = 20,
) -> tuple[list[SubsidyCandidate], int]:
    """テーマのキーワードで公募中の補助金を集める。戻り値は候補と API 呼び出し数。

    詳細 API は公開ページ URL と補助率を持っているので呼びたいが、レート制限が
    あるので件数に上限を置く。詳細が取れなかったものは一覧の値だけで載せる。
    """
    client = source or subsidy_source()
    found: dict[str, SubsidyListing] = {}
    calls = 0
    for keyword in theme.keywords:
        listings = await client.search(keyword)
        calls += 1
        for listing in listings:
            if listing.subsidy_id in found or not _matches_area(listing, theme.target_areas):
                continue
            if listing.acceptance_end is None or listing.acceptance_end < now:
                continue
            found[listing.subsidy_id] = listing

    # 締切が近いものから詳細を取る。上限に当たっても締切の近いものは詳細付きになる
    ordered = sorted(found.values(), key=lambda item: (item.acceptance_end, item.subsidy_id))
    candidates: list[SubsidyCandidate] = []
    for index, listing in enumerate(ordered):
        detail = None
        if index < detail_limit:
            detail = await client.detail(listing.subsidy_id)
            calls += 1
        mapped = event_from_subsidy(
            listing, detail, now=now, run_id=run_id, theme_id=theme.id
        )
        if mapped is None:
            continue
        event, evidence = mapped
        candidates.append(SubsidyCandidate(event=event, evidence=evidence))
    return candidates, calls


_source: "SubsidySource | None" = None


def set_subsidy_source(source: "SubsidySource | None") -> None:
    """テストとデモで差し替える。"""
    global _source
    _source = source


def subsidy_source() -> "SubsidySource":
    """本番は jGrants、それ以外は固定のデモデータ（ネットワークに出ない）。"""
    global _source
    if _source is None:
        from event_agent.config import settings

        if settings.use_vertex:
            _source = JGrantsClient()
        else:
            from event_agent.demo.subsidies import DemoSubsidySource

            _source = DemoSubsidySource()
    return _source
