"""Run the evaluation dataset and gate on the §13.2 criteria.

    python -m event_agent.evaluation.cli --fail-under-gates
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from event_agent.config import settings
from event_agent.evaluation.cases import default_cases_dir, load_cases
from event_agent.evaluation.harness import run_case
from event_agent.evaluation.metrics import (
    CONSISTENCY_FIELDS,
    consistency_metric,
    evaluate,
)
from event_agent.evaluation.report import build_json, render_text, write_json


def _fields_of(result) -> dict[str, dict[str, object]]:
    """Snapshot the fields whose stability §13.2 measures."""
    snapshot: dict[str, object] = {}
    for event in sorted(result.events, key=lambda e: e.official_url):
        for field_path in CONSISTENCY_FIELDS:
            key = f"{event.official_url}|{field_path}"
            if field_path == "title":
                snapshot[key] = event.title
            elif field_path == "dates.eventStart":
                snapshot[key] = event.dates.event_start.isoformat()
            elif field_path == "dates.eventStartPrecision":
                snapshot[key] = event.dates.event_start_precision
            elif field_path == "dates.applicationDeadline":
                snapshot[key] = (
                    event.dates.application_deadline.isoformat()
                    if event.dates.application_deadline
                    else None
                )
            elif field_path == "officialUrl":
                snapshot[key] = event.official_url
            elif field_path == "validationStatus":
                snapshot[key] = event.validation_status
    return snapshot


async def _run(cases_dir: Path, repeats: int):
    cases = load_cases(cases_dir)
    results = [await run_case(case) for case in cases]
    report = evaluate(results)

    # 同一入力を繰り返して必須項目の一致率を測る（§13.2）
    snapshots = [{c.case_id: v for c, v in zip(cases, [_fields_of(r) for r in results])}]
    for _ in range(max(0, repeats - 1)):
        repeat = [await run_case(case) for case in cases]
        snapshots.append({c.case_id: _fields_of(r) for c, r in zip(cases, repeat)})
    consistency = consistency_metric(snapshots)
    return report, [consistency]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the agent evaluation dataset")
    parser.add_argument("--cases", type=Path, default=default_cases_dir())
    parser.add_argument("--report", type=Path, default=None)
    parser.add_argument("--repeats", type=int, default=settings.eval_repeat_count)
    parser.add_argument(
        "--fail-under-gates",
        action="store_true",
        help="基準未達のとき終了コード1を返す（§13.3 のリリースゲート）",
    )
    args = parser.parse_args(argv)

    report, extra = asyncio.run(_run(args.cases, args.repeats))
    print(render_text(report, extra))

    payload = build_json(report, extra, args.repeats)
    if args.report:
        write_json(args.report, payload)
        print(f"\nレポート: {args.report}")

    return 0 if payload["passed"] or not args.fail_under_gates else 1


if __name__ == "__main__":
    sys.exit(main())
