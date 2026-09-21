from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from threading import Lock
from uuid import uuid4

from event_agent.schemas import AgentRun, ApiEvent, Evidence, UserPreferences


@dataclass
class SessionState:
    session_id: str
    preferences: UserPreferences = field(default_factory=UserPreferences)
    messages: list[dict[str, str]] = field(default_factory=list)
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class MemoryStore:
    def __init__(self) -> None:
        self._lock = Lock()
        self._sessions: dict[str, SessionState] = {}
        self._runs: dict[str, AgentRun] = {}
        self._events_by_run: dict[str, list[ApiEvent]] = {}
        self._latest_events: list[ApiEvent] = []
        self._evidence: dict[str, Evidence] = {}

    def reset(self) -> None:
        """Drop all state. Used between evaluation cases so they cannot leak."""
        with self._lock:
            self._sessions.clear()
            self._runs.clear()
            self._events_by_run.clear()
            self._latest_events = []
            self._evidence.clear()

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
            self._runs[run.run_id] = run
            return run

    def update_run(self, run: AgentRun) -> AgentRun:
        with self._lock:
            self._runs[run.run_id] = run
            return run

    def get_run(self, run_id: str) -> AgentRun | None:
        with self._lock:
            return self._runs.get(run_id)

    def save_events(self, run_id: str, events: list[ApiEvent]) -> None:
        with self._lock:
            self._events_by_run[run_id] = events
            self._latest_events = events

    def save_evidence(self, evidence: list[Evidence]) -> None:
        with self._lock:
            for item in evidence:
                self._evidence[item.evidence_id] = item

    def get_evidence(self, evidence_ids: list[str]) -> list[Evidence]:
        with self._lock:
            return [
                self._evidence[eid] for eid in evidence_ids if eid in self._evidence
            ]

    def list_events(self, source_run_id: str | None = None) -> list[ApiEvent]:
        with self._lock:
            if source_run_id:
                return list(self._events_by_run.get(source_run_id, []))
            return list(self._latest_events)


store = MemoryStore()
