"""Validation status (§6.6) and the scoring of a single candidate."""

from __future__ import annotations

from datetime import datetime
from urllib.parse import urlsplit

from event_agent.domain.confidence import compute_confidence, required_evidence_fields
from event_agent.schemas import ApiEvent, Evidence


def derive_validation_status(
    *,
    confidence: float,
    threshold: float,
    deadline_known: bool,
    has_conflict: bool,
    has_required_evidence: bool,
    is_finished: bool = False,
    in_target_year: bool = True,
    url_safe: bool = True,
    aggregator_only: bool = False,
    aggregator_min_confidence: float = 0.0,
) -> str:
    """Map facts onto the §6.6 statuses.

    Precedence is rejected > quarantined > partial > verified: ``rejected`` is
    terminal (the event is over, out of scope, or the URL is unsafe), so it is
    decided first and nothing downstream can promote it.

    ``partial`` is only allowed when the event date itself is settled and
    evidenced; a missing deadline must never be presented as "no deadline".

    An event whose only sources are aggregator sites is held back below
    ``aggregator_min_confidence`` (画面設計書§8-2). §6.6「公式性」 asks for the
    lack of an official page to be stated rather than hidden, but below that
    floor the event has not even got evidence on both required fields, and the
    dual-date display the product exists for would be guesswork.
    """
    if not url_safe or is_finished or not in_target_year:
        return "rejected"
    if has_conflict or not has_required_evidence:
        return "quarantined"
    if aggregator_only and confidence < aggregator_min_confidence:
        return "quarantined"
    if not deadline_known:
        return "partial"
    if confidence < threshold:
        return "partial"
    return "verified"

def score_event(
    event: ApiEvent,
    evidence: list[Evidence],
    *,
    threshold: float,
    now: datetime | None = None,
    target_year: int | None = None,
    url_safe: bool = True,
    aggregator_min_confidence: float = 0.0,
) -> ApiEvent:
    """Return a copy of ``event`` with evidence, confidence and status filled in.

    Kept out of the Pydantic model because it needs the evidence records, which
    live alongside the run rather than on the event document.
    """
    source_types = [e.source_type for e in evidence]
    supported: set[str] = set()
    for item in evidence:
        supported.update(item.supports)
    hosts = {urlsplit(e.canonical_url or e.source_url).netloc.casefold() for e in evidence}

    dates = event.dates
    deadline_known = dates.application_deadline is not None
    # 実施日が無い告知（ビジコン・補助金）は、締切と実施日の前後関係を問えない
    has_conflict = bool(
        deadline_known and dates.event_start and dates.application_deadline > dates.event_start
    ) or bool(dates.event_end and dates.event_start and dates.event_end < dates.event_start)

    confidence = compute_confidence(
        source_types=source_types,
        supported_fields=supported,
        distinct_hosts=len(hosts),
        deadline_known=deadline_known,
        deadline_precision=dates.application_deadline_precision,
        start_precision=dates.event_start_precision,
        has_conflict=has_conflict,
    )
    # 終了判定は呼び出し側から渡された時刻で行う。ここで datetime.now() を
    # 呼ぶと、同じ入力でも時間の経過で結果が変わり §13.2 の再現性が測れない。
    is_finished = False
    if now is not None:
        # 実施日が無ければ締切で終了を判断する。どちらも無ければ終了とみなさない
        end = dates.event_end or dates.event_start or dates.application_deadline
        is_finished = end < now if end else False
    # 対象年（§6.6）。ビジコンは「2026年に応募 → 2027年に最終審査」が普通なので、
    # 締切か実施日のどちらかが対象年なら対象とみなす。どちらも無ければ問わない
    in_target_year = True
    if target_year is not None:
        years = {
            value.year
            for value in (dates.event_start, dates.application_deadline)
            if value is not None
        }
        in_target_year = target_year in years if years else True

    status = derive_validation_status(
        confidence=confidence,
        threshold=threshold,
        deadline_known=deadline_known,
        has_conflict=has_conflict,
        has_required_evidence=all(
            f in supported for f in required_evidence_fields(dates.event_start is not None)
        ),
        is_finished=is_finished,
        in_target_year=in_target_year,
        url_safe=url_safe,
        aggregator_only=bool(source_types)
        and not any(t in ("official", "organizer") for t in source_types),
        aggregator_min_confidence=aggregator_min_confidence,
    )
    return event.model_copy(
        update={
            "evidence_ids": [e.evidence_id for e in evidence],
            "confidence": confidence,
            "validation_status": status,
        }
    )
