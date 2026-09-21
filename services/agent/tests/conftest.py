"""Shared fixtures.

Note: ``reset_store`` is deliberately **not** autouse. ``test_contracts.py``
uses a module-scoped ``finished_run`` fixture, and a function-scoped autouse
reset would wipe the run between the fixture and the tests that consume it.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

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
    from event_agent.store import store

    store.reset()
    yield store
    store.reset()
