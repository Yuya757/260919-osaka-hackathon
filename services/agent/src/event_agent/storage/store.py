"""Persistence for sessions, runs, events and evidence.

Two backends implement :class:`Store`. ``MemoryStore`` keeps everything in the
process and is what the demo, the unit tests and the evaluation harness use.
``FirestoreStore`` (``event_agent.storage.firestore_store``) writes the collections
described in §7 and is selected when ``FIRESTORE_ENABLED`` is set.

Both backends share the idempotency rules of §9.3, which live here as free
functions so the two implementations cannot drift:

- a run is identified by its ``idempotencyKey``; creating a run twice with the
  same key returns the first run instead of starting a second one;
- an event is identified by its ``dedupKey``; re-saving one keeps the identity
  and the user's own state, and only moves ``lastSeenAt`` forward;
- an organizer post is identified by its ``postId`` (derived from the same
  ``dedupKey``); re-saving one keeps ``createdAt`` and the moderation and
  placement state, which the poster must not be able to reset.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from threading import Lock
from typing import Protocol
from uuid import uuid4

from event_agent.domain.organizer_edit import apply_organizer_edit
from event_agent.schemas import (
    AgentRun,
    EventClaim,
    WatchedPage,
    ApiEvent,
    Evidence,
    EventMetrics,
    MetricCounts,
    OrganizerPost,
    PostPlacement,
    SearchActivity,
    UsageRecord,
    UserPreferences,
)


@dataclass
class SessionState:
    session_id: str
    preferences: UserPreferences = field(default_factory=UserPreferences)
    messages: list[dict[str, str]] = field(default_factory=list)
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


def merge_saved_event(incoming: ApiEvent, existing: ApiEvent | None) -> ApiEvent:
    """Fold a freshly collected event into what is already stored (§9.3).

    The incoming event carries the newer facts, so it wins on dates, evidence
    and ranking. What it must not do is reset identity or overwrite the user:
    ``eventId`` and ``firstSeenAt`` are what the UI and Calendar entries point
    at, and ``status``/``googleCalendarEventIds`` record decisions the user
    made. A re-run that clobbered those would un-bookmark saved events.
    """
    if existing is None:
        return apply_organizer_edit(incoming)
    # 主催者が直した値（ADR-013）は再収集で消さない。新しい編集があればそちらを使う
    return apply_organizer_edit(
        incoming.model_copy(
            update={
                "event_id": existing.event_id,
                "first_seen_at": existing.first_seen_at,
                "status": existing.status,
                "google_calendar_event_ids": existing.google_calendar_event_ids,
                "organizer_edit": incoming.organizer_edit or existing.organizer_edit,
            }
        )
    )


def display_order(events: list[ApiEvent]) -> list[ApiEvent]:
    """Rank order (§6.8) with a stable tiebreak.

    ``MemoryStore`` could return insertion order, but Firestore queries come
    back in document-id order, so both backends sort explicitly here. Without
    the ``eventId`` tiebreak the two would disagree whenever two events score
    the same, and the store contract test could not compare them.
    """
    return sorted(
        events,
        key=lambda e: (
            -(e.recommendation.score if e.recommendation else 0),
            e.event_id,
        ),
    )


def merge_saved_post(incoming: OrganizerPost, existing: OrganizerPost | None) -> OrganizerPost:
    """Fold a re-submitted post into what is already stored (ADR-006).

    The text and the derived event may change, so the incoming post wins on
    those. ``createdAt`` keeps the feed order stable, and ``status`` /
    ``placement`` are moderation and sponsorship state that a repeated submit
    must not be able to reset.
    """
    if existing is None:
        return incoming
    return incoming.model_copy(
        update={
            "created_at": existing.created_at,
            "status": existing.status,
            "placement": existing.placement,
            # 主催者確認は管理者の判断。再投稿やボットの再投稿で戻らない（ADR-009）
            "organizer_confirmed": existing.organizer_confirmed,
            "confirmed_at": existing.confirmed_at,
        }
    )


def _with_state(
    post: OrganizerPost,
    *,
    status: str | None,
    placement: PostPlacement | None,
    organizer_confirmed: bool | None = None,
    now: datetime | None = None,
) -> OrganizerPost:
    now = now or datetime.now(timezone.utc)
    update: dict[str, object] = {"updated_at": now}
    if status is not None:
        update["status"] = status
    if placement is not None:
        update["placement"] = placement
    if organizer_confirmed is not None:
        update["organizer_confirmed"] = organizer_confirmed
        update["confirmed_at"] = now if organizer_confirmed else None
    return post.model_copy(update=update)


def _bump_metrics(current: EventMetrics | None, event_id: str, kind: str, *, jst_date: str, now: datetime) -> EventMetrics:
    """メモリ側の加算。Firestore 側は Increment で同じ形にする。"""
    metrics = current or EventMetrics(eventId=event_id)
    day = metrics.daily.get(jst_date, MetricCounts())
    if kind == "calendar":
        metrics = metrics.model_copy(update={"calendar": metrics.calendar + 1})
        day = day.model_copy(update={"calendar": day.calendar + 1})
    else:
        clicks = metrics.clicks.model_copy(update={kind: getattr(metrics.clicks, kind) + 1})
        metrics = metrics.model_copy(update={"clicks": clicks})
        day = day.model_copy(update={"clicks": day.clicks + 1})
    return metrics.model_copy(update={"daily": {**metrics.daily, jst_date: day}, "updated_at": now})


_PLACEMENT_RANK = {"pinned": 0, "priority": 1, "normal": 2}


def effective_placement(post: OrganizerPost, now: datetime) -> PostPlacement:
    """A pinned or priority slot whose ``until`` has passed counts as normal."""
    placement = post.placement
    if placement.kind != "normal" and placement.until is not None and placement.until <= now:
        return PostPlacement(kind="normal", until=None)
    return placement


def feed_order(posts: list[OrganizerPost], *, now: datetime) -> list[OrganizerPost]:
    """Feed order: pinned, then priority, then newest first.

    Sorted here rather than in the query so that both backends agree and so
    that Firestore needs no composite index (ADR-002).
    """
    return sorted(
        posts,
        key=lambda p: (
            _PLACEMENT_RANK[effective_placement(p, now).kind],
            -p.created_at.timestamp(),
            p.post_id,
        ),
    )


class Store(Protocol):
    """The persistence surface the workflow and the API depend on."""

    def reset(self) -> None:
        """Drop all state. Only for tests and between evaluation cases."""

    def get_or_create_session(self, session_id: str | None) -> SessionState: ...

    def save_session(self, session: SessionState) -> None: ...

    def create_run(self, run: AgentRun) -> AgentRun:
        """Persist a queued run, or return the run that already holds its key.

        Callers must compare ``run_id`` on the result: a different id means the
        run already existed and no new workflow should be started (§9.3).
        """

    def update_run(self, run: AgentRun) -> AgentRun: ...

    def get_run(self, run_id: str) -> AgentRun | None: ...

    def save_events(self, run_id: str, events: list[ApiEvent]) -> list[ApiEvent]:
        """Upsert by ``dedupKey`` and return what is now stored, in order."""

    def save_evidence(self, run_id: str, evidence: list[Evidence]) -> None: ...

    def get_evidence(self, run_id: str, evidence_ids: list[str]) -> list[Evidence]:
        """Evidence lives under the run that collected it (§7.2), so the run id
        is required; an event's ``evidenceIds`` always belong to its
        ``sourceRunId`` because deduplication only merges within one run."""

    def get_event(self, event_id: str) -> ApiEvent | None: ...

    def list_events(self, source_run_id: str | None = None) -> list[ApiEvent]:
        """Events of one run, or of the most recent run when no id is given."""

    def list_recent_events(self, since: datetime, *, limit: int = 500) -> list[ApiEvent]:
        """The shared pool (ADR-008): events seen since ``since``, unordered."""

    def find_events_by_urls(self, normalized_urls: list[str]) -> dict[str, ApiEvent]:
        """Known-page lookup keyed by ``normalizedOfficialUrl``."""

    def touch_events(self, dedup_keys: list[str], *, last_seen_at: datetime) -> None:
        """Move ``lastSeenAt`` only. Evidence, run id and ``lastExtractedAt`` stay."""

    def get_evidence_for_events(self, events: list[ApiEvent]) -> dict[str, list[Evidence]]:
        """Evidence for many events in one round trip, keyed by ``eventId``."""

    def latest_collection_at(self) -> datetime | None:
        """When the most recent run saved its events (``appState/latestRun``)."""

    def save_organizer_post(self, post: OrganizerPost) -> OrganizerPost:
        """Upsert by ``postId`` and return what is now stored."""

    def get_organizer_post(self, post_id: str) -> OrganizerPost | None: ...

    def list_organizer_posts(self, status: str | None = None) -> list[OrganizerPost]:
        """All posts, or only those with the given status. Unordered."""

    def update_post_state(
        self,
        post_id: str,
        *,
        status: str | None = None,
        placement: PostPlacement | None = None,
        organizer_confirmed: bool | None = None,
        now: datetime | None = None,
    ) -> OrganizerPost | None:
        """Moderation, sponsorship and confirmation state. The only way to change
        any of them: a re-submitted post keeps them (see :func:`merge_saved_post`).
        Reached through ``entrypoints/admin.py``, not the public API (ADR-009)."""

    def increment_event_metric(self, event_id: str, kind: str, *, jst_date: str) -> None:
        """Count one click (official/application/contact) or calendar registration."""

    def get_event_metrics(self, event_id: str) -> EventMetrics | None: ...

    def list_calendar_counts(self) -> dict[str, int]:
        """Calendar registrations per event, omitting events with none."""

    def reserve_grounding_calls(self, day: str, count: int, *, cap: int) -> bool:
        """Claim ``count`` searches against the day's cap (ADR-008 決定5).

        Atomic: two runs cannot both succeed past the cap. Returns False and
        reserves nothing when the cap would be exceeded.
        """

    def save_watched_page(self, page: WatchedPage) -> WatchedPage: ...

    def get_watched_page(self, watch_id: str) -> WatchedPage | None: ...

    def list_watched_pages(self, *, limit: int = 100) -> list[WatchedPage]:
        """Active pages, least recently checked first."""

    def reserve_quota(self, key: str, *, cap: int) -> bool:
        """Take one from a named counter capped at ``cap`` (e.g. ``web-search:2026-09-24:<session>``).

        Atomic like :meth:`reserve_grounding_calls`. False when the cap is reached."""

    def record_model_calls(self, day: str, count: int) -> None:
        """Add text-generation calls to the day's usage. Not capped here."""

    def get_usage(self, day: str) -> UsageRecord | None: ...

    def update_event(self, event: ApiEvent) -> ApiEvent:
        """Overwrite one stored event in place (organizer edits, ADR-013).

        Goes through :func:`merge_saved_event` like a collected event, but does
        not move the latest-run pointer: an edit is not a collection."""

    def save_claim(self, claim: EventClaim) -> EventClaim: ...

    def get_claim(self, claim_id: str) -> EventClaim | None: ...

    def save_search_activity(self, search_id: str, lines: list[SearchActivity]) -> None:
        """Replace the activity of an in-flight pool search (ADR-010).

        Written after every line so that another instance can serve the
        polling reads while the search request is still open."""

    def get_search_activity(self, search_id: str) -> list[SearchActivity] | None:
        """None until the search has written its first line."""

    # 検索グラウンディング由来のデータを消す管理コマンド（ADR-014）だけが使う
    def list_all_events(self) -> list[ApiEvent]: ...

    def list_claims(self) -> list[EventClaim]: ...

    def delete_events(self, dedup_keys: list[str]) -> None: ...

    def delete_runs(self, run_ids: list[str]) -> None:
        """Delete the runs together with their evidence and idempotency keys."""

    def delete_organizer_posts(self, post_ids: list[str]) -> None: ...

    def delete_claims(self, claim_ids: list[str]) -> None: ...


