"""Application-side confidence (§7.5).

§7.5 requires the score be computed by the application from observable
properties, never taken from the model's own self-reported number. Another
leaf module: the inputs are plain values, so nothing here needs ``schemas``.
"""

from __future__ import annotations

# Weights sum to 1.0. Each component is observable without asking the model.
_W_OFFICIAL = 0.30
_W_EVIDENCE = 0.30
_W_CORROBORATION = 0.15
_W_DATE_COMPLETENESS = 0.15
_W_NO_CONFLICT = 0.10

REQUIRED_EVIDENCE_FIELDS = ("title", "dates.eventStart")
# 実施日が無い告知（ビジコン・補助金）は、締切の根拠を実施日の代わりに求める
REQUIRED_EVIDENCE_FIELDS_NO_START = ("title", "dates.applicationDeadline")


def required_evidence_fields(has_event_start: bool) -> tuple[str, ...]:
    return REQUIRED_EVIDENCE_FIELDS if has_event_start else REQUIRED_EVIDENCE_FIELDS_NO_START


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

    required = required_evidence_fields("dates.eventStart" in supported_fields)
    covered = sum(1 for f in required if f in supported_fields)
    score += _W_EVIDENCE * covered / len(required)

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
