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
    OrganizerPost,
    PostPlacement,
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


def make_post(post_id: str = "post-1", *, origin: str = "organizer", **overrides) -> OrganizerPost:
    event = make_event(post_id, run_id="organizer-posts", url="https://example.com/post")
    fields = {
        "postId": post_id,
        "origin": origin,
        "organizerName": "テスト主催者",
        "contactUrl": "https://example.com/post",
        "title": event.title,
        "body": "開催日: 2026年10月21日 10:00\n申込締切: 2026年10月1日",
        "event": event,
        "evidence": [make_evidence("ev-post", sourceType="organizer")],
        "createdAt": NOW,
        "updatedAt": NOW,
    }
    fields.update(overrides)
    return OrganizerPost(**fields)


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


class TestPool:
    def test_list_recent_events_respects_since(self, store):
        store.save_events("run-1", [make_event("evt-old", url="https://example.com/old", lastSeenAt=NOW - timedelta(days=40))])
        store.save_events("run-2", [make_event("evt-new", url="https://example.com/new", lastSeenAt=NOW - timedelta(days=3))])
        recent = store.list_recent_events(NOW - timedelta(days=30))
        assert [e.event_id for e in recent] == ["evt-new"]

    def test_find_events_by_urls_matches_normalized_url(self, store):
        store.save_events("run-1", [make_event("evt-1", url="https://www.example.com/event/?utm_source=x")])
        found = store.find_events_by_urls(["https://example.com/event"])
        assert list(found) == ["https://example.com/event"]
        assert found["https://example.com/event"].event_id == "evt-1"
        assert store.find_events_by_urls(["https://example.com/other"]) == {}

    def test_touch_events_moves_only_last_seen_at(self, store):
        saved = store.save_events(
            "run-1", [make_event("evt-1", lastExtractedAt=NOW - timedelta(days=2))]
        )[0]
        later = NOW + timedelta(days=1)
        store.touch_events([saved.dedup_key], last_seen_at=later)
        touched = store.get_event("evt-1")
        assert touched.last_seen_at == later
        assert touched.last_extracted_at == NOW - timedelta(days=2)
        assert touched.source_run_id == "run-1"
        assert touched.evidence_ids == ["ev-1"]
        store.touch_events(["missing"], last_seen_at=later)  # 無いものは黙って飛ばす

    def test_get_evidence_for_events_spans_runs(self, store):
        store.save_evidence("run-1", [make_evidence("ev-1")])
        store.save_evidence("run-2", [make_evidence("ev-2", excerpt="別の根拠")])
        store.save_events("run-1", [make_event("evt-1", url="https://example.com/a", evidenceIds=["ev-1"])])
        store.save_events("run-2", [make_event("evt-2", url="https://example.com/b", run_id="run-2", evidenceIds=["ev-2", "ev-missing"])])
        events = [store.get_event("evt-1"), store.get_event("evt-2")]
        by_id = store.get_evidence_for_events(events)
        assert [e.evidence_id for e in by_id["evt-1"]] == ["ev-1"]
        assert [e.evidence_id for e in by_id["evt-2"]] == ["ev-2"]

    def test_latest_collection_at_follows_non_empty_saves(self, store):
        assert store.latest_collection_at() is None
        store.save_events("run-1", [make_event("evt-1")])
        first = store.latest_collection_at()
        assert first is not None
        store.save_events("run-2", [])
        assert store.latest_collection_at() == first
        assert store.list_events() and store.list_events()[0].event_id == "evt-1"


class TestUsage:
    def test_reservation_is_capped_per_day(self, store):
        assert store.get_usage("2026-09-21") is None
        assert store.reserve_grounding_calls("2026-09-21", 4, cap=10)
        assert store.reserve_grounding_calls("2026-09-21", 4, cap=10)
        assert not store.reserve_grounding_calls("2026-09-21", 4, cap=10)
        assert store.get_usage("2026-09-21").grounding_calls == 8
        # 別の日は別の枠
        assert store.reserve_grounding_calls("2026-09-22", 4, cap=10)
        store.record_model_calls("2026-09-21", 3)
        store.record_model_calls("2026-09-21", 2)
        usage = store.get_usage("2026-09-21")
        assert usage.model_calls == 5 and usage.grounding_calls == 8


class TestOrganizerPosts:
    def test_round_trip_keeps_nested_models(self, store):
        saved = store.save_organizer_post(make_post())
        loaded = store.get_organizer_post("post-1")
        assert loaded == saved
        assert loaded.event.dates.event_start == NOW + timedelta(days=30)
        assert loaded.evidence[0].source_type == "organizer"
        assert loaded.placement == PostPlacement()
        assert loaded.status == "published"

    def test_resave_keeps_created_at_and_state(self, store):
        store.save_organizer_post(make_post())
        store.update_post_state(
            "post-1", status="hidden", placement=PostPlacement(kind="pinned")
        )
        later = NOW + timedelta(days=1)
        resaved = store.save_organizer_post(
            make_post(title="改題", createdAt=later, updatedAt=later)
        )
        assert resaved.title == "改題"
        assert resaved.updated_at == later
        assert resaved.created_at == NOW
        assert resaved.status == "hidden"
        assert resaved.placement.kind == "pinned"

    def test_list_filters_by_status(self, store):
        store.save_organizer_post(make_post("post-1"))
        store.save_organizer_post(make_post("post-2"))
        store.update_post_state("post-2", status="hidden")
        assert {p.post_id for p in store.list_organizer_posts()} == {"post-1", "post-2"}
        assert [p.post_id for p in store.list_organizer_posts(status="published")] == ["post-1"]

    def test_update_unknown_post_is_none(self, store):
        assert store.update_post_state("missing", status="hidden") is None


class TestReset:
    def test_reset_clears_everything(self, store):
        store.create_run(make_run())
        store.save_events("run-1", [make_event("evt-1")])
        store.save_evidence("run-1", [make_evidence("ev-1")])
        store.save_organizer_post(make_post())

        store.reset()

        assert store.get_run("run-1") is None
        assert store.list_events() == []
        assert store.get_evidence("run-1", ["ev-1"]) == []
        assert store.list_organizer_posts() == []


class TestMetrics:
    def test_increment_creates_and_accumulates(self, store):
        assert store.get_event_metrics("evt-1") is None
        store.increment_event_metric("evt-1", "official", jst_date="2026-09-21")
        store.increment_event_metric("evt-1", "official", jst_date="2026-09-21")
        store.increment_event_metric("evt-1", "calendar", jst_date="2026-09-22")
        metrics = store.get_event_metrics("evt-1")
        assert metrics.event_id == "evt-1"
        assert metrics.clicks.official == 2 and metrics.clicks.application == 0
        assert metrics.calendar == 1
        assert metrics.daily["2026-09-21"].clicks == 2 and metrics.daily["2026-09-21"].calendar == 0
        assert metrics.daily["2026-09-22"].calendar == 1
        assert metrics.updated_at is not None

    def test_confirmation_is_kept_on_resave(self, store):
        store.save_organizer_post(make_post())
        confirmed = store.update_post_state("post-1", organizer_confirmed=True, now=NOW)
        assert confirmed.organizer_confirmed and confirmed.confirmed_at == NOW
        resaved = store.save_organizer_post(make_post(title="改題"))
        assert resaved.organizer_confirmed and resaved.confirmed_at == NOW
        cleared = store.update_post_state("post-1", organizer_confirmed=False, now=NOW)
        assert not cleared.organizer_confirmed and cleared.confirmed_at is None
