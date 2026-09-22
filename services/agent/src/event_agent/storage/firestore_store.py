"""Firestore backend for :class:`event_agent.storage.store.Store` (§7).

Collection layout, taken from the data requirements:

``agentRuns/{runId}``                      §7.1 run record
``agentRuns/{runId}/evidence/{evidenceId}`` §7.2 minimal quoted evidence
``events/{dedupKey}``                       §7.3 event candidate
``agentRunKeys/{hash(idempotencyKey)}``     §9.3 run idempotency index
``sessions/{hash(sessionId)}``              chat session state
``appState/latestRun``                      pointer used by ``list_events(None)``
``organizerPosts/{postId}``                 F-06 organizer post (ADR-006)
``eventMetrics/{eventId}``                  clicks and calendar registrations (ADR-009)

Two of those collections are not in §7. ``agentRunKeys`` exists because §9.3
requires a manual run to be idempotent on the client's ``Idempotency-Key``, and
a document at a key-derived path is the only way to claim that key without a
race. ``appState/latestRun`` exists because the API's ``GET /api/events`` with
no run id means "the newest results", which is otherwise unanswerable without
an ordered query and a composite index.

Event documents are keyed by ``dedupKey`` rather than ``eventId`` so that
re-collecting the same event writes to the same path. That makes the write
idempotent by construction instead of by a read-then-search.
"""

from __future__ import annotations

import hashlib
import os
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from event_agent.config import get_settings
from event_agent.schemas import (
    AgentRun,
    ApiEvent,
    Evidence,
    EventMetrics,
    OrganizerPost,
    PostPlacement,
    UserPreferences,
)
from event_agent.storage.store import (
    SessionState,
    _with_state,
    display_order,
    merge_saved_event,
    merge_saved_post,
)

RUNS = "agentRuns"
RUN_KEYS = "agentRunKeys"
EVIDENCE = "evidence"
EVENTS = "events"
SESSIONS = "sessions"
APP_STATE = "appState"
LATEST_RUN_DOC = "latestRun"
ORGANIZER_POSTS = "organizerPosts"
EVENT_METRICS = "eventMetrics"


def _path_id(raw: str) -> str:
    """Hash a caller-supplied string into a safe document id.

    Idempotency keys and session ids arrive from HTTP clients, so they may
    contain ``/``, be ``..``, or exceed the 1500-byte document-id limit. The
    original value is kept as a field on the document.
    """
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _dump(model: Any) -> dict[str, Any]:
    """Serialize a Pydantic model the way §7 spells the fields (camelCase)."""
    return model.model_dump(by_alias=True, mode="python")


