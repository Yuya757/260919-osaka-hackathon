"""Render the evaluation report.

The Cursor skill (`.cursor/skills/event-agent-development/SKILL.md`) requires
that prompt, model, schema and validation-rule versions are recorded with the
results, so a number in a report can always be traced to what produced it.
"""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from event_agent.config import settings
from event_agent.evaluation.metrics import Metric, Report


def _schema_hash() -> str:
    root = Path(__file__).resolve().parents[5] / "packages" / "contracts" / "schemas"
    digest = hashlib.sha256()
    for path in sorted(root.glob("*.json")):
        digest.update(path.name.encode("utf-8"))
        digest.update(path.read_bytes())
    return digest.hexdigest()


def build_meta(case_count: int, repeat_count: int) -> dict[str, Any]:
    return {
        "runAt": datetime.now(timezone.utc).isoformat(),
        "gitSha": os.environ.get("GITHUB_SHA", ""),
        "caseCount": case_count,
        "repeatCount": repeat_count,
        "demoMode": not settings.use_vertex,
        "model": settings.gemini_model,
        "promptVersion": settings.prompt_version,
        "extractionSchemaVersion": settings.extraction_schema_version,
        "validationRuleVersion": settings.validation_rule_version,
        "contractsSchemaHash": _schema_hash(),
        "settings": {
            "maxSearchQueries": settings.max_search_queries,
            "maxCandidates": settings.max_candidates,
            "maxModelCalls": settings.max_model_calls,
            "verifiedConfidenceThreshold": settings.verified_confidence_threshold,
            "titleSimilarityThreshold": settings.title_similarity_threshold,
        },
    }


def _format_value(metric: Metric) -> str:
    if metric.key in ("toolDeviations", "caseFailures"):
        return f"{int(metric.value)}件"
    return f"{metric.value * 100:.1f}%"


def _format_gate(metric: Metric) -> str:
    if metric.gate is None:
        return "記録のみ"
    if metric.key in ("toolDeviations", "caseFailures"):
        return f"{int(metric.gate)}件"
    symbol = "≥" if metric.comparison == "gte" else "≤"
    return f"{symbol} {metric.gate * 100:.0f}%"


def render_text(report: Report, extra: list[Metric] | None = None) -> str:
    metrics = [*report.metrics, *(extra or [])]
    lines = [
        f"評価データセット: {report.case_count}ケース",
        "",
        f"{'指標':<34}{'結果':>10}{'基準':>12}  判定",
        "-" * 72,
    ]
    for metric in metrics:
        verdict = "—" if not metric.gated else ("PASS" if metric.passed else "FAIL")
        lines.append(
            f"{metric.label:<34}{_format_value(metric):>10}{_format_gate(metric):>12}  {verdict}"
            + (f"   ({metric.detail})" if metric.detail else "")
        )
    lines.append("-" * 72)

    if report.failures:
        lines.append("")
        lines.append(f"不一致 {len(report.failures)}件（先頭20件）:")
        for failure in report.failures[:20]:
            lines.append(
                f"  {failure.case_id}  {failure.metric}: "
                f"期待={failure.expected} / 実際={failure.got}"
            )
    gated = [m for m in metrics if m.gated]
    failed = [m for m in gated if not m.passed]
    lines.append("")
    lines.append(
        f"判定: {'PASS' if not failed else 'FAIL'}  ({len(gated) - len(failed)}/{len(gated)} 基準を満たす)"
    )
    return "\n".join(lines)


def build_json(report: Report, extra: list[Metric], repeat_count: int) -> dict[str, Any]:
    metrics = [*report.metrics, *extra]
    return {
        "meta": build_meta(report.case_count, repeat_count),
        "passed": all(m.passed for m in metrics),
        "metrics": [
            {
                "key": m.key,
                "label": m.label,
                "value": m.value,
                "gate": m.gate,
                "comparison": m.comparison,
                "detail": m.detail,
                "passed": m.passed,
            }
            for m in metrics
        ],
        "failures": [
            {
                "caseId": f.case_id,
                "metric": f.metric,
                "expected": f.expected,
                "got": f.got,
            }
            for f in report.failures
        ],
    }


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
