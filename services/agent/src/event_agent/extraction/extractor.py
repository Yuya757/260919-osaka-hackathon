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
from event_agent.clients.page_fetcher import FetchedPage, SearchHit
from event_agent.schemas import (
    ApiEvent,
    EventDates,
    EventLocation,
    EventMilestone,
    Evidence,
    Recommendation,
)

_TITLE = re.compile(r"<title[^>]*>(.*?)</title>", re.I | re.S)
_H1 = re.compile(r"<h1[^>]*>(.*?)</h1>", re.I | re.S)
_TAGS = re.compile(r"<[^>]+>")

_ONLINE_WORDS = ("オンライン", "online", "リモート", "配信", "zoom", "google meet")
_HYBRID_WORDS = ("ハイブリッド", "hybrid", "現地とオンライン", "オンライン併催")
_VENUE_LABELS = ("会場", "開催場所", "場所", "venue")
_ACCESS_LABELS = ("最寄駅", "最寄り駅", "アクセス", "交通")
_STATION = re.compile(r"([一-龥ぁ-んァ-ヶA-Za-z0-9ー]{1,12}?)駅")
_ORGANIZER_LABELS = ("主催", "主催者", "organizer", "運営")

# category（表示用の細分）→ kind（絞り込みとラベル表の切り替え）
_KIND_BY_CATEGORY = {
    "hackathon": "hackathon",
    "contest": "contest",
    "acceleration": "accelerator",
    "cocreation": "cocreation",
    "pitch": "contest",
    "conference": "hackathon",
    "meetup": "hackathon",
    "workshop": "hackathon",
    "other": "hackathon",
}

