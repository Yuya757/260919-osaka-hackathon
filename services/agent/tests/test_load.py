"""Concurrency behaviour under load (§13.3 Load).

§13.3 asks for「同時手動Runと定期Job重複時のロック・クォータ動作」. The four
things that can actually go wrong when runs overlap:

1. a duplicated scheduled trigger collects twice (§9.3 の定期Runキー),
2. a retried manual POST collects twice (§9.3 の Idempotency-Key),
3. the per-run limits of §9.2 stop being per-run,
4. accepting a run stops being cheap, breaking §11.1「p95 2秒以内」.

Each is asserted here against both store backends, because the lock is a
transaction on Firestore and a mutex in memory, and only one of those is what
production will use.
"""

from __future__ import annotations

import asyncio
import time
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from event_agent.config import settings
from event_agent.schemas import UserPreferences
from event_agent.workflows.collect import (
    run_collect_workflow,
    run_daily_collection,
    scheduled_idempotency_key,
)

JST = timezone(timedelta(hours=9))
NOW = datetime(2026, 9, 21, 9, 0, tzinfo=JST)

CONCURRENCY = 8


def preferences() -> UserPreferences:
    return UserPreferences()


# ---- §9.3 定期Runのキー ----

def test_scheduled_key_is_stable_within_one_jst_day() -> None:
    morning = datetime(2026, 9, 21, 7, 0, tzinfo=JST)
    evening = datetime(2026, 9, 21, 23, 30, tzinfo=JST)

    assert scheduled_idempotency_key(
        "u1", now=morning, schedule_version="daily-1"
    ) == scheduled_idempotency_key("u1", now=evening, schedule_version="daily-1")


def test_scheduled_key_uses_the_jst_date_not_utc() -> None:
    """07:00 JST is still the previous day in UTC. The key must not split."""
    seven_jst = datetime(2026, 9, 21, 7, 0, tzinfo=JST)
    same_moment_utc = seven_jst.astimezone(timezone.utc)
    assert same_moment_utc.date() != seven_jst.date(), "fixture must straddle midnight"

    assert scheduled_idempotency_key(
        "u1", now=seven_jst, schedule_version="daily-1"
    ) == scheduled_idempotency_key(
        "u1", now=same_moment_utc, schedule_version="daily-1"
    )


def test_scheduled_key_differs_by_day_user_and_version() -> None:
    base = dict(now=NOW, schedule_version="daily-1")
    keys = {
        scheduled_idempotency_key("u1", **base),
        scheduled_idempotency_key("u2", **base),
        scheduled_idempotency_key("u1", now=NOW + timedelta(days=1), schedule_version="daily-1"),
        scheduled_idempotency_key("u1", now=NOW, schedule_version="daily-2"),
    }
    assert len(keys) == 4


# ---- §13.3 ロック ----

@pytest.mark.asyncio
async def test_duplicate_scheduled_triggers_collect_once(store_backend) -> None:
    """A schedule that fires twice, or a retried Job, must not collect twice."""
    results = await asyncio.gather(
        *(
            run_daily_collection(preferences(), user_id="u1", now=NOW)
            for _ in range(CONCURRENCY)
        )
    )

    started = [run for run, did_start in results if did_start]
    assert len(started) == 1, "exactly one trigger may own the day"

    run_ids = {run.run_id for run, _ in results}
    assert len(run_ids) == 1, "every caller must be handed the same run"

    owner = started[0]
    assert owner.trigger_type == "scheduled"
    assert store_backend.get_run(owner.run_id) is not None


@pytest.mark.asyncio
async def test_a_different_day_is_a_different_scheduled_run(store_backend) -> None:
    today, _ = await run_daily_collection(preferences(), user_id="u1", now=NOW)
    tomorrow, started = await run_daily_collection(
        preferences(), user_id="u1", now=NOW + timedelta(days=1)
    )

    assert started is True
    assert tomorrow.run_id != today.run_id


@pytest.mark.asyncio
async def test_different_users_do_not_share_the_lock(store_backend) -> None:
    first, _ = await run_daily_collection(preferences(), user_id="u1", now=NOW)
    second, started = await run_daily_collection(preferences(), user_id="u2", now=NOW)

    assert started is True
    assert second.run_id != first.run_id


@pytest.mark.asyncio
async def test_manual_runs_are_not_blocked_by_the_scheduled_one(store_backend) -> None:
    """§13.3「同時手動Runと定期Job重複時」. The two must not starve each other."""
    scheduled = run_daily_collection(preferences(), user_id="u1", now=NOW)
    manual = [run_collect_workflow(preferences(), True, now=NOW) for _ in range(4)]

    outcome = await asyncio.gather(scheduled, *manual)
    scheduled_run, started = outcome[0]
    manual_runs = list(outcome[1:])

    assert started is True
    assert all(run.status in ("succeeded", "partial_success") for run in manual_runs)
    assert scheduled_run.status in ("succeeded", "partial_success")

    ids = {run.run_id for run in manual_runs} | {scheduled_run.run_id}
    assert len(ids) == 5, "manual runs carry their own keys and stay separate"


