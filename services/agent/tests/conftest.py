"""Shared fixtures.

Note: ``reset_store`` is deliberately **not** autouse. ``test_contracts.py``
uses a module-scoped ``finished_run`` fixture, and a function-scoped autouse
reset would wipe the run between the fixture and the tests that consume it.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

import pytest

# 既定（本番の安全側）は手動探索オフだが、テストは Run を起点にした流れを検証する。
# Settings は最初の import 時に読むので、event_agent を import する前に立てる。
os.environ.setdefault("MANUAL_RUNS_ENABLED", "true")

JST = timezone(timedelta(hours=9))

# デモカタログが2026年のイベントを持つため、評価とテストの基準時刻を固定する。
# datetime.now() に依存すると、時間の経過でテストが壊れる。
FROZEN_NOW = datetime(2026, 9, 21, 9, 0, tzinfo=JST)


@pytest.fixture
def frozen_now() -> datetime:
    return FROZEN_NOW


@pytest.fixture
def reset_store():
    """Clear the in-process store before and after a test."""
    from event_agent.storage.store import store

    store.reset()
    yield store
    store.reset()


# --- store backends -------------------------------------------------------
#
# Every module binds ``store`` at import time, so swapping the backend has to
# reach all of them; patching only ``event_agent.storage.store`` would leave the
# workflow running on whichever backend it imported.

STORE_HOLDERS = (
    "event_agent.storage.store",
    "event_agent.workflows.collect",
    "event_agent.workflows.organizer_posts",
    "event_agent.workflows.pool",
    "event_agent.workflows.pool_search",
    "event_agent.entrypoints.service",
    "event_agent.agents.chat",
    "event_agent.evaluation.harness",
)

EMULATOR_PROJECT = "osaka-hackathon-test"


def install_store(monkeypatch, backend):
    for module in STORE_HOLDERS:
        monkeypatch.setattr(f"{module}.store", backend)
    return backend


def build_firestore_store():
    """A FirestoreStore pointed at the emulator, or a skip if there is none."""
    import os

    if not os.environ.get("FIRESTORE_EMULATOR_HOST"):
        pytest.skip(
            "FIRESTORE_EMULATOR_HOST is not set; run scripts/run-integration-tests.sh"
        )
    pytest.importorskip("google.cloud.firestore")
    from google.cloud import firestore

    from event_agent.storage.firestore_store import FirestoreStore

    backend = FirestoreStore(
        firestore.Client(project=EMULATOR_PROJECT, database="(default)")
    )
    backend.reset()
    return backend


@pytest.fixture
def firestore_backend(monkeypatch):
    """Firestore only. Skips without the emulator."""
    backend = build_firestore_store()
    install_store(monkeypatch, backend)
    yield backend
    backend.reset()


@pytest.fixture(params=["memory", "firestore"])
def store_backend(request, monkeypatch):
    """Both backends. The Firestore parameter skips without the emulator."""
    from event_agent.storage.store import MemoryStore

    if request.param == "memory":
        backend = MemoryStore()
        install_store(monkeypatch, backend)
        yield backend
        return

    backend = build_firestore_store()
    install_store(monkeypatch, backend)
    yield backend
    backend.reset()
