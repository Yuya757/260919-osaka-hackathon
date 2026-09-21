"""Deterministic, application-side derivations for event candidates.

Agent詳細要件定義書 §7.5 requires that confidence is computed by the
application from observable properties, never taken from the model's own
self-reported score. §9.3 requires a stable ``dedupKey``. Both live here so the
rules stay independent of the Cloud Run entrypoints and can be unit tested.
"""

from __future__ import annotations

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
) -> str:
    """Map facts onto the §6.6 statuses.

    ``partial`` is only allowed when the event date itself is settled and
    evidenced; a missing deadline must never be presented as "no deadline".
    """
    if has_conflict or not has_required_evidence:
        return "quarantined"
    if not deadline_known:
        return "partial"
    if confidence < threshold:
        return "partial"
    return "verified"


def score_event(event, evidence: list, *, threshold: float):
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
    status = derive_validation_status(
        confidence=confidence,
        threshold=threshold,
        deadline_known=deadline_known,
        has_conflict=has_conflict,
        has_required_evidence=all(f in supported for f in _REQUIRED_EVIDENCE_FIELDS),
    )
    return event.model_copy(
        update={
            "evidence_ids": [e.evidence_id for e in evidence],
            "confidence": confidence,
            "validation_status": status,
        }
    )
