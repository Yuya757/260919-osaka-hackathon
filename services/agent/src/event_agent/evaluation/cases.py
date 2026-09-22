"""Load the labelled evaluation corpus (§13.1)."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from event_agent.clients.page_fetcher import FixturePage, SearchHit
from event_agent.schemas import UserPreferences


def default_cases_dir() -> Path:
    # .../services/agent/src/event_agent/evaluation/cases.py からリポジトリルートへ
    return Path(__file__).resolve().parents[5] / "evals" / "cases"


def default_schema_path() -> Path:
    return Path(__file__).resolve().parents[5] / "evals" / "case.schema.json"


@dataclass(frozen=True)
class ExpectedEvent:
    official_url: str
    validation_status: str
    title: str | None = None
    event_start: str | None = None
    event_start_precision: str | None = None
    event_end: str | None = None
    application_deadline: str | None = None
    application_deadline_precision: str = "unknown"
    location_type: str | None = None
    kind: str | None = None
    milestone_labels: tuple[str, ...] = ()
    evidence_required: tuple[str, ...] = ()


@dataclass(frozen=True)
class EvalCase:
    case_id: str
    categories: tuple[str, ...]
    note: str
    clock: datetime
    preferences: UserPreferences
    search_hits: tuple[SearchHit, ...]
    pages: dict[str, FixturePage]
    source_types: dict[str, str]
    expected_events: tuple[ExpectedEvent, ...]
    duplicate_groups: tuple[tuple[str, ...], ...] = ()
    not_produced: tuple[str, ...] = ()
    allowed_fetch_urls: tuple[str, ...] | None = None
    forbidden_values: tuple[str, ...] = ()
    raw: dict[str, Any] = field(default_factory=dict)


def _expected(entry: dict[str, Any]) -> ExpectedEvent:
    return ExpectedEvent(
        official_url=entry["officialUrl"],
        validation_status=entry["validationStatus"],
        title=entry.get("title"),
        event_start=entry.get("eventStart"),
        event_start_precision=entry.get("eventStartPrecision"),
        event_end=entry.get("eventEnd"),
        application_deadline=entry.get("applicationDeadline"),
        application_deadline_precision=entry.get("applicationDeadlinePrecision", "unknown"),
        location_type=entry.get("locationType"),
        kind=entry.get("kind"),
        milestone_labels=tuple(entry.get("milestoneLabels", ())),
        evidence_required=tuple(entry.get("evidenceRequired", ())),
    )


def parse_case(data: dict[str, Any]) -> EvalCase:
    expected = data["expected"]
    return EvalCase(
        case_id=data["caseId"],
        categories=tuple(data["categories"]),
        note=data.get("note", ""),
        clock=datetime.fromisoformat(data["clock"]),
        preferences=UserPreferences(**data["preferences"]),
        search_hits=tuple(
            SearchHit(
                url=hit["url"],
                title=hit.get("title", ""),
                excerpt=hit.get("excerpt", ""),
                query=hit.get("query", ""),
            )
            for hit in data.get("searchHits", [])
        ),
        pages={
            p["url"]: FixturePage(
                body=p["body"],
                status=p.get("status", 200),
                content_type=p.get("contentType", "text/html; charset=utf-8"),
                redirects_to=p.get("redirectsTo"),
            )
            for p in data.get("pages", [])
        },
        source_types={
            p["url"]: p.get("sourceType", "other") for p in data.get("pages", [])
        },
        expected_events=tuple(_expected(e) for e in expected.get("events", [])),
        duplicate_groups=tuple(
            tuple(group) for group in expected.get("duplicateGroups", [])
        ),
        not_produced=tuple(expected.get("notProduced", ())),
        allowed_fetch_urls=(
            tuple(expected["allowedFetchUrls"])
            if "allowedFetchUrls" in expected
            else None
        ),
        forbidden_values=tuple(expected.get("forbiddenValues", ())),
        raw=data,
    )


def load_cases(directory: Path | None = None) -> list[EvalCase]:
    directory = directory or default_cases_dir()
    paths = sorted(directory.glob("*.json"))
    if not paths:
        raise FileNotFoundError(f"no evaluation cases under {directory}")
    return [parse_case(json.loads(p.read_text(encoding="utf-8"))) for p in paths]