class MemoryStore:
    def __init__(self) -> None:
        self._lock = Lock()
        self._sessions: dict[str, SessionState] = {}
        self._runs: dict[str, AgentRun] = {}
        self._runs_by_key: dict[str, str] = {}
        self._events_by_run: dict[str, list[str]] = {}
        self._events_by_dedup_key: dict[str, ApiEvent] = {}
        self._latest_run_id: str | None = None
        self._latest_saved_at: datetime | None = None
        self._evidence: dict[tuple[str, str], Evidence] = {}
        self._posts: dict[str, OrganizerPost] = {}
        self._metrics: dict[str, EventMetrics] = {}
        self._usage: dict[str, UsageRecord] = {}
        self._search_activity: dict[str, list[SearchActivity]] = {}
        self._claims: dict[str, EventClaim] = {}
        self._quotas: dict[str, int] = {}
        self._watched: dict[str, WatchedPage] = {}

    def reset(self) -> None:
        with self._lock:
            self._sessions.clear()
            self._runs.clear()
            self._runs_by_key.clear()
            self._events_by_run.clear()
            self._events_by_dedup_key.clear()
            self._latest_run_id = None
            self._latest_saved_at = None
            self._evidence.clear()
            self._posts.clear()
            self._metrics.clear()
            self._usage.clear()
            self._search_activity.clear()
            self._claims.clear()
            self._quotas.clear()
            self._watched.clear()

    def get_or_create_session(self, session_id: str | None) -> SessionState:
        with self._lock:
            if session_id and session_id in self._sessions:
                return self._sessions[session_id]
            created = SessionState(session_id=session_id or str(uuid4()))
            self._sessions[created.session_id] = created
            return created

    def save_session(self, session: SessionState) -> None:
        with self._lock:
            session.updated_at = datetime.now(timezone.utc)
            self._sessions[session.session_id] = session

    def create_run(self, run: AgentRun) -> AgentRun:
        with self._lock:
            existing_id = self._runs_by_key.get(run.idempotency_key)
            if existing_id and existing_id in self._runs:
                return self._runs[existing_id]
            self._runs[run.run_id] = run
            self._runs_by_key[run.idempotency_key] = run.run_id
            return run

    def update_run(self, run: AgentRun) -> AgentRun:
        with self._lock:
            self._runs[run.run_id] = run
            return run

    def get_run(self, run_id: str) -> AgentRun | None:
        with self._lock:
            return self._runs.get(run_id)

    def save_events(self, run_id: str, events: list[ApiEvent]) -> list[ApiEvent]:
        with self._lock:
            stored: list[ApiEvent] = []
            for event in events:
                merged = merge_saved_event(
                    event, self._events_by_dedup_key.get(event.dedup_key)
                )
                self._events_by_dedup_key[merged.dedup_key] = merged
                stored.append(merged)
            self._events_by_run[run_id] = [e.dedup_key for e in stored]
            # 空の保存で「最新の Run」を進めない（検索を省いた Run が一覧を空にしないため）
            if stored:
                self._latest_run_id = run_id
                self._latest_saved_at = datetime.now(timezone.utc)
            return stored

    def save_evidence(self, run_id: str, evidence: list[Evidence]) -> None:
        with self._lock:
            for item in evidence:
                self._evidence[(run_id, item.evidence_id)] = item

    def get_evidence(self, run_id: str, evidence_ids: list[str]) -> list[Evidence]:
        with self._lock:
            return [
                self._evidence[(run_id, eid)]
                for eid in evidence_ids
                if (run_id, eid) in self._evidence
            ]

    def get_event(self, event_id: str) -> ApiEvent | None:
        with self._lock:
            for event in self._events_by_dedup_key.values():
                if event.event_id == event_id:
                    return event
            return None

    def list_events(self, source_run_id: str | None = None) -> list[ApiEvent]:
        with self._lock:
            run_id = source_run_id or self._latest_run_id
            if run_id is None:
                return []
            return display_order(
                [
                    self._events_by_dedup_key[key]
                    for key in self._events_by_run.get(run_id, [])
                    if key in self._events_by_dedup_key
                ]
            )

    def list_recent_events(self, since: datetime, *, limit: int = 500) -> list[ApiEvent]:
        with self._lock:
            return [
                e for e in self._events_by_dedup_key.values() if e.last_seen_at >= since
            ][:limit]

    def find_events_by_urls(self, normalized_urls: list[str]) -> dict[str, ApiEvent]:
        wanted = set(normalized_urls)
        with self._lock:
            return {
                e.normalized_official_url: e
                for e in self._events_by_dedup_key.values()
                if e.normalized_official_url in wanted
            }

    def touch_events(self, dedup_keys: list[str], *, last_seen_at: datetime) -> None:
        with self._lock:
            for key in dedup_keys:
                existing = self._events_by_dedup_key.get(key)
                if existing is not None:
                    self._events_by_dedup_key[key] = existing.model_copy(
                        update={"last_seen_at": last_seen_at}
                    )

    def get_evidence_for_events(self, events: list[ApiEvent]) -> dict[str, list[Evidence]]:
        with self._lock:
            return {
                e.event_id: [
                    self._evidence[(e.source_run_id, eid)]
                    for eid in e.evidence_ids
                    if (e.source_run_id, eid) in self._evidence
                ]
                for e in events
            }

    def latest_collection_at(self) -> datetime | None:
        with self._lock:
            return self._latest_saved_at

    def save_watched_page(self, page: WatchedPage) -> WatchedPage:
        with self._lock:
            self._watched[page.watch_id] = page
            return page

    def get_watched_page(self, watch_id: str) -> WatchedPage | None:
        with self._lock:
            return self._watched.get(watch_id)

    def list_watched_pages(self, *, limit: int = 100) -> list[WatchedPage]:
        with self._lock:
            active = [p for p in self._watched.values() if p.active]
        oldest = datetime.min.replace(tzinfo=timezone.utc)
        return sorted(active, key=lambda p: (p.last_checked_at or oldest, p.watch_id))[:limit]

    def reserve_quota(self, key: str, *, cap: int) -> bool:
        with self._lock:
            used = self._quotas.get(key, 0)
            if used + 1 > cap:
                return False
            self._quotas[key] = used + 1
            return True

    def reserve_grounding_calls(self, day: str, count: int, *, cap: int) -> bool:
        with self._lock:
            current = self._usage.get(day) or UsageRecord(day=day)
            if current.grounding_calls + count > cap:
                return False
            self._usage[day] = current.model_copy(
                update={
                    "grounding_calls": current.grounding_calls + count,
                    "updated_at": datetime.now(timezone.utc),
                }
            )
            return True

    def record_model_calls(self, day: str, count: int) -> None:
        with self._lock:
            current = self._usage.get(day) or UsageRecord(day=day)
            self._usage[day] = current.model_copy(
                update={
                    "model_calls": current.model_calls + count,
                    "updated_at": datetime.now(timezone.utc),
                }
            )

    def get_usage(self, day: str) -> UsageRecord | None:
        with self._lock:
            return self._usage.get(day)

    def update_event(self, event: ApiEvent) -> ApiEvent:
        with self._lock:
            merged = merge_saved_event(event, self._events_by_dedup_key.get(event.dedup_key))
            self._events_by_dedup_key[merged.dedup_key] = merged
            return merged

    def save_claim(self, claim: EventClaim) -> EventClaim:
        with self._lock:
            self._claims[claim.claim_id] = claim
            return claim

    def get_claim(self, claim_id: str) -> EventClaim | None:
        with self._lock:
            return self._claims.get(claim_id)

    def save_search_activity(self, search_id: str, lines: list[SearchActivity]) -> None:
        with self._lock:
            self._search_activity[search_id] = list(lines)

    def get_search_activity(self, search_id: str) -> list[SearchActivity] | None:
        with self._lock:
            lines = self._search_activity.get(search_id)
            return list(lines) if lines is not None else None

    def list_all_events(self) -> list[ApiEvent]:
        with self._lock:
            return list(self._events_by_dedup_key.values())

    def list_claims(self) -> list[EventClaim]:
        with self._lock:
            return list(self._claims.values())

    def delete_events(self, dedup_keys: list[str]) -> None:
        with self._lock:
            for key in dedup_keys:
                self._events_by_dedup_key.pop(key, None)

    def delete_runs(self, run_ids: list[str]) -> None:
        doomed = set(run_ids)
        with self._lock:
            for run_id in doomed:
                run = self._runs.pop(run_id, None)
                if run is not None and self._runs_by_key.get(run.idempotency_key) == run_id:
                    del self._runs_by_key[run.idempotency_key]
                self._events_by_run.pop(run_id, None)
            for key in [k for k in self._evidence if k[0] in doomed]:
                del self._evidence[key]
            if self._latest_run_id in doomed:
                self._latest_run_id = None

    def delete_organizer_posts(self, post_ids: list[str]) -> None:
        with self._lock:
            for post_id in post_ids:
                self._posts.pop(post_id, None)

    def delete_claims(self, claim_ids: list[str]) -> None:
        with self._lock:
            for claim_id in claim_ids:
                self._claims.pop(claim_id, None)

    def save_organizer_post(self, post: OrganizerPost) -> OrganizerPost:
        with self._lock:
            merged = merge_saved_post(post, self._posts.get(post.post_id))
            self._posts[merged.post_id] = merged
            return merged

    def get_organizer_post(self, post_id: str) -> OrganizerPost | None:
        with self._lock:
            return self._posts.get(post_id)

    def list_organizer_posts(self, status: str | None = None) -> list[OrganizerPost]:
        with self._lock:
            return [p for p in self._posts.values() if status is None or p.status == status]

    def update_post_state(
        self,
        post_id: str,
        *,
        status: str | None = None,
        placement: PostPlacement | None = None,
        organizer_confirmed: bool | None = None,
        now: datetime | None = None,
    ) -> OrganizerPost | None:
        with self._lock:
            existing = self._posts.get(post_id)
            if existing is None:
                return None
            updated = _with_state(
                existing,
                status=status,
                placement=placement,
                organizer_confirmed=organizer_confirmed,
                now=now,
            )
            self._posts[post_id] = updated
            return updated

    def increment_event_metric(self, event_id: str, kind: str, *, jst_date: str) -> None:
        with self._lock:
            self._metrics[event_id] = _bump_metrics(
                self._metrics.get(event_id), event_id, kind, jst_date=jst_date, now=datetime.now(timezone.utc)
            )

    def get_event_metrics(self, event_id: str) -> EventMetrics | None:
        with self._lock:
            return self._metrics.get(event_id)

    def list_calendar_counts(self) -> dict[str, int]:
        with self._lock:
            return {key: value.calendar for key, value in self._metrics.items() if value.calendar > 0}


def create_store() -> Store:
    """Pick the backend from configuration.

    Imported lazily so that a demo or test run never needs the Firestore
    client library installed or a project configured.
    """
    from event_agent.config import get_settings

    if get_settings().firestore_enabled:
        from event_agent.storage.firestore_store import FirestoreStore

        return FirestoreStore()
    return MemoryStore()


store: Store = create_store()
