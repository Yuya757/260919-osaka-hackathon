"""Build event candidates from fetched pages (§6.5).

Every field that reaches the output carries the literal page snippet it came
from. That is what makes §13.2's「必須項目に根拠のない値を生成する割合 0%」
enforceable by construction rather than by inspection: a value with no snippet
is dropped before it can be emitted.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime

from event_agent.extraction import dates as d
from event_agent.extraction.html_text import to_text
from event_agent.page_fetcher import FetchedPage, SearchHit
from event_agent.schemas import (
    ApiEvent,
    EventDates,
    EventLocation,
    Evidence,
    Recommendation,
)

_TITLE = re.compile(r"<title[^>]*>(.*?)</title>", re.I | re.S)
_H1 = re.compile(r"<h1[^>]*>(.*?)</h1>", re.I | re.S)
_TAGS = re.compile(r"<[^>]+>")

_ONLINE_WORDS = ("オンライン", "online", "リモート", "配信", "zoom", "google meet")
_HYBRID_WORDS = ("ハイブリッド", "hybrid", "現地とオンライン", "オンライン併催")
_VENUE_LABELS = ("会場", "開催場所", "場所", "venue")
_ORGANIZER_LABELS = ("主催", "主催者", "organizer", "運営")

_CATEGORY_WORDS = (
    ("hackathon", ("ハッカソン", "hackathon")),
    ("conference", ("カンファレンス", "conference", "サミット")),
    ("meetup", ("ミートアップ", "meetup", "勉強会", "もくもく")),
    ("acceleration", ("アクセラレ", "accelerat")),
    ("pitch", ("ピッチ", "pitch", "demo day", "デモデイ")),
    ("workshop", ("ワークショップ", "workshop")),
)


@dataclass(frozen=True)
class FieldSource:
    """Where a field's value literally came from."""

    field_path: str
    snippet: str
    url: str


@dataclass
class ExtractedCandidate:
    event: ApiEvent
    evidence: list[Evidence]
    field_sources: dict[str, FieldSource] = field(default_factory=dict)
    conflicts: list[str] = field(default_factory=list)

    def grounded(self, field_path: str) -> bool:
        return field_path in self.field_sources


def _strip(html_fragment: str) -> str:
    return _TAGS.sub("", html_fragment).strip()


def _title_of(page: FetchedPage, hit: SearchHit | None) -> tuple[str, str] | None:
    for pattern in (_H1, _TITLE):
        match = pattern.search(page.text)
        if match:
            value = _strip(match.group(1))
            if value:
                return value, value
    if hit and hit.title:
        return hit.title, hit.title
    return None


def _labelled_value(text: str, labels: tuple[str, ...]) -> str | None:
    for _label, rest in d.find_labelled(text, labels):
        value = rest.strip()
        if value:
            return value
    return None


def _location_of(text: str) -> tuple[str, str | None, str]:
    """Return ``(type, venue, snippet)``."""
    lowered = text.casefold()
    venue = _labelled_value(text, _VENUE_LABELS)
    if any(word in lowered for word in _HYBRID_WORDS):
        return "hybrid", venue, "ハイブリッド"
    online = any(word in lowered for word in _ONLINE_WORDS)
    if online and venue and not any(w in venue.casefold() for w in _ONLINE_WORDS):
        return "hybrid", venue, venue
    if online:
        return "online", venue, "オンライン"
    if venue:
        return "offline", venue, venue
    return "unknown", None, ""


def _category_of(text: str) -> str:
    lowered = text.casefold()
    for category, words in _CATEGORY_WORDS:
        if any(word in lowered for word in words):
            return category
    return "other"


def _summary_of(text: str, title: str) -> str:
    for line in text.splitlines():
        stripped = line.strip()
        if len(stripped) >= 20 and stripped != title:
            return stripped[:200]
    return ""


