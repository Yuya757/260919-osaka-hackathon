"""Deterministic, application-side derivations for event candidates.

Agent詳細要件定義書 §7.5 requires that confidence is computed by the
application from observable properties, never taken from the model's own
self-reported score. §9.3 requires a stable ``dedupKey``. Both live here so the
rules stay independent of the Cloud Run entrypoints and can be unit tested.
"""

from __future__ import annotations

import difflib
import hashlib
import re
import unicodedata
from datetime import datetime
from urllib.parse import urlsplit, urlunsplit

_WHITESPACE = re.compile(r"\s+")
_DECORATION = re.compile(r"[　-〿！-／：-＠［-｀｛-･!-/:-@\[-`{-~]")
_TRACKING_PREFIXES = ("utm_", "gclid", "fbclid", "mc_cid", "mc_eid")


def normalize_title(title: str) -> str:
    """Fold width, case, punctuation and spacing so near-identical titles match."""
    folded = unicodedata.normalize("NFKC", title).casefold()
    folded = _DECORATION.sub(" ", folded)
    return _WHITESPACE.sub(" ", folded).strip()


def normalize_url(url: str) -> str:
    """Drop scheme case, ``www.``, tracking query params and trailing slashes."""
    parts = urlsplit(url.strip())
    host = parts.netloc.casefold()
    if host.startswith("www."):
        host = host[4:]
    kept = [
        pair
        for pair in parts.query.split("&")
        if pair and not pair.casefold().startswith(_TRACKING_PREFIXES)
    ]
    path = parts.path.rstrip("/") or "/"
    return urlunsplit((parts.scheme.casefold(), host, path, "&".join(kept), ""))


def compute_dedup_key(
    official_url: str,
    normalized_title: str,
    event_start: datetime,
    organizer: str | None,
) -> str:
    """Stable identity per §9.3: normalized URL, title, start date and organizer.

    The same event in a different year must produce a different key, so the
    start *date* participates rather than only the month.
    """
    material = "|".join(
        [
            normalize_url(official_url),
            normalized_title,
            event_start.date().isoformat(),
            normalize_title(organizer or ""),
        ]
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


# Weights sum to 1.0. Each component is observable without asking the model.
_W_OFFICIAL = 0.30
_W_EVIDENCE = 0.30
_W_CORROBORATION = 0.15
_W_DATE_COMPLETENESS = 0.15
_W_NO_CONFLICT = 0.10

_REQUIRED_EVIDENCE_FIELDS = ("title", "dates.eventStart")


def compute_confidence(
    *,
    source_types: list[str],
    supported_fields: set[str],
    distinct_hosts: int,
    deadline_known: bool,
    deadline_precision: str,
    start_precision: str,
    has_conflict: bool,
) -> float:
    """Confidence in [0, 1], computed from evidence and validation facts (§7.5)."""
    score = 0.0

    if any(t in ("official", "organizer") for t in source_types):
        score += _W_OFFICIAL
    elif "aggregator" in source_types:
        # 集約サイトのみを根拠とする場合は満点を与えない（§6.6 公式性）
        score += _W_OFFICIAL / 3

    covered = sum(1 for f in _REQUIRED_EVIDENCE_FIELDS if f in supported_fields)
    score += _W_EVIDENCE * covered / len(_REQUIRED_EVIDENCE_FIELDS)

    if distinct_hosts >= 2:
        score += _W_CORROBORATION

    date_points = 0.0
    if start_precision == "datetime":
        date_points += 0.5
    if deadline_known and deadline_precision == "datetime":
        date_points += 0.5
    elif deadline_known:
        date_points += 0.25
    score += _W_DATE_COMPLETENESS * date_points

    if not has_conflict:
        score += _W_NO_CONFLICT

    return round(min(score, 1.0), 2)


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
) -> str:
    """Map facts onto the §6.6 statuses.

    Precedence is rejected > quarantined > partial > verified: ``rejected`` is
    terminal (the event is over, out of scope, or the URL is unsafe), so it is
    decided first and nothing downstream can promote it.

    ``partial`` is only allowed when the event date itself is settled and
    evidenced; a missing deadline must never be presented as "no deadline".
    """
    if not url_safe or is_finished or not in_target_year:
        return "rejected"
    if has_conflict or not has_required_evidence:
        return "quarantined"
    if not deadline_known:
        return "partial"
    if confidence < threshold:
        return "partial"
    return "verified"


def title_similarity(left: str, right: str) -> float:
    """Character-level similarity over already-normalized titles (§6.7 優先度4).

    ``difflib`` is stdlib and needs no tokenizer, which matters because the
    titles are mostly Japanese. Very short titles are compared exactly: at
    three or four characters the ratio is dominated by noise.
    """
    if not left or not right:
        return 0.0
    if min(len(left), len(right)) < 6:
        return 1.0 if left == right else 0.0
    matcher = difflib.SequenceMatcher(None, left, right)
    # 安い順に足切りしてから本計算する
    if matcher.real_quick_ratio() < 0.5 or matcher.quick_ratio() < 0.5:
        return matcher.quick_ratio()
    return matcher.ratio()


def score_recommendation(event, evidence: list, preferences, *, now: datetime) -> int:
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
    region_match = any(loc and loc in region for loc in preferences.locations)
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
    if all(f in supported for f in _REQUIRED_EVIDENCE_FIELDS):
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


def score_event(
    event,
    evidence: list,
    *,
    threshold: float,
    now: datetime | None = None,
    target_year: int | None = None,
    url_safe: bool = True,
):
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
    has_conflict = bool(
        deadline_known and dates.application_deadline > dates.event_start
    ) or bool(dates.event_end and dates.event_end < dates.event_start)

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
        end = dates.event_end or dates.event_start
        is_finished = end < now
    in_target_year = True
    if target_year is not None:
        in_target_year = dates.event_start.year == target_year

    status = derive_validation_status(
        confidence=confidence,
        threshold=threshold,
        deadline_known=deadline_known,
        has_conflict=has_conflict,
        has_required_evidence=all(f in supported for f in _REQUIRED_EVIDENCE_FIELDS),
        is_finished=is_finished,
        in_target_year=in_target_year,
        url_safe=url_safe,
    )
    return event.model_copy(
        update={
            "evidence_ids": [e.evidence_id for e in evidence],
            "confidence": confidence,
            "validation_status": status,
        }
    )


def _pairs(items: list):
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
    events: list, *, similarity_threshold: float, date_window_days: int = 7
) -> list[list]:
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
    buckets: dict[str, list] = {}

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

    def _same_region(left, right) -> bool:
        return (left.location.region or "").casefold() == (
            right.location.region or ""
        ).casefold()

    def _compatible_organizer(left, right) -> bool:
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

    grouped: dict[str, list] = {}
    for event in events:
        grouped.setdefault(_root(parent, event.event_id), []).append(event)
    return list(grouped.values())


def pick_survivor(group: list):
    """Choose which duplicate survives: highest confidence, then most evidence."""
    return sorted(
        group,
        key=lambda e: (e.confidence, len(e.evidence_ids), e.first_seen_at.timestamp()),
        reverse=True,
    )[0]


def merge_group(group: list):
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
