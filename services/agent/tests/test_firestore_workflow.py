"""The §6 workflow, end to end, on Firestore (§13.3 Integration).

tests/test_store_contract.py proves the backend honours the store contract.
This file proves the thing that actually matters: the collection workflow and
the API produce the same result when the store underneath them is Firestore
rather than the in-process dictionary. It is skipped without the emulator; run
it with ./scripts/run-integration-tests.sh tests/test_firestore_workflow.py.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

import pytest

from event_agent.schemas import UserPreferences

JST = timezone(timedelta(hours=9))
NOW = datetime(2026, 9, 21, 9, 0, tzinfo=JST)
EMULATOR_PROJECT = "osaka-hackathon-test"

# Every module binds ``store`` at import time, so the swap has to reach all of
# them; patching only event_agent.store would leave the workflow on memory.
STORE_HOLDERS = (
    "event_agent.store",
    "event_agent.workflows.collect",
    "event_agent.entrypoints.service",
    "event_agent.agents.chat",
    "event_agent.evaluation.harness",
)


@pytest.fixture
def firestore_store(monkeypatch):
    if not os.environ.get("FIRESTORE_EMULATOR_HOST"):
        pytest.skip("FIRESTORE_EMULATOR_HOST is not set; run scripts/run-integration-tests.sh")
    pytest.importorskip("google.cloud.firestore")
    from google.cloud import firestore

    from event_agent.firestore_store import FirestoreStore

    backend = FirestoreStore(firestore.Client(project=EMULATOR_PROJECT, database="(default)"))
    backend.reset()
    for module in STORE_HOLDERS:
        monkeypatch.setattr(f"{module}.store", backend)
    yield backend
    backend.reset()


@pytest.mark.asyncio
async def test_workflow_persists_run_events_and_evidence(firestore_store):
    from event_agent.workflows.collect import run_collect_workflow

    run = await run_collect_workflow(UserPreferences(), True, now=NOW)

    assert run.status in ("succeeded", "partial_success")

    persisted = firestore_store.get_run(run.run_id)
    assert persisted is not None, "the run must outlive the process"
    assert persisted.status == run.status
    assert persisted.current_step == "completed"
    assert persisted.completed_at is not None
    assert persisted.candidate_count > 0

    events = firestore_store.list_events(run.run_id)
    assert events, "a demo-mode run always produces candidates"
    for event in events:
        assert event.source_run_id == run.run_id
        assert event.official_url, "§6.6 requires a source URL on every event"
        assert event.dedup_key

    evidence = firestore_store.get_evidence(run.run_id, events[0].evidence_ids)
    assert len(evidence) == len(events[0].evidence_ids)
    assert all(item.source_url for item in evidence)


@pytest.mark.asyncio
async def test_rerunning_keeps_event_identity(firestore_store):
    """§9.3: the second run updates the same documents, it does not fork them."""
    from event_agent.workflows.collect import run_collect_workflow

    first = await run_collect_workflow(UserPreferences(), True, now=NOW)
    first_events = firestore_store.list_events(first.run_id)
    ids_by_key = {e.dedup_key: e.event_id for e in first_events}
    first_seen = {e.dedup_key: e.first_seen_at for e in first_events}

    second = await run_collect_workflow(
        UserPreferences(), True, now=NOW + timedelta(days=1)
    )
    assert second.run_id != first.run_id

    second_events = firestore_store.list_events(second.run_id)
    assert {e.dedup_key for e in second_events} == set(ids_by_key)
    for event in second_events:
        assert event.event_id == ids_by_key[event.dedup_key]
        assert event.first_seen_at == first_seen[event.dedup_key]


def test_api_reads_back_what_the_workflow_wrote(firestore_store):
    from fastapi.testclient import TestClient

    from event_agent.entrypoints.service import app

    client = TestClient(app)

    started = client.post("/api/agent-runs", json={"forceRefresh": True})
    assert started.status_code == 200
    run_id = started.json()["runId"]

    # TestClient runs the app's loop only for the duration of a request, so the
    # background task finishes during the following calls rather than at once.
    status = client.get(f"/api/agent-runs/{run_id}")
    assert status.status_code == 200
    assert status.json()["runId"] == run_id

    assert firestore_store.get_run(run_id) is not None


def test_repeated_idempotency_key_returns_the_same_run(firestore_store):
    """§9.3: a retried POST must not launch a second collection."""
    from fastapi.testclient import TestClient

    from event_agent.entrypoints.service import app

    client = TestClient(app)
    headers = {"Idempotency-Key": "client-key-42"}

    first = client.post("/api/agent-runs", json={"forceRefresh": False}, headers=headers)
    second = client.post("/api/agent-runs", json={"forceRefresh": False}, headers=headers)

    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json()["runId"] == first.json()["runId"]


def test_evidence_endpoint_serves_firestore_documents(firestore_store):
    import asyncio

    from fastapi.testclient import TestClient

    from event_agent.entrypoints.service import app
    from event_agent.workflows.collect import run_collect_workflow

    run = asyncio.run(run_collect_workflow(UserPreferences(), True, now=NOW))
    events = [
        e
        for e in firestore_store.list_events(run.run_id)
        if e.validation_status in ("verified", "partial") and e.evidence_ids
    ]
    assert events, "the run must leave at least one displayable event with evidence"

    client = TestClient(app)
    response = client.get(f"/api/events/{events[0].event_id}/evidence")

    assert response.status_code == 200
    body = response.json()
    assert body["eventId"] == events[0].event_id
    assert len(body["evidence"]) == len(events[0].evidence_ids)
    assert all(item["sourceUrl"] for item in body["evidence"])
