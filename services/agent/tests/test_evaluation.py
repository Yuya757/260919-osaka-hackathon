"""The evaluation dataset as a test, so `pytest` gives a single verdict.

§13.3 requires that the dataset is re-run whenever prompts, schemas, models or
validation rules change, and that a release is blocked when the criteria are
not met. CI runs this.
"""

from __future__ import annotations

import asyncio
import json
from collections import Counter
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from event_agent.evaluation.cases import default_cases_dir, default_schema_path, load_cases
from event_agent.evaluation.harness import run_case
from event_agent.evaluation.metrics import evaluate

REQUIRED_CATEGORIES = {
    "deadline_clear",
    "deadline_missing",
    "multi_day",
    "location_modes",
    "year_partial",
    "deadline_kinds",
    "duplicates",
    "finished",
    "conflicting_sources",
    "prompt_injection",
}


@pytest.fixture(scope="module")
def cases():
    return load_cases()


@pytest.fixture(scope="module")
def report(cases):
    async def _run():
        return [await run_case(case) for case in cases]

    return evaluate(asyncio.run(_run()))


def test_dataset_has_at_least_fifty_cases(cases) -> None:
    """§13.1「最低50件の正解付きイベントを用意し」"""
    assert len(cases) >= 50


def test_dataset_covers_every_required_category(cases) -> None:
    counts = Counter(category for case in cases for category in case.categories)
    assert REQUIRED_CATEGORIES <= set(counts), REQUIRED_CATEGORIES - set(counts)


def test_every_case_matches_the_schema() -> None:
    schema = json.loads(default_schema_path().read_text(encoding="utf-8"))
    validator = Draft202012Validator(schema)
    problems: list[str] = []
    for path in sorted(default_cases_dir().glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        for error in validator.iter_errors(data):
            problems.append(f"{path.name}: {'/'.join(map(str, error.absolute_path))} {error.message}")
    assert not problems, "\n".join(problems[:10])


@pytest.mark.parametrize(
    "key",
    [
        "eventStartAccuracy",
        "deadlineAccuracy",
        "evidenceCoverage",
        "finishedShownRate",
        "duplicateF1",
        "ungroundedRate",
        "toolDeviations",
        "caseFailures",
    ],
)
def test_acceptance_criterion(report, key: str) -> None:
    """§13.2 の受入基準。1つでも割ったらリリースしない。"""
    metric = next(m for m in report.metrics if m.key == key)
    assert metric.passed, (
        f"{metric.label}: {metric.value} (基準 {metric.comparison} {metric.gate}) "
        f"{metric.detail}"
    )


def test_no_unexpected_failures(report) -> None:
    assert not report.failures, "\n".join(
        f"{f.case_id} {f.metric}: expected={f.expected} got={f.got}"
        for f in report.failures[:10]
    )
