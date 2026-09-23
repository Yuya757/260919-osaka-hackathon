"""Deterministic recommendation score (§6.8)."""

from __future__ import annotations

import re
from datetime import datetime
from urllib.parse import urlsplit

from event_agent.domain.confidence import required_evidence_fields
from event_agent.domain.regions import in_locations
from event_agent.schemas import ApiEvent, Evidence, UserPreferences


def score_recommendation(
    event: ApiEvent,
    evidence: list[Evidence],
    preferences: UserPreferences,
    *,
    now: datetime,
) -> int:
    """§6.8 の決定論的スコア（100点満点）。

    配点は要件どおり 関心40 / 地域・オンライン20 / 締切までの余裕15 /
    公式性・根拠品質15 / 情報完全性10。モデルはこの値を変更しない。
    """
    text = " ".join(
        [
            event.title,
            event.summary or "",
            event.category,
            event.location.region or "",
            event.location.venue or "",
        ]
    ).casefold()

    # 関心キーワード・カテゴリ適合: 40
    tokens = [t for t in re.split(r"[\s、,/]+", preferences.interests_prompt.casefold()) if t]
    matched = sum(1 for token in tokens if token in text)
    keyword_points = 30.0 * (matched / len(tokens)) if tokens else 0.0
    category_points = 10.0 if any(token in event.category.casefold() for token in tokens) else 0.0
    score = min(40.0, keyword_points + category_points)

    # 地域・オンライン条件適合: 20
    region = (event.location.region or "") + (event.location.venue or "")
    region_match = in_locations(region, preferences.locations)
    if region_match:
        score += 20
    elif preferences.online_allowed and event.location.type in {"online", "hybrid"}:
        score += 14
    elif event.location.type == "online":
        score += 10

    # 締切までの余裕: 15
    deadline = event.dates.application_deadline
    if deadline is None:
        score += 5  # 不明。満点にも0点にもしない
    else:
        days = (deadline - now).days
        if days >= 14:
            score += 15
        elif days >= 7:
            score += 12
        elif days >= 3:
            score += 8
        elif days >= 1:
            score += 4

    # 公式性・根拠品質: 15
    source_types = {e.source_type for e in evidence}
    if source_types & {"official", "organizer"}:
        score += 9
    elif "aggregator" in source_types:
        score += 3
    hosts = {urlsplit(e.canonical_url or e.source_url).netloc.casefold() for e in evidence}
    if len(hosts) >= 2:
        score += 3
    supported: set[str] = set()
    for item in evidence:
        supported.update(item.supports)
    if all(f in supported for f in required_evidence_fields(event.dates.event_start is not None)):
        score += 3

    # 情報完全性: 10
    for present in (
        event.dates.application_deadline is not None,
        event.dates.event_end is not None,
        bool(event.organizer),
        bool(event.location.venue or event.location.region),
        bool(event.application_url),
    ):
        if present:
            score += 2

    return max(0, min(100, round(score)))
