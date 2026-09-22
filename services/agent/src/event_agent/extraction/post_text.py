"""主催者投稿の本文から Event を派生させる（F-06 / ADR-006）。

ページ抽出（:mod:`event_agent.extraction.extractor`）と同じ決定論的な日付解析を
使う。投稿は主催者本人が書いた文だが、扱いはページ本文と同じ「根拠のある値だけ
採用する」で、年が本文に一つだけ無ければ年を補わない（§6.5）。モデルは呼ばない。

抽出結果は :func:`event_agent.domain.validation.score_event` に通し、ページ由来の
イベントと同じ規則で ``validationStatus`` を決める。主催者 1 ホストだけの根拠では
confidence の上限が 0.85 なので、締切と開催日が両方 datetime 精度のときだけ
``verified`` になり、それ以外は ``partial``（UI では「要確認」）になる。
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime

from event_agent.config import get_settings
from event_agent.domain.normalize import compute_dedup_key, normalize_title
from event_agent.domain.validation import score_event
from event_agent.extraction import dates as d
from event_agent.extraction.extractor import (
    _ORGANIZER_LABELS,
    _labelled_value,
    category_of,
    kind_of,
    location_of,
    station_of,
    summary_of,
)
from event_agent.schemas import (
    DEMO_USER_ID,
    ORGANIZER_POST_RUN_ID,
    ApiEvent,
    EventDates,
    EventLocation,
    EventMilestone,
    Evidence,
    OrganizerPostRequest,
    PostIssue,
)

_EVIDENCE_FIELDS = (
    "title",
    "dates.eventStart",
    "dates.eventEnd",
    "dates.applicationDeadline",
    "location",
    "organizer",
    "officialUrl",
)

EVENT_DATE_HINT = "「開催日: 2026年10月11日 10:00」のように、年を含めて書いてください。"


def post_id_for(origin: str, dedup_key: str) -> str:
    """投稿IDは dedupKey から決める。同じ告知を二度投げても同じ文書に上書きされる（§9.3）。"""
    prefix = "bot" if origin == "bot" else "post"
    return f"{prefix}-{dedup_key[:24]}"


@dataclass
class PostDraft:
    """投稿から派生した Event と、投稿者に返す指摘。"""

    event: ApiEvent | None
    evidence: list[Evidence] = field(default_factory=list)
    issues: list[PostIssue] = field(default_factory=list)

    def ok(self) -> bool:
        return self.event is not None and not any(i.severity == "error" for i in self.issues)

    @property
    def errors(self) -> list[PostIssue]:
        return [i for i in self.issues if i.severity == "error"]

    @property
    def warnings(self) -> list[PostIssue]:
        return [i for i in self.issues if i.severity == "warning"]


def _issue(code: str, severity: str, message: str) -> PostIssue:
    return PostIssue(code=code, severity=severity, message=message)  # type: ignore[arg-type]


def _year_ambiguous(text: str, years: set[int]) -> bool:
    """年なしの開催日らしき記述はあるが、年が一意に決まらないか。

    仮の年で解析が通るかだけを見る。通った結果を使うことは決してない。
    エラー文言を「開催日が無い」から「年が分からない」に変えるための判定である。
    """
    if len(years) == 1:
        return False
    probe, _ = d.find_event_dates(text, fallback_year=2000)
    return probe is not None


def derive_event_from_post(
    request: OrganizerPostRequest,
    *,
    now: datetime,
    user_id: str = DEMO_USER_ID,
) -> PostDraft:
    """投稿本文から Event と根拠を作る。開催日が取れなければ ``event`` は None。

    ``eventId`` は投稿IDと同じで、投稿IDは dedupKey から決まる。
    """
    settings = get_settings()
    text = d.normalize(f"{request.title}\n{request.body}")
    years = d.page_years(text)
    # 年は本文で一意に確定できるときだけ補完する（§6.5）
    fallback_year = next(iter(years)) if len(years) == 1 else None

    category = category_of(text)
    kind = kind_of(category)
    start, end = d.find_event_dates(text, fallback_year=fallback_year, kind=kind)
    deadline = d.find_application_deadline(text, fallback_year=fallback_year, kind=kind)
    # 実施日を書かない告知がある（ビジコン・補助金）。締切だけでも載せる。
    # ハッカソンは実施日が必須のまま（§6.6、ジャンル拡張計画 段階1）
    if start is None and (kind == "hackathon" or deadline is None):
        if _year_ambiguous(text, years):
            return PostDraft(
                event=None,
                issues=[
                    _issue(
                        "YEAR_AMBIGUOUS",
                        "error",
                        "開催日の年が本文から確定できません。" + EVENT_DATE_HINT,
                    )
                ],
            )
        return PostDraft(
            event=None,
            issues=[
                _issue(
                    "EVENT_DATE_MISSING",
                    "error",
                    "開催日か申込締切が見つかりませんでした。" + EVENT_DATE_HINT,
                )
            ],
        )

    location_type, venue, location_snippet = location_of(text)
    organizer_in_body = _labelled_value(text, _ORGANIZER_LABELS)
    organizer = organizer_in_body or request.organizer_name
    dedup_key = compute_dedup_key(
        request.contact_url,
        normalize_title(request.title),
        start.value if start else None,
        organizer,
        deadline.value if deadline else None,
    )
    post_id = post_id_for("organizer", dedup_key)

    # 根拠は「本文のどの行から取ったか」を項目ごとに残す。出典URLは主催者の申告URL。
    snippets: dict[str, str] = {"title": request.title}
    if start is not None:
        snippets["dates.eventStart"] = start.snippet
    snippets["officialUrl"] = request.contact_url
    if end is not None:
        snippets["dates.eventEnd"] = end.snippet
    if deadline is not None:
        snippets["dates.applicationDeadline"] = deadline.snippet
    if location_snippet:
        snippets["location"] = location_snippet
    if organizer_in_body:
        snippets["organizer"] = organizer_in_body

    content_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
    evidence = [
        Evidence(
            evidenceId=f"{post_id}-{index}",
            sourceUrl=request.contact_url,
            sourceType="organizer",
            title=request.title,
            excerpt=snippet[:500],
            supports=[field_path],  # type: ignore[list-item]
            retrievedAt=now,
            contentHash=content_hash,
        )
        for index, (field_path, snippet) in enumerate(snippets.items())
        if field_path in _EVIDENCE_FIELDS
    ]

    event = ApiEvent(
        eventId=post_id,
        userId=user_id,
        title=request.title,
        organizer=organizer,
        category=category,
        kind=kind,
        summary=summary_of(request.body, request.title) or request.title,
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
                    text, fallback_year=fallback_year, kind=kind
                )
            ],
        ),
        attributes=d.find_attributes(text, kind=kind),
        officialUrl=request.contact_url,
        recommendation=None,
        firstSeenAt=now,
        lastSeenAt=now,
        sourceRunId=ORGANIZER_POST_RUN_ID,
        source="主催者投稿",
    )
    scored = score_event(
        event,
        evidence,
        threshold=settings.verified_confidence_threshold,
        now=now,
        aggregator_min_confidence=settings.aggregator_only_min_confidence,
    )

    issues: list[PostIssue] = []
    if scored.validation_status == "rejected":
        issues.append(
            _issue("EVENT_FINISHED", "error", "開催日がすでに過ぎているため投稿できません。")
        )
    elif scored.validation_status == "quarantined":
        issues.append(
            _issue(
                "DATE_CONFLICT",
                "error",
                "申込締切が開催日より後になっています。日付を確認してください。",
            )
        )
    if deadline is None:
        issues.append(
            _issue(
                "DEADLINE_MISSING",
                "warning",
                "申込締切が見つかりませんでした。一覧には「未確認」と表示されます。"
                "「申込締切: 2026年9月28日 23:59」のように書くと反映されます。",
            )
        )
    return PostDraft(event=scored, evidence=evidence, issues=issues)