# ---- §9.2 クォータ ----

@pytest.mark.asyncio
async def test_per_run_quotas_hold_under_concurrency(store_backend) -> None:
    runs = await asyncio.gather(
        *(run_collect_workflow(preferences(), True, now=NOW) for _ in range(CONCURRENCY))
    )

    for run in runs:
        assert run.query_count <= settings.max_search_queries
        assert run.candidate_count <= settings.max_candidates


@pytest.mark.asyncio
async def test_the_model_call_budget_is_per_run(store_backend) -> None:
    """§9.2「1 Run最大15回」.

    The budget used to be an attribute on the module singleton, reset at the
    start of each run, so a run beginning while another was in flight wiped the
    first run's counter and the cap stopped being per-run. It now lives in a
    ContextVar, which asyncio copies per task.
    """
    from event_agent.clients.gemini import gemini_client

    observed: list[int] = []

    async def spend(calls: int) -> None:
        gemini_client.reset_call_budget()
        for _ in range(calls):
            gemini_client._take_call()
            await asyncio.sleep(0)
        observed.append(gemini_client.calls_used)

    await asyncio.gather(spend(3), spend(5), spend(7))

    assert sorted(observed) == [3, 5, 7], "budgets must not leak between runs"


@pytest.mark.asyncio
async def test_the_budget_refuses_calls_past_the_limit() -> None:
    from event_agent.clients.gemini import gemini_client

    gemini_client.reset_call_budget()
    allowed = sum(1 for _ in range(settings.max_model_calls + 5) if gemini_client._take_call())

    assert allowed == settings.max_model_calls


# ---- §11.1 受付レイテンシ ----

@pytest.mark.asyncio
async def test_accepting_concurrent_manual_runs_stays_fast(store_backend) -> None:
    """§11.1「手動Run受付API p95 2秒以内にRun IDを返す」.

    Acceptance must not wait for collection, so this measures the POST alone
    while several of them arrive together.
    """
    from event_agent.entrypoints.service import app

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:

        async def accept(index: int) -> float:
            started = time.perf_counter()
            response = await client.post(
                "/api/agent-runs",
                json={"forceRefresh": True},
                headers={"Idempotency-Key": f"load-{index}"},
            )
            elapsed = time.perf_counter() - started
            assert response.status_code == 200
            assert response.json()["runId"]
            return elapsed

        timings = await asyncio.gather(*(accept(i) for i in range(CONCURRENCY)))

    timings = sorted(timings)
    p95 = timings[max(0, int(len(timings) * 0.95) - 1)]
    assert p95 < 2.0, f"p95 acceptance took {p95:.3f}s (§11.1 allows 2s)"


@pytest.mark.asyncio
async def test_a_retried_post_does_not_start_a_second_run(store_backend) -> None:
    """§9.3. A client retrying the same key concurrently gets one run."""
    from event_agent.entrypoints.service import app

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        responses = await asyncio.gather(
            *(
                client.post(
                    "/api/agent-runs",
                    json={"forceRefresh": True},
                    headers={"Idempotency-Key": "retried-key"},
                )
                for _ in range(CONCURRENCY)
            )
        )

    run_ids = {response.json()["runId"] for response in responses}
    assert len(run_ids) == 1


# ---- Job エントリポイント ----

@pytest.mark.asyncio
async def test_the_job_claims_the_day_and_a_retry_exits_zero(store_backend) -> None:
    """A retried Cloud Run Job execution must exit 0 without collecting again."""
    from event_agent.entrypoints.job import collect_theme
    from event_agent.workflows.collect import run_theme_collection
    from event_agent.workflows.themes import theme_by_id

    theme = theme_by_id("hackathon-kansai")
    assert await collect_theme(theme) == 0

    # The job derives its key from today's JST date and the theme, so a
    # scheduled call for the same day now finds it taken. That is what the
    # retry relies on.
    run, started = await run_theme_collection(theme)
    assert started is False
    assert run.trigger_type == "scheduled"
    assert run.theme_id == "hackathon-kansai"
    assert run.status in ("succeeded", "partial_success")

    assert await collect_theme(theme) == 0


# ---- 課金単位の分計と日次上限 ----

def test_call_budget_counts_grounding_and_text_separately() -> None:
    from event_agent.clients.gemini import _CallBudget

    budget = _CallBudget(limit=3)
    assert budget.take("grounding") and budget.take("text") and budget.take("grounding")
    assert not budget.take("text")
    assert (budget.grounding_used, budget.text_used, budget.used) == (2, 1, 3)


@pytest.mark.asyncio
async def test_concurrent_reservations_never_exceed_the_cap(store_backend) -> None:
    import asyncio

    results = await asyncio.gather(
        *(asyncio.to_thread(store_backend.reserve_grounding_calls, "2026-09-21", 4, cap=16) for _ in range(8))
    )
    assert sum(results) == 4
    assert store_backend.get_usage("2026-09-21").grounding_calls == 16
