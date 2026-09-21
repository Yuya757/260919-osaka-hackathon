"""Duplicate detection and merging (§6.7)."""

from __future__ import annotations

from typing import Iterator

from event_agent.domain.normalize import (
    normalize_title,
    normalize_url,
    title_similarity,
)
from event_agent.schemas import ApiEvent


def _pairs(items: list[ApiEvent]) -> Iterator[tuple[ApiEvent, ApiEvent]]:
    for i in range(len(items)):
        for j in range(i + 1, len(items)):
            yield items[i], items[j]


def _root(parent: dict[str, str], key: str) -> str:
    while parent[key] != key:
        parent[key] = parent[parent[key]]
        key = parent[key]
    return key


def _union(parent: dict[str, str], a: str, b: str) -> None:
    ra, rb = _root(parent, a), _root(parent, b)
    if ra != rb:
        parent[rb] = ra


def group_duplicates(
    events: list[ApiEvent],
    *,
    similarity_threshold: float,
    date_window_days: int = 7,
) -> list[list[ApiEvent]]:
    """Group duplicate events using the §6.7 priority order.

    1. normalized official URL
    2. normalized application URL
    3. (normalized title, start date, organizer)
    4. title similarity above the threshold AND same start date AND same region

    A fifth rule handles sources that disagree about the date. §6.7's「重複時」
    block requires that「開催日変更は履歴を残し、無条件で上書きしない」, which
    only has meaning if two records of one event can carry different dates — so
    the priority-4 comparison is also run over a small date window when the
    title, region and organizer all agree. The window keeps it conservative:
    the 2026 and 2027 editions of a series are a year apart, and a spring and
    autumn edition are months apart, so both stay separate.
    """
    if not events:
        return []

    parent = {event.event_id: event.event_id for event in events}
    by_official: dict[str, str] = {}
    by_application: dict[str, str] = {}
    by_triple: dict[tuple[str, str, str], str] = {}
    buckets: dict[str, list[ApiEvent]] = {}

    for event in events:
        key = normalize_url(event.official_url)
        if key in by_official:
            _union(parent, by_official[key], event.event_id)
        else:
            by_official[key] = event.event_id

        if event.application_url:
            akey = normalize_url(event.application_url)
            if akey in by_application:
                _union(parent, by_application[akey], event.event_id)
            else:
                by_application[akey] = event.event_id

        start = event.dates.event_start.date().isoformat()
        triple = (event.normalized_title, start, normalize_title(event.organizer or ""))
        if triple in by_triple:
            _union(parent, by_triple[triple], event.event_id)
        else:
            by_triple[triple] = event.event_id

        buckets.setdefault(start, []).append(event)

    def _same_region(left: ApiEvent, right: ApiEvent) -> bool:
        return (left.location.region or "").casefold() == (
            right.location.region or ""
        ).casefold()

    def _compatible_organizer(left: ApiEvent, right: ApiEvent) -> bool:
        lorg = normalize_title(left.organizer or "")
        rorg = normalize_title(right.organizer or "")
        return not lorg or not rorg or lorg == rorg

    # 優先度4: 同一開催日・同一地域
    for bucket in buckets.values():
        for left, right in _pairs(bucket):
            if not _same_region(left, right):
                continue
            if (
                title_similarity(left.normalized_title, right.normalized_title)
                >= similarity_threshold
            ):
                _union(parent, left.event_id, right.event_id)

    # 日付が食い違うソース同士。主催者まで一致し、日付差が窓内のときだけ併合する。
    if date_window_days > 0:
        for left, right in _pairs(events):
            if _root(parent, left.event_id) == _root(parent, right.event_id):
                continue
            if not _same_region(left, right) or not _compatible_organizer(left, right):
                continue
            gap = abs(
                (left.dates.event_start.date() - right.dates.event_start.date()).days
            )
            if 0 < gap <= date_window_days and (
                title_similarity(left.normalized_title, right.normalized_title)
                >= similarity_threshold
            ):
                _union(parent, left.event_id, right.event_id)

    grouped: dict[str, list[ApiEvent]] = {}
    for event in events:
        grouped.setdefault(_root(parent, event.event_id), []).append(event)
    return list(grouped.values())


def pick_survivor(group: list[ApiEvent]) -> ApiEvent:
    """Choose which duplicate survives: highest confidence, then most evidence."""
    return sorted(
        group,
        key=lambda e: (e.confidence, len(e.evidence_ids), e.first_seen_at.timestamp()),
        reverse=True,
    )[0]


def merge_group(group: list[ApiEvent]) -> ApiEvent:
    """Collapse a duplicate group into one event, preserving evidence.

    The start date of the survivor is never overwritten by a loser's value
    (§6.7「開催日変更は履歴を残し、無条件で上書きしない」). A disagreement is
    recorded by demoting the result to ``partial`` so the UI flags it rather
    than silently presenting one of two conflicting dates as settled.
    """
    if len(group) == 1:
        return group[0]
    survivor = pick_survivor(group)
    evidence_ids = list(
        dict.fromkeys(eid for event in group for eid in event.evidence_ids)
    )
    disagreement = any(
        event.dates.event_start.date() != survivor.dates.event_start.date()
        for event in group
    )
    update = {
        "evidence_ids": evidence_ids,
        "last_seen_at": max(event.last_seen_at for event in group),
        "first_seen_at": min(event.first_seen_at for event in group),
    }
    if disagreement and survivor.validation_status == "verified":
        update["validation_status"] = "partial"
    return survivor.model_copy(update=update)