def extract_candidate(
    page: FetchedPage,
    *,
    hit: SearchHit | None,
    run_id: str,
    now: datetime,
    user_id: str,
    source_type: str = "other",
) -> ExtractedCandidate | None:
    """Extract one candidate from one page, or None when it is not an event."""
    text = to_text(page.text)
    sources: dict[str, FieldSource] = {}

    titled = _title_of(page, hit)
    if not titled:
        return None
    title, title_snippet = titled
    sources["title"] = FieldSource("title", title_snippet, page.final_url)

    # 年は「ページ上で一意に確定できる」ときだけ補完する（§6.5）
    years = d.page_years(d.normalize(text))
    fallback_year = next(iter(years)) if len(years) == 1 else None

    start, end = d.find_event_dates(text, fallback_year=fallback_year)
    if start is None:
        return None  # 開催日が取れないものは候補にしない（§6.6 必須項目）
    sources["dates.eventStart"] = FieldSource(
        "dates.eventStart", start.snippet, page.final_url
    )
    if end is not None:
        sources["dates.eventEnd"] = FieldSource(
            "dates.eventEnd", end.snippet, page.final_url
        )

    deadline = d.find_application_deadline(text, fallback_year=fallback_year)
    if deadline is not None:
        sources["dates.applicationDeadline"] = FieldSource(
            "dates.applicationDeadline", deadline.snippet, page.final_url
        )

    location_type, venue, location_snippet = _location_of(text)
    if location_snippet:
        sources["location"] = FieldSource("location", location_snippet, page.final_url)

    organizer = _labelled_value(text, _ORGANIZER_LABELS)
    if organizer:
        sources["organizer"] = FieldSource("organizer", organizer, page.final_url)

    sources["officialUrl"] = FieldSource("officialUrl", page.final_url, page.final_url)

    event = ApiEvent(
        eventId=page.content_hash[:16],
        userId=user_id,
        title=title,
        organizer=organizer,
        category=_category_of(text),
        summary=_summary_of(text, title),
        location=EventLocation(type=location_type, venue=venue, region=venue),
        dates=EventDates(
            applicationDeadline=deadline.value if deadline else None,
            applicationDeadlinePrecision=deadline.precision if deadline else "unknown",
            eventStart=start.value,
            eventStartPrecision=start.precision,
            eventEnd=end.value if end else None,
        ),
        officialUrl=page.final_url,
        recommendation=Recommendation(score=0, reason=""),
        firstSeenAt=now,
        lastSeenAt=now,
        sourceRunId=run_id,
        source="公式サイトで確認済み" if source_type == "official" else "取得元を確認",
    )

    evidence = [
        Evidence(
            evidenceId=f"{page.content_hash[:12]}-{index}",
            query=hit.query if hit else None,
            sourceUrl=page.final_url,
            sourceType=source_type,
            title=title,
            excerpt=source.snippet[:500],
            supports=[source.field_path],
            retrievedAt=page.fetched_at,
            contentHash=page.content_hash,
        )
        for index, source in enumerate(sources.values())
        if source.field_path
        in {
            "title",
            "dates.eventStart",
            "dates.eventEnd",
            "dates.applicationDeadline",
            "location",
            "organizer",
            "officialUrl",
        }
    ]

    return ExtractedCandidate(event=event, evidence=evidence, field_sources=sources)


def extract_candidates(
    pages: list[FetchedPage],
    *,
    hits: dict[str, SearchHit] | None = None,
    run_id: str,
    now: datetime,
    user_id: str,
    source_types: dict[str, str] | None = None,
) -> list[ExtractedCandidate]:
    hits = hits or {}
    source_types = source_types or {}
    out: list[ExtractedCandidate] = []
    for page in pages:
        candidate = extract_candidate(
            page,
            hit=hits.get(page.requested_url) or hits.get(page.final_url),
            run_id=run_id,
            now=now,
            user_id=user_id,
            source_type=source_types.get(page.final_url)
            or source_types.get(page.requested_url)
            or "other",
        )
        if candidate is not None:
            out.append(candidate)
    return out
