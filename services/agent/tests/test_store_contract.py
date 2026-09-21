"""One contract, both backends (§13.3 Contract と Integration).

Every test here runs twice: once against ``MemoryStore`` in process, and once
against ``FirestoreStore`` talking to the Firestore Emulator. The Firestore
parameter skips itself when ``FIRESTORE_EMULATOR_HOST`` is unset, so ``pytest``
stays runnable without the emulator while ``./scripts/run-integration-tests.sh``
exercises the real client.

Running the same assertions against both is the point: the two backends must be
substitutable, and §9.3's idempotency rules must hold in either.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

import pytest

from event_agent.schemas import (
    AgentRun,
    ApiEvent,
    EventDates,
    EventLocation,
    Evidence,
    GoogleCalendarEventIds,
    Recommendation,
    UserPreferences,
)
from event_agent.storage.store import MemoryStore

JST = timezone(timedelta(hours=9))
NOW = datetime(2026, 9, 21, 9, 0, tzinfo=JST)
EMULATOR_PROJECT = "osaka-hackathon-test"


def _firestore_store():
    from google.cloud import firestore

    from event_agent.storage.firestore_store import FirestoreStore

    client = firestore.Client(project=EMULATOR_PROJECT, database="(default)")
    created = FirestoreStore(client)
    created.reset()
    return created


@pytest.fixture(params=["memory", "firestore"])
def store(request):
    if request.param == "memory":
        return MemoryStore()
    if not os.environ.get("FIRESTORE_EMULATOR_HOST"):
        pytest.skip("FIRESTORE_EMULATOR_HOST is not set; run scripts/run-integration-tests.sh")
    pytest.importorskip("google.cloud.firestore")
    return _firestore_store()


def make_run(run_id: str = "run-1", key: str = "key-1", **overrides) -> AgentRun:
    fields = {
        "runId": run_id,
        "idempotencyKey": key,
        "status": "queued",
        "currentStep": "queued",
        "model": "gemini-2.0-flash",
        "startedAt": NOW,
    }
    fields.update(overrides)
    return AgentRun(**fields)


def make_event(
    event_id: str = "evt-1",
    *,
    title: str = "大阪生成AIハッカソン",
    start: datetime = NOW + timedelta(days=30),
    run_id: str = "run-1",
    score: int = 80,
    url: str = "https://example.com/event",
    **overrides,
) -> ApiEvent:
    fields = {
        "eventId": event_id,
        "title": title,
        "category": "hackathon",
        "summary": "生成AIをテーマにしたハッカソン。",
        "location": EventLocation(type="offline", venue="大阪", region="関西"),
        "dates": EventDates(eventStart=start, timezone="Asia/Tokyo"),
        "officialUrl": url,
        "validationStatus": "verified",
        "confidence": 0.9,
        "evidenceIds": ["ev-1"],
        "recommendation": Recommendation(score=score, reason="関西開催のため。"),
        "firstSeenAt": NOW,
        "lastSeenAt": NOW,
        "sourceRunId": run_id,
    }
    fields.update(overrides)
    return ApiEvent(**fields)


def make_evidence(evidence_id: str = "ev-1", **overrides) -> Evidence:
    fields = {
        "evidenceId": evidence_id,
        "query": "2026 大阪 生成AI ハッカソン 応募締切",
        "sourceUrl": "https://example.com/event",
        "canonicalUrl": "https://example.com/event",
        "sourceType": "official",
        "title": "大阪生成AIハッカソン",
        "excerpt": "応募締切は2026年10月20日",
        "supports": ["title", "dates.eventStart"],
        "retrievedAt": NOW,
        "contentHash": "a" * 64,
    }
    fields.update(overrides)
    return Evidence(**fields)


class TestRuns:
    def test_round_trip(self, store):
        store.create_run(make_run())
        loaded = store.get_run("run-1")
        assert loaded is not None
        assert loaded.status == "queued"
        assert loaded.model == "gemini-2.0-flash"
        assert loaded.idempotency_key == "key-1"

    def test_unknown_run_is_none(self, store):
        assert store.get_run("missing") is None

    def test_update_persists_counters_and_completion(self, store):
        run = store.create_run(make_run())
        run.status = "succeeded"
        run.verified_count = 3
        run.duplicate_count = 2
        run.current_step = "completed"
        run.completed_at = NOW + timedelta(minutes=2)
        store.update_run(run)

        loaded = store.get_run("run-1")
        assert loaded is not None
        assert loaded.status == "succeeded"
        assert loaded.verified_count == 3
        assert loaded.duplicate_count == 2
        assert loaded.completed_at == NOW + timedelta(minutes=2)

    def test_same_idempotency_key_returns_the_first_run(self, store):
        """§9.3: a repeated Idempotency-Key must not start a second run."""
        first = store.create_run(make_run("run-1", "shared-key"))
        second = store.create_run(make_run("run-2", "shared-key"))

        assert second.run_id == first.run_id
        assert store.get_run("run-2") is None

    def test_different_idempotency_keys_are_separate_runs(self, store):
        store.create_run(make_run("run-1", "key-a"))
        store.create_run(make_run("run-2", "key-b"))

        assert store.get_run("run-1") is not None
        assert store.get_run("run-2") is not None


class TestEvents:
    def test_save_and_list_by_run(self, store):
        store.save_events("run-1", [make_event("evt-1"), make_event(
            "evt-2", title="関西AIミートアップ", url="https://example.com/meetup", score=60
        )])

        listed = store.list_events("run-1")
        assert [e.event_id for e in listed] == ["evt-1", "evt-2"]

    def test_list_without_run_id_returns_the_latest_run(self, store):
        store.save_events("run-1", [make_event("evt-1")])
        store.save_events(
            "run-2",
            [make_event("evt-2", title="別イベント", url="https://example.com/other", run_id="run-2")],
        )

        assert [e.event_id for e in store.list_events()] == ["evt-2"]

    def test_list_is_empty_before_anything_is_saved(self, store):
        assert store.list_events() == []
        assert store.list_events("run-1") == []

    def test_results_come_back_in_rank_order(self, store):
        store.save_events(
            "run-1",
            [
                make_event("evt-low", url="https://example.com/a", score=40),
                make_event("evt-high", url="https://example.com/b", score=95),
                make_event("evt-mid", url="https://example.com/c", score=70),
            ],
        )

        assert [e.event_id for e in store.list_events("run-1")] == [
            "evt-high",
            "evt-mid",
            "evt-low",
        ]

    def test_resaving_the_same_event_keeps_its_identity(self, store):
        """§9.3: dedupKey identifies the event, so a second run updates it."""
        store.save_events("run-1", [make_event("evt-1")])
        later = NOW + timedelta(days=1)
        store.save_events(
            "run-2",
            [
                make_event(
                    "evt-regenerated",
                    run_id="run-2",
                    firstSeenAt=later,
                    lastSeenAt=later,
                    confidence=0.95,
                )
            ],
        )

        listed = store.list_events("run-2")
        assert len(listed) == 1
        survivor = listed[0]
        assert survivor.event_id == "evt-1", "the stable id must survive a re-run"
        assert survivor.first_seen_at == NOW, "first sighting must not move forward"
        assert survivor.last_seen_at == later
        assert survivor.confidence == 0.95, "new facts still win"

    def test_resaving_does_not_discard_user_decisions(self, store):
        store.save_events(
            "run-1",
            [
                make_event(
                    "evt-1",
                    status="bookmarked",
                    googleCalendarEventIds=GoogleCalendarEventIds(
                        mainEventId="gcal-main-1"
                    ),
                )
            ],
        )
        store.save_events("run-2", [make_event("evt-1", run_id="run-2")])

        survivor = store.list_events("run-2")[0]
        assert survivor.status == "bookmarked"
        assert survivor.google_calendar_event_ids.main_event_id == "gcal-main-1"

    def test_a_different_year_is_a_different_event(self, store):
        store.save_events("run-1", [make_event("evt-2026")])
        store.save_events(
            "run-1",
            [
                make_event("evt-2026"),
                make_event("evt-2027", start=NOW + timedelta(days=395)),
            ],
        )

        assert len(store.list_events("run-1")) == 2

    def test_get_event_by_id(self, store):
        store.save_events("run-1", [make_event("evt-1")])

        found = store.get_event("evt-1")
        assert found is not None
        assert found.title == "大阪生成AIハッカソン"
        assert store.get_event("missing") is None

    def test_nested_fields_survive_a_round_trip(self, store):
        store.save_events(
            "run-1",
            [
                make_event(
                    "evt-1",
                    location=EventLocation(
                        type="hybrid", venue="グランフロント大阪", region="大阪府",
                        nearestStation="大阪駅",
                    ),
                    dates=EventDates(
                        applicationDeadline=NOW + timedelta(days=10),
                        applicationDeadlinePrecision="date",
                        eventStart=NOW + timedelta(days=30),
                        eventStartPrecision="datetime",
                        eventEnd=NOW + timedelta(days=31),
                        timezone="Asia/Tokyo",
                    ),
                )
            ],
        )

        loaded = store.list_events("run-1")[0]
        assert loaded.location.nearest_station == "大阪駅"
        assert loaded.location.type == "hybrid"
        assert loaded.dates.application_deadline == NOW + timedelta(days=10)
        assert loaded.dates.application_deadline_precision == "date"
        assert loaded.dates.event_end == NOW + timedelta(days=31)
        assert loaded.dates.timezone == "Asia/Tokyo"


class TestEvidence:
    def test_round_trip_preserves_requested_order(self, store):
        store.save_evidence(
            "run-1", [make_evidence("ev-1"), make_evidence("ev-2"), make_evidence("ev-3")]
        )

        loaded = store.get_evidence("run-1", ["ev-3", "ev-1"])
        assert [e.evidence_id for e in loaded] == ["ev-3", "ev-1"]
        assert loaded[0].source_type == "official"
        assert loaded[0].supports == ["title", "dates.eventStart"]
        assert loaded[0].retrieved_at == NOW

    def test_unknown_ids_are_skipped_not_faked(self, store):
        store.save_evidence("run-1", [make_evidence("ev-1")])

        assert [e.evidence_id for e in store.get_evidence("run-1", ["ev-1", "nope"])] == [
            "ev-1"
        ]
        assert store.get_evidence("run-1", []) == []

    def test_evidence_belongs_to_its_run(self, store):
        """§7.2 nests evidence under the run, so ids do not leak across runs."""
        store.save_evidence("run-1", [make_evidence("ev-1")])

        assert store.get_evidence("run-2", ["ev-1"]) == []

    def test_grounding_metadata_survives(self, store):
        from event_agent.schemas import GroundingMetadata

        store.save_evidence(
            "run-1",
            [
                make_evidence(
                    "ev-1",
                    groundingMetadata=GroundingMetadata(chunkIndex=2, supportScore=0.75),
                )
            ],
        )

        loaded = store.get_evidence("run-1", ["ev-1"])[0]
        assert loaded.grounding_metadata is not None
        assert loaded.grounding_metadata.chunk_index == 2
        assert loaded.grounding_metadata.support_score == 0.75


class TestSessions:
    def test_new_session_gets_an_id(self, store):
        session = store.get_or_create_session(None)
        assert session.session_id

    def test_preferences_and_messages_round_trip(self, store):
        session = store.get_or_create_session(None)
        session.preferences = UserPreferences(
            interestsPrompt="Rust、組込み", targetYear=2027,
            onlineAllowed=False, locations=["関東"],
        )
        session.messages = [{"role": "user", "content": "探して"}]
        store.save_session(session)

        loaded = store.get_or_create_session(session.session_id)
        assert loaded.session_id == session.session_id
        assert loaded.preferences.interests_prompt == "Rust、組込み"
        assert loaded.preferences.target_year == 2027
        assert loaded.preferences.online_allowed is False
        assert loaded.preferences.locations == ["関東"]
        assert loaded.messages == [{"role": "user", "content": "探して"}]

    def test_unknown_session_id_starts_a_fresh_session(self, store):
        session = store.get_or_create_session("never-seen")
        assert session.messages == []


class TestReset:
    def test_reset_clears_everything(self, store):
        store.create_run(make_run())
        store.save_events("run-1", [make_event("evt-1")])
        store.save_evidence("run-1", [make_evidence("ev-1")])

        store.reset()

        assert store.get_run("run-1") is None
        assert store.list_events() == []
        assert store.get_evidence("run-1", ["ev-1"]) == []
