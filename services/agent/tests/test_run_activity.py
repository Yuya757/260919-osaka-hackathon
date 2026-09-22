"""Run の「エージェントの動き」（activity）。UI が各役割の進行を見せるために使う。"""

from __future__ import annotations

import time

import pytest

from conftest import FROZEN_NOW
from event_agent.schemas import RUN_ACTIVITY_MAX, AgentRun, UserPreferences
from event_agent.workflows.collect import run_collect_workflow


@pytest.mark.asyncio
async def test_finished_run_reports_every_role(store_backend):
    run = await run_collect_workflow(UserPreferences(), True, now=FROZEN_NOW)
    stored = store_backend.get_run(run.run_id)
    assert stored is not None
    agents = [line.agent for line in stored.activity]
    assert {"planner", "searcher", "extractor", "organizer"} <= set(agents)
    # 役割の順序はパイプラインの順序。計画が先で、整理が最後
    assert agents.index("planner") < agents.index("searcher") < agents.index("extractor")
    assert agents[-1] == "organizer"
    messages = " ".join(line.message for line in stored.activity)
    assert "検索クエリを" in messages and "件を保存" in messages
    assert all(len(line.message) <= 300 for line in stored.activity)


def test_activity_is_bounded():
    run = AgentRun(runId="r", idempotencyKey="k", status="queued")
    for i in range(RUN_ACTIVITY_MAX + 25):
        run.log("planner", f"line {i}")
    assert len(run.activity) == RUN_ACTIVITY_MAX
    assert run.activity[0].message == "line 25"
    assert run.activity[-1].message == f"line {RUN_ACTIVITY_MAX + 24}"


def test_run_uses_the_chat_session_preferences(store_backend):
    """「探す」はチャットで更新した関心条件で探索する（sessionId を引き継ぐ）。"""
    from fastapi.testclient import TestClient

    from event_agent.entrypoints.service import app

    with TestClient(app) as client:
        chat = client.post("/api/chat", json={"message": "京都 生成AI"}).json()
        assert not any(a["type"] == "agent_run_started" for a in chat.get("actions", []))
        created = client.post(
            "/api/agent-runs", json={"forceRefresh": True, "sessionId": chat["sessionId"]}
        )
        assert created.status_code == 200
        run_id = created.json()["runId"]
        for _ in range(200):
            body = client.get(f"/api/agent-runs/{run_id}").json()
            if body["status"] in ("succeeded", "partial_success", "failed"):
                break
            time.sleep(0.05)
        assert body["status"] != "queued"
        planner = " ".join(a["message"] for a in body["activity"] if a["agent"] == "planner")
        assert "京都" in planner and "生成AI" in planner
