"""共有プールと読み出し時の採点（ADR-008）。"""

from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient

from conftest import FROZEN_NOW
from event_agent.config import get_settings
from event_agent.entrypoints.service import app
from event_agent.schemas import UserPreferences
from event_agent.workflows.collect import run_collect_workflow
from event_agent.workflows.pool import ranked_pool


def _finish(client: TestClient, run_id: str) -> dict:
    for _ in range(200):
        body = client.get(f"/api/agent-runs/{run_id}").json()
        if body["status"] in ("succeeded", "partial_success", "failed"):
            return body
        time.sleep(0.05)
    raise AssertionError("run did not finish")


@pytest.mark.asyncio
async def test_ranked_pool_scores_without_persisting(store_backend):
    run = await run_collect_workflow(UserPreferences(), True, now=FROZEN_NOW)
    kyoto = UserPreferences(interestsPrompt="ハッカソン", locations=["京都"])
    ranked, evidence = ranked_pool(kyoto, now=FROZEN_NOW)
    assert ranked and all(e.recommendation is not None for e in ranked)
    assert set(evidence) == {e.event_id for e in ranked}
    # 保存されたスコアは Run 時のもので、読み出し時の採点で書き換わっていない
    stored = {e.event_id: e for e in store_backend.list_events(run.run_id)}
    assert any(stored[e.event_id].recommendation.score != e.recommendation.score for e in ranked)


def test_events_without_run_id_return_the_pool_ranked_by_session(store_backend):
    with TestClient(app) as client:
        run_id = client.post("/api/agent-runs", json={"forceRefresh": True}).json()["runId"]
        _finish(client, run_id)

        default = client.get("/api/events").json()
        assert default["lastCollectedAt"]
        titles = [e["title"] for e in default["events"]]
        assert titles
        scores = [e["recommendation"]["score"] for e in default["events"]]
        assert scores == sorted(scores, reverse=True)
        assert all(e["evidencePreview"] for e in default["events"])

        chat = client.post("/api/chat", json={"message": "オンラインのミートアップだけ"}).json()
        online = client.get("/api/events", params={"sessionId": chat["sessionId"]}).json()
        assert online["events"][0]["location"]["type"] in ("online", "hybrid")
        assert set(e["eventId"] for e in online["events"]) == set(e["eventId"] for e in default["events"])


def test_manual_runs_can_be_disabled(store_backend, monkeypatch):
    monkeypatch.setattr(get_settings(), "manual_runs_enabled", False)
    with TestClient(app) as client:
        assert client.get("/api/health").json()["manualRunsEnabled"] is False
        refused = client.post("/api/agent-runs", json={"forceRefresh": True})
        assert refused.status_code == 403
        assert "手動の探索" in refused.json()["detail"]
        chat = client.post("/api/chat", json={"message": "関西のハッカソンを探して"}).json()
        kinds = [a["type"] for a in chat["actions"]]
        assert "agent_run_started" not in kinds
        assert "events_ready" in kinds
        assert "並べ替え" in chat["reply"]


@pytest.mark.asyncio
async def test_pool_leaves_out_paused_kinds(store_backend):
    """補助金などは収集を止めても過去の分がプールに残る。一覧には出さない。"""
    from event_agent.workflows.collect import run_theme_collection
    from event_agent.workflows.pool import candidates
    from event_agent.workflows.themes import theme_by_id

    await run_theme_collection(theme_by_id("subsidy-dx"), now=FROZEN_NOW)
    assert any(e.kind == "subsidy" for e in store_backend.list_events())
    assert all(e.kind in ("hackathon", "contest") for e in candidates(now=FROZEN_NOW))