_CATEGORY_WORDS = (
    ("hackathon", ("ハッカソン", "hackathon")),
    ("contest", ("ビジネスコンテスト", "ビジコン", "ビジネスプラン", "アイデアコンテスト", "コンテスト", "グランプリ", "contest")),
    ("conference", ("カンファレンス", "conference", "サミット")),
    ("meetup", ("ミートアップ", "meetup", "勉強会", "もくもく")),
    ("acceleration", ("アクセラレ", "accelerat", "インキュベーション", "incubation")),
    ("cocreation", ("オープンイノベーション", "open innovation", "共創", "マッチングプログラム", "公募プログラム")),
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
    # 見出し付近から読めたジャンル。読めなければ None（テーマのゲートが判定しない）
    headline_kind: str | None = None

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
    for _label, rest, _line in d.find_labelled(text, labels):
        value = rest.strip()
        if value:
            return value
    return None


_VENUE_BAD_START = ("で", "に", "は", "が", "を", "の", "、", "。", "と", "も")


def clean_venue(value: str | None) -> str | None:
    """会場名として通せる文字列だけ返す。

    「会場で開催します」の行から「で開催します」を拾うと会場名になってしまう。
    助詞で始まるもの、短すぎるもの、文になっているものは捨てる。推測はしない。
    """
    if not value:
        return None
    cleaned = value.strip(" :：　-ー")
    if len(cleaned) < 2 or len(cleaned) > 60:
        return None
    if cleaned.startswith(_VENUE_BAD_START) or cleaned.endswith(("。", "ます", "です")):
        return None
    return cleaned


def location_of(text: str) -> tuple[str, str | None, str]:
    """Return ``(type, venue, snippet)``."""
    lowered = text.casefold()
    venue = clean_venue(_labelled_value(text, _VENUE_LABELS))
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


def station_of(text: str) -> str | None:
    """「最寄駅: JR大阪駅から徒歩5分」→「大阪」。経路検索の到着駅に使う。

    路線名の接頭辞（JR / 阪急 など）は駅名検索の妨げになるので落とす。
    見つからなければ None。推測しない。
    """
    value = _labelled_value(text, _ACCESS_LABELS)
    if not value:
        return None
    match = _STATION.search(value)
    if not match:
        return None
    name = re.sub(r"^(JR|ＪＲ|阪急|阪神|京阪|近鉄|南海|地下鉄|Osaka Metro|大阪メトロ|市営)", "", match.group(1))
    return name or None


def category_of(text: str) -> str:
    """ページの主題に近いカテゴリを選ぶ。

    どのカテゴリの語も本文のどこかには出るので、**最初に現れた語**のカテゴリを採る。
    表の順に舐めると、本題が共創でも本文の隅の「ワークショップ」で workshop になる
    （事前調査で AUBA の共創プログラムがそうなった）。
    """
    lowered = text.casefold()
    best: tuple[int, str] | None = None
    for category, words in _CATEGORY_WORDS:
        for word in words:
            index = lowered.find(word)
            if index >= 0 and (best is None or index < best[0]):
                best = (index, category)
    return best[1] if best else "other"


def kind_of(category: str) -> str:
    """category から kind を決める。未知の category はハッカソン扱い（既定）。"""
    return _KIND_BY_CATEGORY.get(category, "hackathon")


# kind → 表示用 category。ページからジャンルが読めないときの既定
_CATEGORY_BY_KIND = {
    "hackathon": "hackathon",
    "contest": "contest",
    "accelerator": "acceleration",
    "cocreation": "cocreation",
}


def headline_kind(title: str) -> str | None:
    """タイトルがジャンルを名乗っていれば、その kind。名乗っていなければ None。

    本文は当てにならない。事前調査で読んだ AUBA の共創プログラムは、本文に一度
    出る「ワークショップ」でワークショップ扱いになった。逆にハッカソンやビジコンは
    ほぼ必ずタイトルで名乗る。テーマのゲートはこの強い signal のときだけ効かせ、
    名乗っていないページは落とさない。
    """
    category = category_of(title)
    return None if category == "other" else kind_of(category)


def summary_of(text: str, title: str) -> str:
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
    kind: str | None = None,
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

    category = category_of(text)
    resolved_kind = kind or kind_of(category)
    from_headline = headline_kind(title)
    if kind and from_headline is None and kind_of(category) != kind:
        # ページがジャンルを名乗っていない。テーマの種別で表示も揃える
        category = _CATEGORY_BY_KIND.get(kind, category)
    start, end = d.find_event_dates(text, fallback_year=fallback_year, kind=resolved_kind)
    deadline = d.find_application_deadline(
        text, fallback_year=fallback_year, kind=resolved_kind
    )
    # 実施日か締切のどちらかは要る。ハッカソンは実施日が必須のまま（§6.6）
    if start is None and (resolved_kind == "hackathon" or deadline is None):
        return None
    if start is not None:
        sources["dates.eventStart"] = FieldSource(
            "dates.eventStart", start.snippet, page.final_url
        )
    if end is not None:
        sources["dates.eventEnd"] = FieldSource(
            "dates.eventEnd", end.snippet, page.final_url
        )

    if deadline is not None:
        sources["dates.applicationDeadline"] = FieldSource(
            "dates.applicationDeadline", deadline.snippet, page.final_url
        )

    location_type, venue, location_snippet = location_of(text)
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
        category=category,
        kind=resolved_kind,
        summary=summary_of(text, title),
        location=EventLocation(
            type=location_type, venue=venue, region=venue, nearestStation=station_of(text)
        ),
        dates=EventDates(
            applicationDeadline=deadline.value if deadline else None,
            applicationDeadlinePrecision=deadline.precision if deadline else "unknown",
            eventStart=start.value if start else None,
            eventStartPrecision=start.precision if start else "unknown",
            eventEnd=end.value if end else None,
            milestones=[
                EventMilestone(label=label, at=parsed.value, precision=parsed.precision)
                for label, parsed in d.find_milestones(
                    text, fallback_year=fallback_year, kind=resolved_kind
                )
            ],
        ),
        attributes=d.find_attributes(text, kind=resolved_kind),
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

    return ExtractedCandidate(
        event=event, evidence=evidence, field_sources=sources, headline_kind=from_headline
    )


def extract_candidates(
    pages: list[FetchedPage],
    *,
    hits: dict[str, SearchHit] | None = None,
    run_id: str,
    now: datetime,
    user_id: str,
    source_types: dict[str, str] | None = None,
    kind: str | None = None,
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
            kind=kind,
        )
        if candidate is not None:
            out.append(candidate)
    return out