class FirestoreStore:
    """Persists §7 collections. Safe to construct once per process."""

    def __init__(self, client: Any | None = None) -> None:
        if client is None:
            from google.cloud import firestore

            settings = get_settings()
            client = firestore.Client(
                project=settings.gcp_project_id,
                database=settings.firestore_database,
            )
        self._db = client

    # ------------------------------------------------------------------ tests

    @property
    def _is_emulated(self) -> bool:
        return bool(os.environ.get("FIRESTORE_EMULATOR_HOST"))

    def reset(self) -> None:
        """Delete every document this store owns.

        Refused unless ``FIRESTORE_EMULATOR_HOST`` is set. The evaluation
        harness calls ``reset()`` between cases, and pointing that at a real
        project would erase production data.
        """
        if not self._is_emulated:
            raise RuntimeError(
                "FirestoreStore.reset() is only allowed against the emulator"
            )
        for name in (RUNS, RUN_KEYS, EVENTS, SESSIONS, APP_STATE, ORGANIZER_POSTS, EVENT_METRICS):
            for doc in self._db.collection(name).stream():
                for sub in doc.reference.collections():
                    for child in sub.stream():
                        child.reference.delete()
                doc.reference.delete()

    # --------------------------------------------------------------- sessions

    def get_or_create_session(self, session_id: str | None) -> SessionState:
        if session_id:
            snapshot = self._db.collection(SESSIONS).document(
                _path_id(session_id)
            ).get()
            if snapshot.exists:
                data = snapshot.to_dict() or {}
                return SessionState(
                    session_id=data.get("sessionId", session_id),
                    preferences=UserPreferences(**(data.get("preferences") or {})),
                    messages=list(data.get("messages") or []),
                    updated_at=data.get("updatedAt")
                    or datetime.now(timezone.utc),
                )
        return SessionState(session_id=session_id or str(uuid4()))

    def save_session(self, session: SessionState) -> None:
        session.updated_at = datetime.now(timezone.utc)
        self._db.collection(SESSIONS).document(_path_id(session.session_id)).set(
            {
                "sessionId": session.session_id,
                "preferences": _dump(session.preferences),
                "messages": session.messages,
                "updatedAt": session.updated_at,
            }
        )

    # ------------------------------------------------------------------- runs

    def create_run(self, run: AgentRun) -> AgentRun:
        """Claim the idempotency key, or hand back the run that already holds it.

        The claim and the run document are written in one transaction so two
        concurrent requests carrying the same ``Idempotency-Key`` cannot both
        start a workflow (§9.3).
        """
        from google.cloud import firestore

        key_ref = self._db.collection(RUN_KEYS).document(
            _path_id(run.idempotency_key)
        )
        run_ref = self._db.collection(RUNS).document(run.run_id)

        @firestore.transactional
        def _claim(transaction: Any) -> str | None:
            existing = key_ref.get(transaction=transaction)
            if existing.exists:
                return (existing.to_dict() or {}).get("runId")
            transaction.set(
                key_ref,
                {
                    "runId": run.run_id,
                    "idempotencyKey": run.idempotency_key,
                    "createdAt": datetime.now(timezone.utc),
                },
            )
            transaction.set(run_ref, _dump(run))
            return None

        claimed_by = _claim(self._db.transaction())
        if claimed_by and claimed_by != run.run_id:
            existing_run = self.get_run(claimed_by)
            if existing_run:
                return existing_run
        return run

    def update_run(self, run: AgentRun) -> AgentRun:
        self._db.collection(RUNS).document(run.run_id).set(_dump(run))
        return run

    def get_run(self, run_id: str) -> AgentRun | None:
        snapshot = self._db.collection(RUNS).document(run_id).get()
        if not snapshot.exists:
            return None
        return AgentRun(**(snapshot.to_dict() or {}))

    # ----------------------------------------------------------------- events

    def save_events(self, run_id: str, events: list[ApiEvent]) -> list[ApiEvent]:
        refs = {
            event.dedup_key: self._db.collection(EVENTS).document(event.dedup_key)
            for event in events
        }
        existing: dict[str, ApiEvent] = {}
        if refs:
            # One round trip for the whole run rather than one read per event.
            for snapshot in self._db.get_all(list(refs.values())):
                if snapshot.exists:
                    found = ApiEvent(**(snapshot.to_dict() or {}))
                    existing[found.dedup_key] = found

        stored: list[ApiEvent] = []
        batch = self._db.batch()
        for event in events:
            merged = merge_saved_event(event, existing.get(event.dedup_key))
            batch.set(refs[event.dedup_key], _dump(merged))
            stored.append(merged)
        # 空の保存で「最新の Run」を進めない（検索を省いた Run が一覧を空にしないため）
        if stored:
            batch.set(
                self._db.collection(APP_STATE).document(LATEST_RUN_DOC),
                {"runId": run_id, "updatedAt": datetime.now(timezone.utc)},
            )
        batch.commit()
        return display_order(stored)

    def list_recent_events(self, since: datetime, *, limit: int = 500) -> list[ApiEvent]:
        # 単一フィールドの範囲条件だけなら自動索引で済み、composite index は要らない（ADR-002）
        from google.cloud.firestore_v1.base_query import FieldFilter

        query = (
            self._db.collection(EVENTS)
            .where(filter=FieldFilter("lastSeenAt", ">=", since))
            .limit(limit)
        )
        return [ApiEvent(**(s.to_dict() or {})) for s in query.stream()]

    def find_events_by_urls(self, normalized_urls: list[str]) -> dict[str, ApiEvent]:
        from google.cloud.firestore_v1.base_query import FieldFilter

        found: dict[str, ApiEvent] = {}
        urls = list(dict.fromkeys(normalized_urls))
        # "in" は 30 件まで
        for start in range(0, len(urls), 30):
            chunk = urls[start : start + 30]
            query = self._db.collection(EVENTS).where(
                filter=FieldFilter("normalizedOfficialUrl", "in", chunk)
            )
            for snapshot in query.stream():
                event = ApiEvent(**(snapshot.to_dict() or {}))
                found[event.normalized_official_url] = event
        return found

    def touch_events(self, dedup_keys: list[str], *, last_seen_at: datetime) -> None:
        if not dedup_keys:
            return
        # update() は無い文書で失敗する。merge の set なら無い鍵は空文書を作ってしまうので、
        # 存在するものだけを1回の get_all で確かめてから更新する
        refs = [self._db.collection(EVENTS).document(key) for key in dedup_keys]
        existing = [snap.reference for snap in self._db.get_all(refs) if snap.exists]
        if not existing:
            return
        batch = self._db.batch()
        for ref in existing:
            batch.update(ref, {"lastSeenAt": last_seen_at})
        batch.commit()

    def get_evidence_for_events(self, events: list[ApiEvent]) -> dict[str, list[Evidence]]:
        refs = []
        owners: list[tuple[str, str]] = []
        for event in events:
            collection = (
                self._db.collection(RUNS).document(event.source_run_id).collection(EVIDENCE)
            )
            for eid in event.evidence_ids:
                refs.append(collection.document(eid))
                owners.append((event.event_id, eid))
        by_event: dict[str, dict[str, Evidence]] = {e.event_id: {} for e in events}
        if refs:
            # run を跨いだ参照でも get_all は一度で引ける
            for snapshot in self._db.get_all(refs):
                if not snapshot.exists:
                    continue
                item = Evidence(**(snapshot.to_dict() or {}))
                run_id = snapshot.reference.parent.parent.id
                for event in events:
                    if event.source_run_id == run_id and item.evidence_id in event.evidence_ids:
                        by_event[event.event_id][item.evidence_id] = item
        # 要求順を保つ
        return {
            e.event_id: [by_event[e.event_id][eid] for eid in e.evidence_ids if eid in by_event[e.event_id]]
            for e in events
        }

    def latest_collection_at(self) -> datetime | None:
        snapshot = self._db.collection(APP_STATE).document(LATEST_RUN_DOC).get()
        if not snapshot.exists:
            return None
        return (snapshot.to_dict() or {}).get("updatedAt")

    def get_event(self, event_id: str) -> ApiEvent | None:
        found = self._where_eq(EVENTS, "eventId", event_id).limit(1).stream()
        for snapshot in found:
            return ApiEvent(**(snapshot.to_dict() or {}))
        return None

    def list_events(self, source_run_id: str | None = None) -> list[ApiEvent]:
        run_id = source_run_id or self._latest_run_id()
        if not run_id:
            return []
        snapshots = self._where_eq(EVENTS, "sourceRunId", run_id).stream()
        return display_order([ApiEvent(**(s.to_dict() or {})) for s in snapshots])

    def _latest_run_id(self) -> str | None:
        snapshot = self._db.collection(APP_STATE).document(LATEST_RUN_DOC).get()
        if not snapshot.exists:
            return None
        return (snapshot.to_dict() or {}).get("runId")

    def _where_eq(self, collection: str, field: str, value: Any) -> Any:
        """Equality query. ``FieldFilter`` replaced the positional form of
        ``where()`` in google-cloud-firestore 2.x, and it must be passed by
        keyword."""
        from google.cloud.firestore_v1.base_query import FieldFilter

        return self._db.collection(collection).where(
            filter=FieldFilter(field, "==", value)
        )

    # --------------------------------------------------------------- evidence

    def save_evidence(self, run_id: str, evidence: list[Evidence]) -> None:
        if not evidence:
            return
        batch = self._db.batch()
        collection = self._db.collection(RUNS).document(run_id).collection(EVIDENCE)
        for item in evidence:
            batch.set(collection.document(item.evidence_id), _dump(item))
        batch.commit()

    def get_evidence(self, run_id: str, evidence_ids: list[str]) -> list[Evidence]:
        if not evidence_ids:
            return []
        collection = self._db.collection(RUNS).document(run_id).collection(EVIDENCE)
        refs = [collection.document(eid) for eid in evidence_ids]
        by_id: dict[str, Evidence] = {}
        for snapshot in self._db.get_all(refs):
            if snapshot.exists:
                item = Evidence(**(snapshot.to_dict() or {}))
                by_id[item.evidence_id] = item
        # get_all does not preserve request order, so restore the caller's.
        return [by_id[eid] for eid in evidence_ids if eid in by_id]

    # ------------------------------------------------------- organizer posts

    def save_organizer_post(self, post: OrganizerPost) -> OrganizerPost:
        ref = self._db.collection(ORGANIZER_POSTS).document(post.post_id)
        snapshot = ref.get()
        existing = OrganizerPost(**(snapshot.to_dict() or {})) if snapshot.exists else None
        merged = merge_saved_post(post, existing)
        ref.set(_dump(merged))
        return merged

    def get_organizer_post(self, post_id: str) -> OrganizerPost | None:
        snapshot = self._db.collection(ORGANIZER_POSTS).document(post_id).get()
        if not snapshot.exists:
            return None
        return OrganizerPost(**(snapshot.to_dict() or {}))

    def list_organizer_posts(self, status: str | None = None) -> list[OrganizerPost]:
        # 並び順はクエリに持たせない。単一フィールドの等価条件だけなら
        # composite index が要らず、ADR-002 の運用（rules しか deploy しない）で済む。
        query = (
            self._where_eq(ORGANIZER_POSTS, "status", status)
            if status
            else self._db.collection(ORGANIZER_POSTS)
        )
        return [OrganizerPost(**(s.to_dict() or {})) for s in query.stream()]

    def update_post_state(
        self,
        post_id: str,
        *,
        status: str | None = None,
        placement: PostPlacement | None = None,
        organizer_confirmed: bool | None = None,
        now: datetime | None = None,
    ) -> OrganizerPost | None:
        ref = self._db.collection(ORGANIZER_POSTS).document(post_id)
        snapshot = ref.get()
        if not snapshot.exists:
            return None
        updated = _with_state(
            OrganizerPost(**(snapshot.to_dict() or {})),
            status=status,
            placement=placement,
            organizer_confirmed=organizer_confirmed,
            now=now,
        )
        ref.set(_dump(updated))
        return updated

    # ---------------------------------------------------------------- metrics

    def increment_event_metric(self, event_id: str, kind: str, *, jst_date: str) -> None:
        from google.cloud import firestore

        # read-then-write を避け、Increment だけで加算する。無ければ merge で作られる
        top = {"calendar": firestore.Increment(1)} if kind == "calendar" else {
            "clicks": {kind: firestore.Increment(1)}
        }
        day = {"calendar": firestore.Increment(1)} if kind == "calendar" else {"clicks": firestore.Increment(1)}
        self._db.collection(EVENT_METRICS).document(event_id).set(
            {
                "eventId": event_id,
                **top,
                "daily": {jst_date: day},
                "updatedAt": datetime.now(timezone.utc),
            },
            merge=True,
        )

    def get_event_metrics(self, event_id: str) -> EventMetrics | None:
        snapshot = self._db.collection(EVENT_METRICS).document(event_id).get()
        if not snapshot.exists:
            return None
        return EventMetrics(**(snapshot.to_dict() or {}))
