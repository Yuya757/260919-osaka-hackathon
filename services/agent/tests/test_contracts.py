"""Validate live API responses against packages/contracts/schemas/*.json.

The backend models once drifted from these schemas without anything failing:
``GET /api/events`` was returning objects that the project's own ``event.json``
would have rejected (8 required fields missing, plus an undeclared ``source``).
These tests close that gap, so a model change that breaks the contract breaks
the build instead.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator
from referencing import Registry, Resource

from event_agent.entrypoints.service import app

SCHEMA_DIR = Path(__file__).resolve().parents[3] / "packages" / "contracts" / "schemas"


def _registry() -> Registry:
    """Every schema document by its ``$id`` so cross-file ``$ref`` resolves.

    ``organizer-post.json`` refers to ``event.json#/$defs/Event``; without a
    registry jsonschema would try to fetch ``https://event-agent.local/…``.
    """
    registry: Registry = Registry()
    for path in SCHEMA_DIR.glob("*.json"):
        document = json.loads(path.read_text(encoding="utf-8"))
        registry = registry.with_resource(
            document["$id"], Resource.from_contents(document)
        )
    return registry


def _validator(schema_file: str, definition: str) -> Draft202012Validator:
    document = json.loads((SCHEMA_DIR / schema_file).read_text(encoding="utf-8"))
    schema = dict(document["$defs"][definition])
    schema["$defs"] = document["$defs"]
    # 同一文書内の "#/$defs/…" と他文書への "event.json#/…" の両方を解決するため、
    # 定義を切り出したスキーマにも元の $id を持たせる。
    schema["$id"] = document["$id"]
    return Draft202012Validator(schema, registry=_registry())


def _assert_valid(validator: Draft202012Validator, payload: object, label: str) -> None:
    errors = sorted(validator.iter_errors(payload), key=lambda e: list(e.absolute_path))
    if errors:
        detail = "\n".join(
            f"  {'/'.join(str(p) for p in e.absolute_path) or '<root>'}: {e.message}"
            for e in errors
        )
        pytest.fail(f"{label} does not conform to its schema:\n{detail}")


@pytest.fixture(scope="module")
def client():
    """Context-managed so the portal's event loop survives between requests.

    Without ``with``, TestClient spins up a fresh loop per request and the
    background task started by ``POST /api/chat`` is abandoned mid-run.
    """
    with TestClient(app) as test_client:
        yield test_client


TERMINAL = {"succeeded", "partial_success", "failed", "cancelled"}


@pytest.fixture(scope="module")
def finished_run(client: TestClient) -> str:
    """Start a run and poll it to completion, the way the web client does."""
    created = client.post("/api/chat", json={"message": "関西の生成AIハッカソンを探して"})
    assert created.status_code == 200
    actions = created.json().get("actions", [])
    run_ids = [a["runId"] for a in actions if a["type"] == "agent_run_started"]
    assert run_ids, "chat did not start an agent run"
    run_id = run_ids[0]

    for _ in range(200):
        response = client.get(f"/api/agent-runs/{run_id}")
        assert response.status_code == 200
        body = response.json()
        if body["status"] in TERMINAL:
            assert body["status"] != "failed", body.get("errorMessage")
            return run_id
        time.sleep(0.05)
    pytest.fail("agent run did not finish in time")


def test_schema_catalog_paths_exist() -> None:
    index = json.loads((SCHEMA_DIR / "index.json").read_text(encoding="utf-8"))
    for entry in index["schemas"]:
        path = SCHEMA_DIR / entry["path"]
        assert path.exists(), f"{entry['id']} points at missing {entry['path']}"
        document = json.loads(path.read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(document)
        for name in entry["definitions"]:
            assert name in document["$defs"], f"{entry['path']} lacks $defs/{name}"


def test_chat_response_conforms(client: TestClient) -> None:
    response = client.post("/api/chat", json={"message": "オンラインのミートアップも入れて"})
    assert response.status_code == 200
    _assert_valid(_validator("chat.json", "ChatResponse"), response.json(), "ChatResponse")


def test_agent_run_conforms(client: TestClient, finished_run: str) -> None:
    response = client.get(f"/api/agent-runs/{finished_run}")
    assert response.status_code == 200
    _assert_valid(_validator("agent-run.json", "AgentRun"), response.json(), "AgentRun")


def test_event_list_conforms(client: TestClient, finished_run: str) -> None:
    response = client.get("/api/events", params={"sourceRunId": finished_run})
    assert response.status_code == 200
    body = response.json()
    assert body["events"], "run produced no events to validate"
    _assert_valid(
        _validator("event.json", "EventListResponse"), body, "EventListResponse"
    )


def test_evidence_conforms(client: TestClient, finished_run: str) -> None:
    events = client.get("/api/events", params={"sourceRunId": finished_run}).json()
    with_evidence = [e for e in events["events"] if e["evidenceIds"]]
    assert with_evidence, "no event carried evidence ids"
    for event in with_evidence:
        response = client.get(f"/api/events/{event['eventId']}/evidence")
        assert response.status_code == 200
        body = response.json()
        _assert_valid(
            _validator("evidence.json", "EvidenceListResponse"),
            body,
            f"evidence for {event['eventId']}",
        )
        returned = {item["evidenceId"] for item in body["evidence"]}
        assert returned == set(event["evidenceIds"]), (
            f"{event['eventId']} evidence ids do not match the event document"
        )


def test_only_displayable_events_are_returned(client: TestClient, finished_run: str) -> None:
    """quarantined / rejected must never reach the normal UI (§8.3)."""
    events = client.get("/api/events", params={"sourceRunId": finished_run}).json()
    statuses = {e["validationStatus"] for e in events["events"]}
    assert statuses <= {"verified", "partial"}, statuses


def test_required_field_evidence_coverage(client: TestClient, finished_run: str) -> None:
    """§13.2: title と dates.eventStart には必ず根拠が付く。"""
    events = client.get("/api/events", params={"sourceRunId": finished_run}).json()
    for event in events["events"]:
        evidence = client.get(f"/api/events/{event['eventId']}/evidence").json()
        supported: set[str] = set()
        for item in evidence["evidence"]:
            supported.update(item["supports"])
        assert {"title", "dates.eventStart"} <= supported, (
            f"{event['eventId']} lacks evidence for title/eventStart: {supported}"
        )


def test_confidence_is_not_model_self_reported(client: TestClient, finished_run: str) -> None:
    """§7.5: confidence はアプリ側算出。verified は閾値以上であること。"""
    from event_agent.config import settings

    events = client.get("/api/events", params={"sourceRunId": finished_run}).json()
    for event in events["events"]:
        assert 0.0 <= event["confidence"] <= 1.0
        if event["validationStatus"] == "verified":
            assert event["confidence"] >= settings.verified_confidence_threshold


def test_unknown_deadline_stays_null(client: TestClient, finished_run: str) -> None:
    """§6.6: 締切が不明なら null のまま。推測した値を入れてはならない。"""
    events = client.get("/api/events", params={"sourceRunId": finished_run}).json()
    for event in events["events"]:
        dates = event["dates"]
        if dates.get("applicationDeadline") is None:
            assert dates["applicationDeadlinePrecision"] == "unknown"
            assert event["validationStatus"] == "partial"


# ------------------------------------------------------------ organizer posts

POST_BODY = {
    "organizerName": "関西イノベーションセンター",
    "contactUrl": "https://kansai-innovation.example.jp/hackathon2026",
    "title": "関西 Generative AI Hackathon 2026",
    "body": "開催日: 2026年10月16日 10:00\n申込締切: 2026年9月30日 23:59\n会場: グランフロント大阪",
}


def test_organizer_post_preview_conforms(client: TestClient) -> None:
    response = client.post("/api/organizer-posts/preview", json=POST_BODY)
    assert response.status_code == 200
    _assert_valid(
        _validator("organizer-post.json", "OrganizerPostPreviewResponse"),
        response.json(),
        "OrganizerPostPreviewResponse",
    )


def test_organizer_post_create_conforms(client: TestClient) -> None:
    response = client.post("/api/organizer-posts", json=POST_BODY)
    assert response.status_code == 201
    _assert_valid(
        _validator("organizer-post.json", "OrganizerPostCreateResponse"),
        response.json(),
        "OrganizerPostCreateResponse",
    )


def test_organizer_post_feed_conforms(client: TestClient, finished_run: str) -> None:
    """finished_run のボット投稿と、上で作った主催者投稿が両方載る。"""
    response = client.get("/api/organizer-posts")
    assert response.status_code == 200
    body = response.json()
    assert body["posts"], "feed is empty even after a finished run"
    _assert_valid(
        _validator("organizer-post.json", "OrganizerPostListResponse"),
        body,
        "OrganizerPostListResponse",
    )
    for post in body["posts"]:
        assert post["status"] == "published"
        assert post["event"]["validationStatus"] in ("verified", "partial")
